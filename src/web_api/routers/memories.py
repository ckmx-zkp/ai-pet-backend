"""用户侧记忆 CRUD 与审核：agent 记忆可由 LLM 自动审核，也保留人工接口。"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import AuditLog, Memory
from web_api.deps import get_current_claims
from web_api.queue import enqueue_memory_profile
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/devices/{device_id}/memories", tags=["memories"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class MemoryIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class MemoryOut(BaseModel):
    id: int
    device_id: int
    title: str | None
    content: str
    status: str
    source: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


async def _memory(session: AsyncSession, device_id: int, memory_id: int) -> Memory:
    row = await session.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.device_id == device_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="memory not found")
    return row


def _out(row: Memory) -> MemoryOut:
    return MemoryOut.model_validate(row, from_attributes=True)


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    device_id: int,
    claims: ClaimsDep,
    session: SessionDep,
    q: str | None = Query(default=None, max_length=200),
    status_: str | None = Query(default=None, alias="status", max_length=16),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[MemoryOut]:
    await _get_own_device(session, device_id, _current_user_id(claims))
    statement = select(Memory).where(Memory.device_id == device_id)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(or_(Memory.title.ilike(pattern), Memory.content.ilike(pattern)))
    if status_:
        statement = statement.where(Memory.status == status_)
    rows = (
        (
            await session.execute(
                statement.order_by(Memory.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_out(row) for row in rows]


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    device_id: int, body: MemoryIn, claims: ClaimsDep, session: SessionDep
) -> MemoryOut:
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    row = Memory(
        device_id=device_id,
        user_id=user_id,
        title=body.title,
        content=body.content,
        tags=body.tags,
        source="manual",
        status="active",
    )
    session.add(row)
    await enqueue_memory_profile(session, device_id, "create")
    await session.commit()
    return _out(row)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory(
    device_id: int, memory_id: int, body: MemoryIn, claims: ClaimsDep, session: SessionDep
) -> MemoryOut:
    await _get_own_device(session, device_id, _current_user_id(claims))
    row = await _memory(session, device_id, memory_id)
    row.title, row.content, row.tags = body.title, body.content, body.tags
    if row.status == "active":
        await enqueue_memory_profile(session, device_id, "update")
    await session.commit()
    return _out(row)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    device_id: int, memory_id: int, claims: ClaimsDep, session: SessionDep
) -> None:
    await _get_own_device(session, device_id, _current_user_id(claims))
    row = await _memory(session, device_id, memory_id)
    row.status = "archived"
    session.add(
        AuditLog(
            actor=f"user:{_current_user_id(claims)}",
            action="memory_archive",
            target_type="memory",
            target_id=str(row.id),
            detail={},
        )
    )
    await enqueue_memory_profile(session, device_id, "archive")
    await session.commit()


async def review_memory(
    session: AsyncSession, device_id: int, memory_id: int, outcome: str, actor: str
) -> MemoryOut:
    row = await _memory(session, device_id, memory_id)
    if row.status != "candidate":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="memory is not a candidate")
    row.status = outcome
    session.add(
        AuditLog(
            actor=actor,
            action=f"memory_{outcome}",
            target_type="memory",
            target_id=str(row.id),
            detail={},
        )
    )
    if outcome == "active":
        await enqueue_memory_profile(session, device_id, "approve")
    await session.commit()
    return _out(row)


@router.post("/{memory_id}/approve", response_model=MemoryOut)
async def approve_memory(
    device_id: int, memory_id: int, claims: ClaimsDep, session: SessionDep
) -> MemoryOut:
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    return await review_memory(session, device_id, memory_id, "active", f"user:{user_id}")


@router.post("/{memory_id}/reject", response_model=MemoryOut)
async def reject_memory(
    device_id: int, memory_id: int, claims: ClaimsDep, session: SessionDep
) -> MemoryOut:
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    return await review_memory(session, device_id, memory_id, "rejected", f"user:{user_id}")
