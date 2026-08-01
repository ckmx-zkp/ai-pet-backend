"""GET/DELETE /devices/{id}/messages（docs/06 §历史）。

红线：只存 content_redacted；查询按 device + 时间窗 + 强制 limit；删除须写 audit_logs。
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import AuditLog, ChatMessage
from web_api.deps import get_current_claims
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/devices/{device_id}/messages", tags=["messages"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class MessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    content_redacted: str
    created_at: datetime


async def _list_messages(
    session: AsyncSession,
    device_id: int,
    from_: datetime | None,
    to: datetime | None,
    limit: int,
    offset: int,
) -> list[ChatMessage]:
    statement = select(ChatMessage).where(ChatMessage.device_id == device_id)
    if from_ is not None:
        statement = statement.where(ChatMessage.created_at >= from_)
    if to is not None:
        statement = statement.where(ChatMessage.created_at <= to)
    result = await session.execute(
        statement.order_by(ChatMessage.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def _delete_messages(
    session: AsyncSession, device_id: int, from_: datetime | None, to: datetime | None
) -> int:
    statement = delete(ChatMessage).where(ChatMessage.device_id == device_id)
    if from_ is not None:
        statement = statement.where(ChatMessage.created_at >= from_)
    if to is not None:
        statement = statement.where(ChatMessage.created_at <= to)
    result = await session.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)


@router.get("")
async def list_messages(
    device_id: int,
    claims: ClaimsDep,
    session: SessionDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,  # 分页强制 limit，上限 100
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageResponse]:
    """脱敏历史：按设备 + 时间窗 + limit。"""
    await _get_own_device(session, device_id, _current_user_id(claims))
    messages = await _list_messages(session, device_id, from_, to, limit, offset)
    return [
        MessageResponse(
            id=message.id,
            session_id=message.session_id,
            role=message.role,
            content_redacted=message.content_redacted,
            created_at=message.created_at,
        )
        for message in messages
    ]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_messages(
    device_id: int,
    claims: ClaimsDep,
    session: SessionDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> None:
    """按条件删除（按日/按会话），物理删或软删，须写 audit_logs。"""
    if from_ is None and to is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="from or to is required for deletion"
        )
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    deleted_count = await _delete_messages(session, device_id, from_, to)
    session.add(
        AuditLog(
            actor=f"user:{user_id}",
            action="messages_delete",
            target_type="device",
            target_id=str(device_id),
            detail={
                "from": from_.isoformat() if from_ is not None else None,
                "to": to.isoformat() if to is not None else None,
                "deleted_count": deleted_count,
            },
        )
    )
    await session.commit()
