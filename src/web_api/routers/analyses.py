"""GET /devices/{id}/analyses?kind=、POST /devices/{id}/export（docs/06 §历史/记忆/分析）。"""

from fastapi import APIRouter, Query

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/devices/{device_id}", tags=["analyses"])


@router.get("/analyses")
async def list_analyses(device_id: int, kind: str | None = Query(default=None)) -> None:
    """分析结果：日摘要/情绪标签/记忆候选/人设契合/运势小记（kind 见 docs/04）。"""
    not_implemented()


@router.post("/export")
async def export_device_data(device_id: int) -> None:
    """导出我的数据（建议 V0.2）。"""
    not_implemented()
