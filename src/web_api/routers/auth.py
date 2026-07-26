"""POST /auth/login、POST /auth/register（docs/06 §用户与设备）。"""

from fastapi import APIRouter

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login() -> None:
    """登录，签发用户 JWT。"""
    not_implemented()


@router.post("/register")
async def register() -> None:
    """注册（若开放）。"""
    not_implemented()
