"""设备域：app 认领/列表/详情/改名/解绑（docs/06 §用户与设备）。

安全约束（AGENTS.md 红线 + docs/06）：
- 详情/改名/解绑对「他人设备」与「已解绑设备」一律 404，不泄露设备存在性；
- app 仅以不可猜测的 binding_id 认领设备；admin 不得占用用户归属；
- 绑定/解绑写 audit_logs；
- 解绑 = user_id 置 NULL（迁移 0002 起）：保留 devices 行与全部历史，
  device_uid 可重绑（bind 时 UPDATE 回原行）；
- 在线状态以 xiaozhi 侧实时连接为准，backend 镜像 devices.online_at
  （E3 chat events / 心跳写入）；E1 先按 online_at 阈值粗判，未接入前恒 false。
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import AuditLog, Device
from web_api.deps import get_current_claims

router = APIRouter(prefix="/devices", tags=["devices"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]

# online_at 距今超过该阈值视为离线（粗判；精确在线以 xiaozhi 侧为准）
_ONLINE_THRESHOLD = timedelta(minutes=5)


class BindRequest(BaseModel):
    binding_id: Annotated[
        str, StringConstraints(min_length=16, max_length=64, strip_whitespace=True)
    ]
    name: Annotated[str | None, StringConstraints(max_length=128, strip_whitespace=True)] = None


class RenameRequest(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=128, strip_whitespace=True)]


class DeviceResponse(BaseModel):
    id: int
    device_uid: str
    name: str | None
    online: bool
    last_seen_at: datetime | None
    firmware_version: str | None
    capabilities: dict[str, Any]


async def _find_device_by_uid(session: AsyncSession, device_uid: str) -> Device | None:
    result = await session.execute(select(Device).where(Device.device_uid == device_uid))
    return result.scalar_one_or_none()


async def _find_device_by_binding_id(session: AsyncSession, binding_id: str) -> Device | None:
    result = await session.execute(select(Device).where(Device.binding_id == binding_id))
    return result.scalar_one_or_none()


async def _list_devices_by_user(
    session: AsyncSession, user_id: int, limit: int, offset: int
) -> list[Device]:
    result = await session.execute(
        select(Device)
        .where(Device.user_id == user_id)
        .order_by(Device.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def _get_device_by_id(session: AsyncSession, device_id: int) -> Device | None:
    result = await session.execute(select(Device).where(Device.id == device_id))
    return result.scalar_one_or_none()


def _current_user_id(claims: dict[str, Any]) -> int:
    try:
        return int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from exc


async def _get_own_device(session: AsyncSession, device_id: int, user_id: int) -> Device:
    """取设备并校验归属；不存在或非本人一律 404（不泄露存在性）。"""
    device = await _get_device_by_id(session, device_id)
    if device is None or device.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")
    return device


def _audit(session: AsyncSession, user_id: int, action: str, device: Device) -> None:
    session.add(
        AuditLog(
            actor=f"user:{user_id}",
            action=action,
            target_type="device",
            target_id=str(device.id),
            detail={"device_uid": device.device_uid},
        )
    )


def _to_response(device: Device) -> DeviceResponse:
    # TODO(E3)：online_at 由 chat events / 心跳镜像写入；精确在线以 xiaozhi 侧为准
    online = device.online_at is not None and (
        datetime.now(UTC) - device.online_at <= _ONLINE_THRESHOLD
    )
    return DeviceResponse(
        id=device.id,
        device_uid=device.device_uid,
        name=device.name,
        online=online,
        last_seen_at=device.online_at,
        firmware_version=device.firmware_version,
        capabilities=device.capabilities,
    )


@router.post("/bind", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def bind_device(
    payload: BindRequest, claims: ClaimsDep, session: SessionDep
) -> DeviceResponse:
    """以 binding_id 认领设备；已绑定中（本人或他人）409；写审计。

    已解绑（user_id 为 NULL）的同 binding_id 设备执行重绑：UPDATE 回原行，
    保留设备 id 与全部历史；payload 带 name 时一并更新。
    """
    if claims.get("role") != "user":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user binding only")
    user_id = _current_user_id(claims)
    device = await _find_device_by_binding_id(session, payload.binding_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="binding_id not found")
    if device.user_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="device already bound")
    device.user_id = user_id
    if payload.name is not None:
        device.name = payload.name
    _audit(session, user_id, "device_bind", device)
    await session.commit()
    return _to_response(device)


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    claims: ClaimsDep,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),  # 分页强制 limit，上限 100
    offset: int = Query(default=0, ge=0),
) -> list[DeviceResponse]:
    """当前用户设备列表：名称/在线/固件版本/capabilities。"""
    user_id = _current_user_id(claims)
    devices = await _list_devices_by_user(session, user_id, limit, offset)
    return [_to_response(device) for device in devices]


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: int, claims: ClaimsDep, session: SessionDep) -> DeviceResponse:
    """设备详情/能力/在线状态；他人设备 404。"""
    user_id = _current_user_id(claims)
    device = await _get_own_device(session, device_id, user_id)
    return _to_response(device)


@router.patch("/{device_id}", response_model=DeviceResponse)
async def rename_device(
    device_id: int, payload: RenameRequest, claims: ClaimsDep, session: SessionDep
) -> DeviceResponse:
    """改名；他人设备 404。"""
    user_id = _current_user_id(claims)
    device = await _get_own_device(session, device_id, user_id)
    device.name = payload.name
    await session.commit()
    return _to_response(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unbind_device(device_id: int, claims: ClaimsDep, session: SessionDep) -> None:
    """解绑：user_id 置 NULL，保留 devices 行与全部历史，可重绑；写审计。

    他人设备与已解绑设备一律 404（不泄露存在性）。
    """
    user_id = _current_user_id(claims)
    device = await _get_own_device(session, device_id, user_id)
    device.user_id = None
    _audit(session, user_id, "device_unbind", device)
    await session.commit()
