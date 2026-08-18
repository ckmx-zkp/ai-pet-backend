"""主人八字读写与每日运势聚合（docs/06 §运势与八字；设计 docs/12，E10）。

安全约束：
- 设备归属校验沿用 devices 域：他人/已解绑设备一律 404，不泄露存在性；
- 八字为敏感数据：响应只回显用户录入字段，不回显 bazi_text 等派生内容；
  写操作审计仅记字段变更键名，不落生辰原文（docs/12 §7）；
- 当日内容缺失时懒入队 daily_device_content，对应字段 null + generating=true。
"""

from datetime import date, time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.dates import today_cn
from pet_common.db import get_session
from pet_common.models import (
    AgentTask,
    AuditLog,
    DailySignFortune,
    DeviceDailyContent,
    OwnerBaziProfile,
)
from pet_common.natal import compute_natal_chart
from web_api.deps import get_current_claims
from web_api.owner_service import (
    claimed_device_ids_for_user,
    get_or_create_owner_profile,
    get_owner_bazi,
    get_owner_profile,
)
from web_api.persona_service import get_profile
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/devices/{device_id}", tags=["fortune"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]

# 运势四维度钉死键（docs/12 §3）
_FORTUNE_KEYS = ("overall", "career", "wealth", "study", "love")
# PUT 覆盖写参与比对的生辰字段；变更即清空 bazi_text 重排（docs/12 §3）
_BIRTH_FIELDS = ("calendar_type", "birth_date", "birth_time", "birth_place", "gender")


class BaziIn(BaseModel):
    """主人八字录入：birth_time（时辰未知）/birth_place/gender 可空。"""

    calendar_type: Literal["solar", "lunar"]
    birth_date: date
    birth_time: time | None = None
    birth_place: str | None = Field(default=None, max_length=128)
    gender: str | None = Field(default=None, max_length=16)


class BaziOut(BaseModel):
    """只回显用户录入字段；bazi_text 等派生内容不出后端（docs/06 §运势与八字）。"""

    calendar_type: str
    birth_date: date
    birth_time: time | None
    birth_place: str | None
    gender: str | None


class FortuneDimensions(BaseModel):
    overall: str
    career: str
    wealth: str
    study: str
    love: str


class DailyFortuneOut(BaseModel):
    """当日运势聚合（docs/06）：缺内容字段为 null 且 generating=true。"""

    date: date
    sign: str | None
    sign_fortune: FortuneDimensions | None
    greeting: str | None
    bazi_fortune: FortuneDimensions | None
    generating: bool


def _today() -> date:
    """每日内容的"今日"按东八区判定（docs/12 §4）。"""
    return today_cn()


async def _bazi_profile(session: AsyncSession, user_id: int) -> OwnerBaziProfile | None:
    return await get_owner_bazi(session, user_id)


async def _sign_fortune(
    session: AsyncSession, fortune_date: date, sign: str
) -> DailySignFortune | None:
    result = await session.execute(
        select(DailySignFortune).where(
            DailySignFortune.fortune_date == fortune_date, DailySignFortune.sign == sign
        )
    )
    return result.scalar_one_or_none()


async def _daily_content(
    session: AsyncSession, device_id: int, content_date: date, kind: str
) -> DeviceDailyContent | None:
    result = await session.execute(
        select(DeviceDailyContent).where(
            DeviceDailyContent.device_id == device_id,
            DeviceDailyContent.content_date == content_date,
            DeviceDailyContent.kind == kind,
        )
    )
    return result.scalar_one_or_none()


def _dimensions(payload: dict[str, Any]) -> FortuneDimensions | None:
    """从 jsonb payload 投影四维度 + 总述；source_digest 仅运营排查，不下发。"""
    values = {key: payload.get(key) for key in _FORTUNE_KEYS}
    if not all(isinstance(value, str) and value for value in values.values()):
        return None
    return FortuneDimensions(**{key: str(value) for key, value in values.items()})


def _enqueue_device_content(session: AsyncSession, device_id: int, content_date: date) -> None:
    session.add(
        AgentTask(
            kind="daily_device_content",
            payload={"device_id": device_id, "date": content_date.isoformat()},
            status="pending",
        )
    )


async def enqueue_daily_content_if_missing(
    session: AsyncSession, device_id: int, content_date: date
) -> None:
    """懒生成触发（internal 用）：当日 greeting 缺失且设备已配置人设才入队。

    先查目标表当日行是否已存在，避免重复入队；未配置人设的设备由 worker 空转
    返回，这里直接跳过，防止 seen 心跳反复入队。
    """
    profile = await get_profile(session, device_id)
    if profile is None or profile.sun_sign is None:
        return
    if await _daily_content(session, device_id, content_date, "greeting") is not None:
        return
    _enqueue_device_content(session, device_id, content_date)


