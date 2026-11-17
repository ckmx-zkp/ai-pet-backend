"""操作员显式同意后的单机联调入口，默认关闭。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from pet_common.config import get_settings
from web_api.social_test import RoomError, RoomStore

store = RoomStore()


def enabled() -> None:
    if not get_settings().social_test_enabled:
        raise HTTPException(404, "not_found")


router = APIRouter(prefix="/internal/social/test-rooms", dependencies=[Depends(enabled)])


class CreateRoom(BaseModel):
    device_uid: str = Field(pattern=r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
    consented: Literal[True]
    peer_device_uid: str | None = Field(default=None, pattern=r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


class Receipt(BaseModel):
    turn_id: str = Field(pattern=r"^[1-8]$")
    speaker: Literal["real", "virtual", "peer"]
    result: Literal["played", "simulated", "failed"]
    actor_device_uid: str | None = Field(default=None, pattern=r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


@router.post("")
async def create(body: CreateRoom) -> dict[str, object]:
    try:
        return store.view(store.create(body.device_uid, body.peer_device_uid))
    except RoomError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.get("/{room_id}")
async def get(room_id: str) -> dict[str, object]:
    try:
        return store.view(store.get(room_id))
    except RoomError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/{room_id}/ack")
async def ack(room_id: str, body: Receipt) -> dict[str, object]:
    try:
        return store.view(store.ack(
            room_id, body.turn_id, body.speaker, body.result, body.actor_device_uid
        ))
    except RoomError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/{room_id}/cancel")
async def cancel(room_id: str) -> dict[str, object]:
    try:
        room = store.get(room_id)
        if room.status == "active":
            room.status = "cancelled"
        return store.view(room)
    except RoomError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
