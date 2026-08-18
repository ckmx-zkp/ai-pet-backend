"""主人档案（一用户账号一行，多设备共享）。"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.models import Device, OwnerBaziProfile, OwnerProfile

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


async def get_owner_profile(session: AsyncSession, user_id: int) -> OwnerProfile | None:
    return await session.get(OwnerProfile, user_id)


async def get_or_create_owner_profile(session: AsyncSession, user_id: int) -> OwnerProfile:
    row = await session.get(OwnerProfile, user_id)
    if row is None:
        row = OwnerProfile(user_id=user_id, quiz_results={})
        session.add(row)
    return row


async def get_owner_bazi(session: AsyncSession, user_id: int) -> OwnerBaziProfile | None:
    return await session.get(OwnerBaziProfile, user_id)


async def claimed_device_ids_for_user(session: AsyncSession, user_id: int) -> list[int]:
    result = await session.execute(
        select(Device.id).where(Device.user_id == user_id).order_by(Device.id).limit(100)
    )
    return list(result.scalars().all())


def record_fun_quiz_result(
    owner: OwnerProfile,
    kind: str,
    scored: dict[str, Any],
    quiz_id: int,
    attempt_id: int,
) -> None:
    results = dict(owner.quiz_results) if isinstance(owner.quiz_results, dict) else {}
    results[kind] = {
        "archetype": scored.get("archetype"),
        "title": scored.get("title"),
        "summary": scored.get("summary"),
        "quiz_id": quiz_id,
        "attempt_id": attempt_id,
    }
    owner.quiz_results = results


def owner_prompt_fragment(owner: OwnerProfile) -> str | None:
    """注入 persona_pack：明确这些是主人信息，禁止模型认成自己。"""
    parts: list[str] = []
    if owner.sun_sign:
        sign_name = _SIGN_NAMES.get(owner.sun_sign, owner.sun_sign)
        parts.append(f"太阳星座是{sign_name}")
    if owner.mbti:
        parts.append(f"MBTI 是 {owner.mbti}")
    quizzes = owner.quiz_results if isinstance(owner.quiz_results, dict) else {}
    quiz_bits: list[str] = []
    for kind, payload in quizzes.items():
        if not isinstance(payload, dict):
            continue
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            quiz_bits.append(f"{kind}测出「{title.strip()[:40]}」")
    if quiz_bits:
        parts.append("他玩过的小测试：" + "；".join(quiz_bits[:4]))
    if not parts:
        return None
    return (
        "这些是主人的事，别说成你自己的："
        + "，".join(parts)
        + "。懂他就好，被问到你自己的星座或性格时只说宠物这边的。"
    )
