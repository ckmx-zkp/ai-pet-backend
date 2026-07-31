"""GET/DELETE /devices/{id}/messages（docs/06 §历史）。

红线：只存 content_redacted；查询按 device + 时间窗 + 强制 limit；删除须写 audit_logs。
"""

from fastapi import APIRouter, Query

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/devices/{device_id}/messages", tags=["messages"])


@router.get("")
async def list_messages(
    device_id: int,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),  # 分页强制 limit，上限 100
    offset: int = Query(default=0, ge=0),
) -> None:
    """脱敏历史：按设备 + 时间窗 + limit。"""
    not_implemented()


@router.delete("")
async def delete_messages(device_id: int) -> None:
    """按条件删除（按日/按会话），物理删或软删，须写 audit_logs。"""
    not_implemented()
