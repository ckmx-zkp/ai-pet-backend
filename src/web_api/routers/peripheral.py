"""GET /devices/{id}/peripheral（docs/06 §外设）。"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import DevicePeripheralState
from web_api.deps import get_current_claims
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/devices/{device_id}/peripheral", tags=["peripheral"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class PeripheralResponse(BaseModel):
    device_id: int
    eye_emotion: str | None
    eye_gaze: str | None
    eye_closed: bool | None
    extra: dict[str, Any]
    updated_at: datetime


async def _get_peripheral_state(
    session: AsyncSession, device_id: int
) -> DevicePeripheralState | None:
    result = await session.execute(
        select(DevicePeripheralState).where(DevicePeripheralState.device_id == device_id)
    )
    return result.scalar_one_or_none()


@router.get("")
async def get_peripheral(
    device_id: int, claims: ClaimsDep, session: SessionDep
) -> PeripheralResponse:
    """外设快照（device_peripheral_state，一设备一行）。"""
    await _get_own_device(session, device_id, _current_user_id(claims))
    state = await _get_peripheral_state(session, device_id)
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
