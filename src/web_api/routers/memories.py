"""记忆 CRUD 与候选通过（docs/06 §历史/记忆）。

红线：source=agent 的记忆默认 candidate；approve 后才 active。
"""

from fastapi import APIRouter, Query

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/devices/{device_id}/memories", tags=["memories"])


@router.get("")
async def list_memories(
    device_id: int,
    q: str | None = Query(default=None),  # 标题/正文模糊
    status: str | None = Query(default=None),  # candidate|active|...
    limit: int = Query(default=20, ge=1, le=100),  # 分页强制 limit，上限 100
    offset: int = Query(default=0, ge=0),
) -> None:
    """记忆列表：q 模糊 + status 筛选 + limit/offset 分页。"""
    not_implemented()


@router.post("")
async def create_memory(device_id: int) -> None:
    not_implemented()


@router.patch("/{memory_id}")
async def update_memory(device_id: int, memory_id: int) -> None:
    not_implemented()


@router.delete("/{memory_id}")
async def delete_memory(device_id: int, memory_id: int) -> None:
    not_implemented()


@router.post("/{memory_id}/approve")
async def approve_memory(device_id: int, memory_id: int) -> None:
    """候选通过：candidate → active。"""
    not_implemented()


@router.post("/{memory_id}/reject")
async def reject_memory(device_id: int, memory_id: int) -> None:
    """候选驳回：candidate → rejected。"""
    not_implemented()
