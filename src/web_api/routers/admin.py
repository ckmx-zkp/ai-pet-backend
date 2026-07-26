"""/admin/* KB 管理（docs/06 §人设与知识库）。

红线：发布必须 version++；Agent/Worker 不得直接 UPDATE published 行。
"""

from fastapi import APIRouter

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/admin/kb", tags=["admin", "kb"])


@router.get("/zodiac")
async def list_zodiac_entries() -> None:
    """KB 条目列表。"""
    not_implemented()


@router.post("/zodiac/{entry_id}")
async def create_zodiac_draft(entry_id: int) -> None:
    """编辑 draft。"""
    not_implemented()


@router.put("/zodiac/{entry_id}")
async def update_zodiac_draft(entry_id: int) -> None:
    """编辑 draft。"""
    not_implemented()


@router.post("/zodiac/{entry_id}/publish")
async def publish_zodiac_entry(entry_id: int) -> None:
    """发布：status=published 且 version++（事务保证原子性）；版本冲突返回 409。"""
    not_implemented()


@router.get("/feedback")
async def list_kb_feedback() -> None:
    """KB 反馈候选（kb_feedback_candidates）。"""
    not_implemented()


@router.post("/feedback/{candidate_id}/accept")
async def accept_kb_feedback(candidate_id: int) -> None:
    """合并候选 → 新 published version。"""
    not_implemented()