def _bazi_out(row: OwnerBaziProfile) -> BaziOut:
    return BaziOut(
        calendar_type=row.calendar_type,
        birth_date=row.birth_date,
        birth_time=row.birth_time,
        birth_place=row.birth_place,
        gender=row.gender,
    )


@router.get("/bazi", response_model=BaziOut)
async def get_bazi(device_id: int, claims: ClaimsDep, session: SessionDep) -> BaziOut:
    """读取主人八字；未录入返回 404。"""
    await _get_own_device(session, device_id, _current_user_id(claims))
    row = await _bazi_profile(session, _current_user_id(claims))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bazi not recorded")
    return _bazi_out(row)


@router.put("/bazi", response_model=BaziOut)
async def put_bazi(device_id: int, body: BaziIn, claims: ClaimsDep, session: SessionDep) -> BaziOut:
    """覆盖写主人八字；出生信息变更清空 bazi_text 重排，当日 bazi_fortune 重生成。

    审计只记字段变更键名，不落生辰原文（docs/12 §7）。
    """
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    row = await _bazi_profile(session, user_id)
    if row is None:
        row = OwnerBaziProfile(
            user_id=user_id,
            calendar_type=body.calendar_type,
            birth_date=body.birth_date,
            birth_time=body.birth_time,
            birth_place=body.birth_place,
            gender=body.gender,
            bazi_text=None,
        )
        session.add(row)
        changed = list(_BIRTH_FIELDS)
    else:
        changed = []
        for field in _BIRTH_FIELDS:
            new_value = getattr(body, field)
            if getattr(row, field) != new_value:
                setattr(row, field, new_value)
                changed.append(field)
    if changed:
        row.bazi_text = None  # 出生信息变更：排盘缓存作废重排

    if body.calendar_type == "solar":
        sun = compute_natal_chart(body.birth_date)["bodies"]["sun"]["sign"]
        owner = await get_or_create_owner_profile(session, user_id)
        owner.sun_sign = str(sun)

    today = _today()
    device_ids = await claimed_device_ids_for_user(session, user_id)
    if device_id not in device_ids:
        device_ids.append(device_id)
    for did in device_ids:
        stale = await _daily_content(session, did, today, "bazi_fortune")
        if stale is not None:
            await session.delete(stale)
        _enqueue_device_content(session, did, today)
    session.add(
        AuditLog(
            actor=f"user:{user_id}",
            action="bazi_upsert",
            target_type="user",
            target_id=str(user_id),
            detail={"changed_fields": changed},
        )
    )
    await session.commit()
    return _bazi_out(row)


@router.get("/fortune/daily", response_model=DailyFortuneOut)
async def get_daily_fortune(
    device_id: int,
    claims: ClaimsDep,
    session: SessionDep,
    date_: Annotated[date | None, Query(alias="date")] = None,
) -> DailyFortuneOut:
    """当日运势聚合：星座四维度 + greeting + 八字四维度（docs/06 契约语义）。

    设备未配置宠物人设（无星座）404；sign 取主人太阳星座，未录入则为 null。
    未录八字 bazi_fortune=null；当日内容缺失时懒入队、对应字段 null、generating=true。
    """
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    profile = await get_profile(session, device_id)
    if profile is None or profile.sun_sign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="persona not configured")
    target = date_ or _today()

    owner = await get_owner_profile(session, user_id)
    owner_sign = owner.sun_sign if owner is not None else None
    sign_row = (
        await _sign_fortune(session, target, owner_sign) if owner_sign is not None else None
    )
    greeting_row = await _daily_content(session, device_id, target, "greeting")
    bazi = await _bazi_profile(session, user_id)
    bazi_row = (
        await _daily_content(session, device_id, target, "bazi_fortune")
        if bazi is not None
        else None
    )

    greeting: str | None = None
    if greeting_row is not None:
        text = greeting_row.payload.get("text")
        if isinstance(text, str) and text.strip():
            greeting = text
    sign_fortune = _dimensions(sign_row.payload) if sign_row is not None else None
    bazi_fortune = _dimensions(bazi_row.payload) if bazi_row is not None else None

    generating = False
    if greeting_row is None or (bazi is not None and bazi_row is None):
        generating = True
        _enqueue_device_content(session, device_id, target)
    if owner_sign is not None and sign_row is None:
        # L1 缺失：直接入队 L1（handler 幂等）；worker 侧 L2 任务会自行延迟重试
        generating = True
        session.add(
            AgentTask(
                kind="daily_sign_fortune",
                payload={"date": target.isoformat()},
                status="pending",
            )
        )
    await session.commit()
    return DailyFortuneOut(
        date=target,
        sign=owner_sign,
        sign_fortune=sign_fortune,
        greeting=greeting,
        bazi_fortune=bazi_fortune,
        generating=generating,
    )
