"""人格化陪伴数据接口：当前主人隔离、候选反馈与会话内约定。"""

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.companion import PREFERENCE_VALUES, CompanionFollowup
from pet_common.db import get_session
from pet_common.models import AuditLog, Device, Memory, OwnerProfile, PersonaProfile
from pet_common.redaction import redact_text
from web_api.deps import get_current_claims
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/internal/companion/devices/{device_uid}", tags=["companion"])
user_router = APIRouter(prefix="/devices/{device_id}/followups", tags=["companion"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


def now_utc() -> datetime:
    return datetime.now(UTC)


def allowed_followup_time(now: datetime) -> bool:
    return 8 <= now.astimezone(timezone(timedelta(hours=8))).hour < 21


async def device_scope(session: AsyncSession, device_uid: str) -> Device:
    # 行锁串行化同设备写入，也避免本次查询跨越解绑/重绑事务。
    device = await session.scalar(
        select(Device).where(Device.device_uid == device_uid.strip().lower()).with_for_update()
    )
    if device is None or device.user_id is None:
        raise HTTPException(404, "bound device not found")
    return device


def preference_tag(key: str, value: str) -> str:
    if key not in PREFERENCE_VALUES or value not in PREFERENCE_VALUES[key]:
        raise HTTPException(422, "unsupported preference")
    return f"preference:{key}:{value}"


def approved_preferences(memories: list[Memory]) -> dict[str, str]:
    result: dict[str, str] = {}
    for memory in memories:
        if memory.status != "active":
            continue
        for tag in memory.tags:
            bits = tag.split(":")
            if len(bits) == 3 and bits[0] == "preference":
                key, value = bits[1:]
                if key in PREFERENCE_VALUES and value in PREFERENCE_VALUES[key]:
                    result.setdefault(key, value)
    return result


def followup_out(row: CompanionFollowup) -> dict[str, Any]:
    return dict(
        id=row.id,
        topic=row.topic,
        due_at=row.due_at.isoformat(),
        expires_at=row.expires_at.isoformat(),
        status=row.status,
        delivery="next_suitable_session",
    )


async def due_followups(session: AsyncSession, device: Device) -> list[CompanionFollowup]:
    now = now_utc()
    if device.user_id is None or not allowed_followup_time(now):
        return []
    return list(
        (
            await session.scalars(
                select(CompanionFollowup)
                .where(
                    CompanionFollowup.device_id == device.id,
                    CompanionFollowup.user_id == device.user_id,
                    CompanionFollowup.status == "pending",
                    CompanionFollowup.due_at <= now,
                    CompanionFollowup.expires_at > now,
                )
                .order_by(CompanionFollowup.due_at)
                .limit(3)
            )
        ).all()
    )


async def followup_context(session: AsyncSession, device: Device) -> list[str]:
    rows = await due_followups(session, device)
    if not rows:
        return []
    return [
        "如果当下方便，可关心已到期的约定："
        + "；".join(r.topic[:100] for r in rows)
        + "。先回应用户当前需求，不必生硬插入，不宣称已完成。"
    ]


@router.get("/context")
async def get_context(
    device_uid: str,
    session: SessionDep,
    q: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    device = await device_scope(session, device_uid)
    owner = await session.scalar(select(OwnerProfile).where(OwnerProfile.user_id == device.user_id))
    pet = await session.scalar(
        select(PersonaProfile).where(
            PersonaProfile.device_id == device.id, PersonaProfile.user_id == device.user_id
        )
    )
    pref_rows = list(
        (
            await session.scalars(
                select(Memory)
                .where(
                    Memory.device_id == device.id,
                    Memory.user_id == device.user_id,
                    Memory.status == "active",
                    Memory.tags.contains(["companion_preference"]),
                )
                .where(
                    select(AuditLog.id)
                    .where(
                        AuditLog.target_id == cast(Memory.id, String),
                        AuditLog.target_type == "memory",
                        AuditLog.action == "memory_active",
                        AuditLog.actor.like("user:%"),
                    )
                    .exists()
                )
                .order_by(Memory.updated_at.desc(), Memory.id.desc())
                .limit(20)
            )
        ).all()
    )
    statement = select(Memory).where(
        Memory.device_id == device.id,
        Memory.user_id == device.user_id,
        Memory.status == "active",
        ~Memory.tags.contains(["companion_preference"]),
    )
    if q.strip():
        # 搜索词作为字面量，避免通配符扩大召回。
        pattern = (
            "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        statement = statement.where(or_(Memory.title.ilike(pattern), Memory.content.ilike(pattern)))
    memories = list(
        (await session.scalars(statement.order_by(Memory.updated_at.desc()).limit(5))).all()
    )
    return dict(
        owner=dict(sun_sign=owner.sun_sign, mbti=owner.mbti) if owner else {},
        pet=dict(
            sun_sign=pet.sun_sign,
            mbti=pet.mbti,
            dossier={
                str(k): [str(item)[:300] for item in v[:8]] if isinstance(v, list) else str(v)[:600]
                for k, v in (pet.dossier or {}).items()
                if k
                in {
                    "identity",
                    "roles",
                    "goals",
                    "background",
                    "relationship",
                    "evolution_rules",
                }
            },
        )
        if pet
        else {},
        relationship=pet.bond or {} if pet else {},
        approved_preferences=approved_preferences(pref_rows),
        memories=[dict(title=m.title, content=m.content[:600]) for m in memories],
        due_followups=[followup_out(row) for row in await due_followups(session, device)],
    )


class FeedbackIn(BaseModel):
    preference: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=24)
    evidence: str = Field(min_length=1, max_length=1000)


@router.post("/feedback")
async def feedback(device_uid: str, body: FeedbackIn, session: SessionDep) -> dict[str, Any]:
    tag = preference_tag(body.preference, body.value)
    evidence = redact_text(body.evidence.strip())
    if not evidence:
        raise HTTPException(422, "explicit feedback required")
    device = await device_scope(session, device_uid)
    event_tag = "feedback:" + hashlib.sha256((tag + evidence).encode()).hexdigest()
    old = await session.scalar(
        select(Memory)
        .where(
            Memory.device_id == device.id,
            Memory.user_id == device.user_id,
            Memory.tags.contains([event_tag]),
            Memory.status.in_(["candidate", "active"]),
        )
        .limit(1)
    )
    if old:
        return dict(memory_id=old.id, status=old.status, approval_required=old.status != "active")
    row = Memory(
        device_id=device.id,
        user_id=device.user_id,
        title="沟通偏好：" + body.preference,
        content=f"用户明确反馈：{evidence}；建议偏好 {body.preference}={body.value}。",
        tags=["companion_preference", tag, event_tag],
        source="agent",
        status="candidate",
    )
    session.add(row)
    await session.flush()
    await session.commit()
    return dict(memory_id=row.id, status="candidate", approval_required=True)


class FollowupIn(BaseModel):
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    topic: str = Field(min_length=1, max_length=500)
    due_at: datetime

    @field_validator("due_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("due_at must contain a timezone")
        return value.astimezone(UTC)


class FollowupUpdate(BaseModel):
    status: Literal["completed", "cancelled"]


@router.post("/followups")
async def create_followup(device_uid: str, body: FollowupIn, session: SessionDep) -> dict[str, Any]:
    device = await device_scope(session, device_uid)
    topic = redact_text(body.topic.strip())
    if not topic:
        raise HTTPException(422, "topic required")
    old = await session.scalar(
        select(CompanionFollowup).where(
            CompanionFollowup.device_id == device.id,
            CompanionFollowup.user_id == device.user_id,
            CompanionFollowup.request_id == body.request_id,
        )
    )
    if old:
        if old.topic != topic or old.due_at != body.due_at:
            raise HTTPException(409, "request_id reused with different content")
        return followup_out(old)
    now = now_utc()
    if not now < body.due_at <= now + timedelta(days=90):
        raise HTTPException(422, "due_at must be within next 90 days")
    count = await session.scalar(
        select(func.count())
        .select_from(CompanionFollowup)
        .where(
            CompanionFollowup.device_id == device.id,
            CompanionFollowup.user_id == device.user_id,
            CompanionFollowup.status == "pending",
            CompanionFollowup.expires_at > now,
        )
    )
    if (count or 0) >= 50:
        raise HTTPException(409, "too many pending followups")
    row = CompanionFollowup(
        id=str(uuid4()),
        device_id=device.id,
        user_id=device.user_id,
        request_id=body.request_id,
        topic=topic,
        due_at=body.due_at,
        expires_at=body.due_at + timedelta(days=7),
        status="pending",
    )
    session.add(row)
    await session.commit()
    return followup_out(row)


async def list_for_device(
    session: AsyncSession,
    device: Device,
    state: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(CompanionFollowup)
        .where(
            CompanionFollowup.device_id == device.id,
            CompanionFollowup.user_id == device.user_id,
            CompanionFollowup.status == state,
        )
        .order_by(CompanionFollowup.due_at, CompanionFollowup.id)
        .limit(limit)
        .offset(offset)
    )
    return [followup_out(row) for row in rows.all()]


@router.get("/followups")
async def list_followups(
    device_uid: str,
    session: SessionDep,
    status: Literal["pending", "completed", "cancelled"] = "pending",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return await list_for_device(
        session, await device_scope(session, device_uid), status, limit, offset
    )


async def update_for_device(
    session: AsyncSession,
    device: Device,
    item_id: str,
    body: FollowupUpdate,
) -> dict[str, Any]:
    row = await session.scalar(
        select(CompanionFollowup)
        .where(
            CompanionFollowup.id == item_id,
            CompanionFollowup.device_id == device.id,
            CompanionFollowup.user_id == device.user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "followup not found")
    if row.status not in ("pending", body.status):
        raise HTTPException(409, "followup already closed")
    row.status = body.status
    await session.commit()
    return followup_out(row)


@router.patch("/followups/{item_id}")
async def update_followup(
    device_uid: str,
    item_id: str,
    body: FollowupUpdate,
    session: SessionDep,
) -> dict[str, Any]:
    return await update_for_device(session, await device_scope(session, device_uid), item_id, body)


@user_router.get("")
async def user_list_followups(
    device_id: int,
    claims: ClaimsDep,
    session: SessionDep,
    status: Literal["pending", "completed", "cancelled"] = "pending",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    device = await _get_own_device(session, device_id, _current_user_id(claims))
    return await list_for_device(session, device, status, limit, offset)


@user_router.patch("/{item_id}")
async def user_update_followup(
    device_id: int,
    item_id: str,
    body: FollowupUpdate,
    claims: ClaimsDep,
    session: SessionDep,
) -> dict[str, Any]:
    device = await _get_own_device(session, device_id, _current_user_id(claims))
    return await update_for_device(session, device, item_id, body)
