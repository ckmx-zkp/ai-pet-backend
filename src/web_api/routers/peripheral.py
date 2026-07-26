"""GET /devices/{id}/peripheral（docs/06 §外设）。"""

from fastapi import APIRouter

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/devices/{device_id}/peripheral", tags=["peripheral"])


@router.get("")
async def get_peripheral(device_id: int) -> None:
    """外设快照（device_peripheral_state，一设备一行）。"""
    not_implemented()
