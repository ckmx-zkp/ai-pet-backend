"""人设领域的数据库编排与小智 persona_pack 契约映射。"""

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from persona_compiler import KBEntry, compile_persona
from pet_common.dates import today_cn
from pet_common.models import (
    DailySignFortune,
    DeviceDailyContent,
    MBTIKBEntry,
    PersonaProfile,
    ZodiacKBEntry,
)
from web_api.owner_service import get_owner_profile, owner_prompt_fragment


def _latest_or_pinned(statement: Select[Any], kb_version: int | None) -> Select[Any]:
    if kb_version is not None:
        statement = statement.where(statement.selected_columns.version <= kb_version)
    return statement.order_by(statement.selected_columns.version.desc()).limit(1)


async def get_profile(session: AsyncSession, device_id: int) -> PersonaProfile | None:
    result = await session.execute(
        select(PersonaProfile).where(PersonaProfile.device_id == device_id)
    )
    return result.scalar_one_or_none()


async def get_zodiac_entry(
    session: AsyncSession, level: str, key: str, kb_version: int | None
) -> ZodiacKBEntry | None:
    statement = select(ZodiacKBEntry).where(
        ZodiacKBEntry.level == level,
        ZodiacKBEntry.key == key,
        ZodiacKBEntry.status == "published",
    )
    result = await session.execute(_latest_or_pinned(statement, kb_version))
    return result.scalar_one_or_none()


async def get_mbti_entry(
    session: AsyncSession, key: str, kb_version: int | None
) -> MBTIKBEntry | None:
    statement = select(MBTIKBEntry).where(
        MBTIKBEntry.key == key,
        MBTIKBEntry.status == "published",
    )
    result = await session.execute(_latest_or_pinned(statement, kb_version))
    return result.scalar_one_or_none()


def _as_kb_entry(entry: ZodiacKBEntry | MBTIKBEntry, level: str) -> KBEntry:
    return KBEntry(level=level, key=entry.key, version=entry.version, payload=entry.payload)


