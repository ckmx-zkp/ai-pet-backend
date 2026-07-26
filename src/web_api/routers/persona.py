"""GET/PUT /devices/{id}/persona 与问卷提交（docs/06 §人设与知识库）。"""

from fastapi import APIRouter

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/devices/{device_id}/persona", tags=["persona"])


@router.get("")
async def get_persona(device_id: int) -> None:
    """读人设：星座、MBTI、忌口、钉扎（follow_latest / kb_version）。"""
    not_implemented()


@router.put("")
async def put_persona(device_id: int) -> None:
    """写人设。kb_version 钉扎规则见 docs/03 §发布与钉扎。"""
    not_implemented()


@router.post("/questionnaire")
async def submit_questionnaire(device_id: int) -> None:
    """问卷提交（可选）。"""
    not_implemented()
