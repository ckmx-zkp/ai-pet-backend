"""人设领域的数据库编排与小智 persona_pack 契约映射。"""

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from persona_compiler import KBEntry, compile_persona
from pet_common.models import MBTIKBEntry, PersonaProfile, ZodiacKBEntry


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

    compiled = compile_persona(
        _as_kb_entry(element, "element"),
        _as_kb_entry(sign, "sign"),
        _as_kb_entry(mbti, "mbti"),
        overrides=profile.overrides,
    )
    payloads = [element.payload, sign.payload, mbti.payload, profile.overrides]
    return {
        "kb_version": compiled["kb_version"],
        "system_prompt_fragments": compiled["prompt_fragments"],
        "style_constraints": _merge_list(payloads, "style_constraints"),
        "taboo": compiled["taboo"],
        "default_emotion": _last_value(payloads, "default_emotion", "calm"),
        "blink_profile": _last_value(
            payloads, "blink_profile", {"interval_ms": 3200, "duration_ms": 180}
        ),
        "retrieval_hints": _retrieval_hints(payloads),
    }