def _merge_list(payloads: Iterable[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    for payload in payloads:
        value = payload.get(key, [])
        if isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return list(dict.fromkeys(values))


def _last_value(payloads: Iterable[dict[str, Any]], key: str, default: Any) -> Any:
    value = default
    for payload in payloads:
        if key in payload:
            value = payload[key]
    return value


def _retrieval_hints(payloads: Iterable[dict[str, Any]]) -> list[str]:
    """兼容早期 dict 形态（取 tags）与当前服务间契约的字符串列表。"""
    hints: list[str] = []
    for payload in payloads:
        value = payload.get("retrieval_hints", [])
        if isinstance(value, list):
            hints.extend(item for item in value if isinstance(item, str))
        elif isinstance(value, dict):
            tags = value.get("tags", [])
            if isinstance(tags, list):
                hints.extend(item for item in tags if isinstance(item, str))
    return list(dict.fromkeys(hints))


_SIGN_NAMES = {
    "aries": "白羊座",
    "taurus": "金牛座",
    "gemini": "双子座",
    "cancer": "巨蟹座",
    "leo": "狮子座",
    "virgo": "处女座",
    "libra": "天秤座",
    "scorpio": "天蝎座",
    "sagittarius": "射手座",
    "capricorn": "摩羯座",
    "aquarius": "水瓶座",
    "pisces": "双鱼座",
}


def _identity_fragment(sun_sign: str, mbti: str) -> str:
    """身份片段：KB 片段只描述沟通风格，身份事实由编译层显式给出。

    没有它，模型在"不编造人设"的基础行为约束下只能否认自己有星座。
    """
    sign_name = _SIGN_NAMES.get(sun_sign, sun_sign)
    return f"你的星座是{sign_name}，MBTI 是 {mbti}；被问到时自然承认，平时不用主动提起。"


def _dossier_fragments(dossier: dict[str, Any]) -> list[str]:
    """稳定档案转为 prompt 片段；只取用户/Admin 明确保存的字段。"""
    labels = {
        "identity": "我是谁",
        "background": "背景",
        "roles": "角色",
        "goals": "目标",
        "evolution_rules": "进化规则",
        "relationship": "与主人的关系",
    }
    fragments: list[str] = []
    for key, label in labels.items():
        value = dossier.get(key)
        if isinstance(value, str) and value.strip():
            fragments.append(f"{label}：{value.strip()}")
        elif isinstance(value, list):
            items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
            if items:
                fragments.append(f"{label}：" + "；".join(items[:8]))
    return fragments


def _payload_text(payload: object, key: str) -> str | None:
    """jsonb payload 中取非空字符串字段；缺失返回 None。"""
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def get_daily_guidance(
    session: AsyncSession, device_id: int, sun_sign: str | None
) -> list[str]:
    """当日个性化引导语（E10/docs/12 §6）：greeting + 主人星座的当日运势总述。

    当日内容缺失时回退最近一期（昨日及以前）内容，并标注"今日早些时候"语义；
    全无内容才返回空列表，不阻塞编译。引导语由模型组织语言，不是固定 TTS 文本。
    """
    today = today_cn()
    fragments: list[str] = []
    greeting_payload = await session.scalar(
        select(DeviceDailyContent.payload).where(
            DeviceDailyContent.device_id == device_id,
            DeviceDailyContent.content_date == today,
            DeviceDailyContent.kind == "greeting",
        )
    )
    greeting_text = _payload_text(greeting_payload, "text")
    greeting_stale = False
    if greeting_text is None:
        # 昨日回退（docs/12 §6）：取最近一期 greeting
        fallback_payload = await session.scalar(
            select(DeviceDailyContent.payload)
            .where(
                DeviceDailyContent.device_id == device_id,
                DeviceDailyContent.content_date < today,
                DeviceDailyContent.kind == "greeting",
            )
            .order_by(DeviceDailyContent.content_date.desc())
            .limit(1)
        )
        greeting_text = _payload_text(fallback_payload, "text")
        greeting_stale = greeting_text is not None
    if greeting_text is not None:
        if greeting_stale:
            fragments.append(f"今天开场时可以延续今日早些时候的素材：{greeting_text}")
        else:
            fragments.append(f"今天开场时可以自然地提到：{greeting_text}")
    fortune_overall = None
    fortune_stale = False
    if sun_sign:
        fortune_payload = await session.scalar(
            select(DailySignFortune.payload).where(
                DailySignFortune.fortune_date == today, DailySignFortune.sign == sun_sign
            )
        )
        fortune_overall = _payload_text(fortune_payload, "overall")
        if fortune_overall is None:
            fallback_fortune = await session.scalar(
                select(DailySignFortune.payload)
                .where(
                    DailySignFortune.fortune_date < today, DailySignFortune.sign == sun_sign
                )
                .order_by(DailySignFortune.fortune_date.desc())
                .limit(1)
            )
            fortune_overall = _payload_text(fallback_fortune, "overall")
            fortune_stale = fortune_overall is not None
    if fortune_overall is not None:
        if fortune_stale:
            fragments.append(f"今天聊天时可以延续今日早些时候提到的运势：{fortune_overall}")
        else:
            fragments.append(f"今天聊天时可以自然地提到今日运势：{fortune_overall}")
    return fragments


async def compile_profile(session: AsyncSession, profile: PersonaProfile) -> dict[str, Any]:
    """从发布中的 KB 编译固定 7 字段的服务间 persona_pack。"""
    if profile.sun_sign is None or profile.mbti is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="persona not configured")

    pinned_version = None if profile.follow_latest else profile.kb_version
    sign = await get_zodiac_entry(session, "sign", profile.sun_sign, pinned_version)
    if sign is None or sign.parent_key is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="published zodiac KB unavailable")
    element = await get_zodiac_entry(session, "element", sign.parent_key, pinned_version)
    mbti = await get_mbti_entry(session, profile.mbti, pinned_version)
    if element is None or mbti is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="published persona KB unavailable")

    # E10：当日 greeting 与**主人**星座运势总述以引导语追加到片段末尾（docs/12 §6）
    owner = await get_owner_profile(session, profile.user_id)
    owner_sign = owner.sun_sign if owner is not None else None
    owner_line = owner_prompt_fragment(owner) if owner is not None else None
    daily_guidance = await get_daily_guidance(session, profile.device_id, owner_sign)
    compiled = compile_persona(
        _as_kb_entry(element, "element"),
        _as_kb_entry(sign, "sign"),
        _as_kb_entry(mbti, "mbti"),
        overrides={
            **profile.overrides,
            "prompt_fragments": _merge_list([profile.overrides], "prompt_fragments")
            + _dossier_fragments(profile.dossier),
        },
        daily_context="\n".join(daily_guidance) or None,
    )
    payloads = [element.payload, sign.payload, mbti.payload, profile.overrides]
    return {
        "kb_version": compiled["kb_version"],
        "system_prompt_fragments": [
            _identity_fragment(profile.sun_sign, profile.mbti),
            *([owner_line] if owner_line else []),
            *compiled["prompt_fragments"],
            *daily_guidance,
        ],
        "style_constraints": _merge_list(payloads, "style_constraints"),
        "taboo": compiled["taboo"],
        "default_emotion": _last_value(payloads, "default_emotion", "calm"),
        "blink_profile": _last_value(
            payloads, "blink_profile", {"interval_ms": 3200, "duration_ms": 180}
        ),
        "retrieval_hints": _retrieval_hints(payloads),
    }
