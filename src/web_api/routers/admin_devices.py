"""管理端设备资产及跨用户只读/人设授权接口。"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import (
    AnalysisResult,
    AuditLog,
    Device,
    DevicePeripheralState,
    Memory,
    PersonaProfile,
)
from web_api.persona_service import get_mbti_entry, get_profile, get_zodiac_entry
from web_api.routers.messages import MessageResponse, _list_messages
from web_api.routers.persona import PersonaPutRequest, PersonaResponse, _to_response

router = APIRouter(prefix="/admin/devices", tags=["admin", "devices"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
_ONLINE_THRESHOLD = timedelta(minutes=5)


class AdminDeviceResponse(BaseModel):
    id: int
    device_uid: str
    binding_id: str
    name: str | None
    claimed: bool
    online: bool
    last_seen_at: datetime | None
    firmware_version: str | None
    capabilities: dict[str, Any]


class PeripheralResponse(BaseModel):
    device_id: int
    eye_emotion: str | None
    eye_gaze: str | None
    eye_closed: bool | None
    extra: dict[str, Any]
    updated_at: datetime


class AnalysisResponse(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime


class AdminMemoryResponse(BaseModel):
    id: int
    device_id: int
    title: str | None
    content: str
    status: str
    source: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


def _to_device_response(device: Device) -> AdminDeviceResponse:
    online = device.online_at is not None and (
        datetime.now(UTC) - device.online_at <= _ONLINE_THRESHOLD
    )
    return AdminDeviceResponse(
        id=device.id,
        device_uid=device.device_uid,
        binding_id=device.binding_id,
        name=device.name,
        claimed=device.user_id is not None,
        online=online,
        last_seen_at=device.online_at,
        firmware_version=device.firmware_version,
        capabilities=device.capabilities,
    )


async def _get_device(session: AsyncSession, device_id: int) -> Device:
    result = await session.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="device not found")
    return device


@router.get("", response_model=list[AdminDeviceResponse])
async def list_admin_devices(
    session: SessionDep,
    q: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AdminDeviceResponse]:
    statement = select(Device)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Device.device_uid.ilike(pattern),
                Device.name.ilike(pattern),
                Device.binding_id.ilike(pattern),
                cast(Device.id, String).ilike(pattern),
            )
        )
    result = await session.execute(statement.order_by(Device.id).limit(limit).offset(offset))
    return [_to_device_response(device) for device in result.scalars().all()]


@router.get("/lookup", response_model=AdminDeviceResponse)
async def lookup_admin_device(
    session: SessionDep,
    device_uid: str = Query(min_length=4, max_length=64),
) -> AdminDeviceResponse:
    """以设备硬件核心 ID 精确读取资产与 app binding_id。"""
    result = await session.execute(select(Device).where(Device.device_uid == device_uid))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="device not found")
    return _to_device_response(device)


@router.get("/{device_id}", response_model=AdminDeviceResponse)
async def get_admin_device(device_id: int, session: SessionDep) -> AdminDeviceResponse:
    return _to_device_response(await _get_device(session, device_id))


@router.post("/{device_id}/binding-id/rotate", response_model=AdminDeviceResponse)
async def rotate_binding_id(device_id: int, session: SessionDep) -> AdminDeviceResponse:
    """轮换 app 认领码，不修改当前 user_id；旧码立即不可再认领。"""
    device = await _get_device(session, device_id)
    device.binding_id = uuid4().hex
    session.add(
        AuditLog(
            actor="admin",
            action="device_binding_id_rotate",
            target_type="device",
            target_id=str(device_id),
            detail={"device_uid": device.device_uid},
        )
    )
    await session.commit()
    return _to_device_response(device)


@router.get("/{device_id}/persona", response_model=PersonaResponse)
async def get_admin_persona(device_id: int, session: SessionDep) -> PersonaResponse:
    await _get_device(session, device_id)
    profile = await get_profile(session, device_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="persona not configured")
    return _to_response(profile)


@router.put("/{device_id}/persona", response_model=PersonaResponse)
async def put_admin_persona(
    device_id: int, payload: PersonaPutRequest, session: SessionDep
) -> PersonaResponse:
    device = await _get_device(session, device_id)
    if device.user_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="device is not claimed")
    sign = await get_zodiac_entry(session, "sign", payload.sun_sign, None)
    mbti = await get_mbti_entry(session, payload.mbti, None)
    if sign is None or mbti is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported persona selection"
        )
    element = await get_zodiac_entry(session, "element", sign.parent_key or "", None)
    if element is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="published zodiac KB unavailable")
    profile = await get_profile(session, device_id)
    kb_version = None if payload.follow_latest else max(element.version, sign.version, mbti.version)
    if profile is None:
        profile = PersonaProfile(
            user_id=device.user_id,
            device_id=device_id,
            sun_sign=payload.sun_sign,
            mbti=payload.mbti,
            overrides=payload.overrides,
            follow_latest=payload.follow_latest,
            kb_version=kb_version,
            dossier=payload.dossier.model_dump(),
        )
        session.add(profile)
    else:
        profile.sun_sign = payload.sun_sign
        profile.mbti = payload.mbti
        profile.overrides = payload.overrides
        profile.follow_latest = payload.follow_latest
        profile.kb_version = kb_version
        profile.dossier = payload.dossier.model_dump()
    session.add(
        AuditLog(
            actor="admin",
            action="admin_persona_update",
            target_type="device",
            target_id=str(device_id),
            detail={"sun_sign": payload.sun_sign, "mbti": payload.mbti},
        )
    )
    await session.commit()
    return _to_response(profile)


@router.get("/{device_id}/messages", response_model=list[MessageResponse])
async def list_admin_messages(
    device_id: int,
    session: SessionDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageResponse]:
    await _get_device(session, device_id)
    messages = await _list_messages(session, device_id, from_, to, limit, offset)
    return [
        MessageResponse(
            id=item.id,
            session_id=item.session_id,
            role=item.role,
            content_redacted=item.content_redacted,
            created_at=item.created_at,
        )
        for item in messages
    ]


@router.get("/{device_id}/memories", response_model=list[AdminMemoryResponse])
async def list_admin_memories(
    device_id: int,
    session: SessionDep,
    q: str | None = Query(default=None, max_length=200),
    status_: str | None = Query(default=None, alias="status", max_length=16),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AdminMemoryResponse]:
    await _get_device(session, device_id)
    statement = select(Memory).where(Memory.device_id == device_id)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(or_(Memory.title.ilike(pattern), Memory.content.ilike(pattern)))
    if status_:
        statement = statement.where(Memory.status == status_)
    rows = (
        (
            await session.execute(
                statement.order_by(Memory.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [AdminMemoryResponse.model_validate(row, from_attributes=True) for row in rows]


async def _admin_review_memory(
    device_id: int, memory_id: int, outcome: str, session: AsyncSession
) -> AdminMemoryResponse:
    await _get_device(session, device_id)
    row = await session.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.device_id == device_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="memory not found")
    if row.status != "candidate":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="memory is not a candidate")
    row.status = outcome
    session.add(
        AuditLog(
            actor="admin",
            action=f"memory_{outcome}",
            target_type="memory",
            target_id=str(row.id),
            detail={},
        )
    )
    await session.commit()
    return AdminMemoryResponse.model_validate(row, from_attributes=True)


@router.post("/{device_id}/memories/{memory_id}/approve", response_model=AdminMemoryResponse)
async def approve_admin_memory(
    device_id: int, memory_id: int, session: SessionDep
) -> AdminMemoryResponse:
    return await _admin_review_memory(device_id, memory_id, "active", session)


@router.post("/{device_id}/memories/{memory_id}/reject", response_model=AdminMemoryResponse)
async def reject_admin_memory(
    device_id: int, memory_id: int, session: SessionDep
) -> AdminMemoryResponse:
    return await _admin_review_memory(device_id, memory_id, "rejected", session)


@router.get("/{device_id}/peripheral", response_model=PeripheralResponse)
async def get_admin_peripheral(device_id: int, session: SessionDep) -> PeripheralResponse:
    await _get_device(session, device_id)
    result = await session.execute(
        select(DevicePeripheralState).where(DevicePeripheralState.device_id == device_id)
    )
    state = result.scalar_one_or_none()
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="peripheral state not found")
    return PeripheralResponse(
        device_id=state.device_id,
        eye_emotion=state.eye_emotion,
        eye_gaze=state.eye_gaze,
        eye_closed=state.eye_closed,
        extra=state.extra,
        updated_at=state.updated_at,
    )


@router.get("/{device_id}/analyses", response_model=list[AnalysisResponse])
async def list_admin_analyses(
    device_id: int,
    session: SessionDep,
    kind: str | None = Query(default=None, max_length=48),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AnalysisResponse]:
    await _get_device(session, device_id)
    statement = select(AnalysisResult).where(AnalysisResult.device_id == device_id)
    if kind:
        statement = statement.where(AnalysisResult.kind == kind)
    result = await session.execute(
        statement.order_by(AnalysisResult.created_at.desc()).limit(limit).offset(offset)
    )
    return [
        AnalysisResponse(
            id=item.id, kind=item.kind, payload=item.payload, created_at=item.created_at
        )
        for item in result.scalars().all()
    ]
