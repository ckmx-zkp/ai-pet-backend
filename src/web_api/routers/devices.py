"""GET /devices、POST /devices/bind、GET /devices/{id}（docs/06 §用户与设备）。"""

from fastapi import APIRouter

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("")
async def list_devices() -> None:
    """当前用户设备列表。"""
    not_implemented()


@router.post("/bind")
async def bind_device() -> None:
    """绑定 device_uid。"""
    not_implemented()


@router.get("/{device_id}")
async def get_device(device_id: int) -> None:
    """设备详情/能力/在线状态。"""
    not_implemented()
