"""管理员 KB 草稿、发布与反馈审核；已发布行只读，发布必须是新版本。"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import AuditLog, KBFeedbackCandidate, MBTIKBEntry, ZodiacKBEntry

router = APIRouter(prefix="/admin/kb", tags=["admin", "kb"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class KBPayload(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class ZodiacDraftIn(KBPayload):
    level: Literal["element", "sign", "modality"]
    key: str = Field(min_length=1, max_length=64)
    parent_key: str | None = Field(default=None, max_length=64)


class MBTIDraftIn(KBPayload):
    key: str = Field(min_length=2, max_length=8)


class KBEntryOut(BaseModel):
    id: int
    level: str | None = None
    key: str
    parent_key: str | None = None
    version: int
    status: str
    payload: dict[str, Any]
    updated_at: datetime


class FeedbackOut(BaseModel):
    id: int
    device_id: int | None
    kind: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


def _zodiac_out(row: ZodiacKBEntry) -> KBEntryOut:
    return KBEntryOut(
        id=row.id,
        level=row.level,
        key=row.key,
        parent_key=row.parent_key,
        version=row.version,
        status=row.status,
        payload=row.payload,
        updated_at=row.updated_at,
    )


def _mbti_out(row: MBTIKBEntry) -> KBEntryOut:
    return KBEntryOut(
        id=row.id,
        key=row.key,
        version=row.version,
        status=row.status,
        payload=row.payload,
        updated_at=row.updated_at,
    )


async def _zodiac(session: AsyncSession, entry_id: int) -> ZodiacKBEntry:
    row = await session.get(ZodiacKBEntry, entry_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="KB entry not found")
    return row


async def _mbti(session: AsyncSession, entry_id: int) -> MBTIKBEntry:
    row = await session.get(MBTIKBEntry, entry_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="KB entry not found")
    return row


async def _next_zodiac_version(session: AsyncSession, level: str, key: str) -> int:
    value = await session.scalar(
        select(func.max(ZodiacKBEntry.version)).where(
            ZodiacKBEntry.level == level, ZodiacKBEntry.key == key
        )
    )
    return (value or 0) + 1


async def _next_mbti_version(session: AsyncSession, key: str) -> int:
    value = await session.scalar(
        select(func.max(MBTIKBEntry.version)).where(MBTIKBEntry.key == key)
    )
    return (value or 0) + 1


def _audit(session: AsyncSession, action: str, entry_id: int, detail: dict[str, Any]) -> None:
    session.add(
        AuditLog(
            actor="admin",
            action=action,
            target_type="kb_entry",
            target_id=str(entry_id),
            detail=detail,
        )
    )


@router.get("/zodiac", response_model=list[KBEntryOut])
async def list_zodiac_entries(
    session: SessionDep,
    level: str | None = None,
    key: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[KBEntryOut]:
    stmt = select(ZodiacKBEntry)
    if level:
        stmt = stmt.where(ZodiacKBEntry.level == level)
    if key:
        stmt = stmt.where(ZodiacKBEntry.key == key)
    if status_:
        stmt = stmt.where(ZodiacKBEntry.status == status_)
    rows = (
        (
            await session.execute(
                stmt.order_by(ZodiacKBEntry.key, ZodiacKBEntry.version.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_zodiac_out(row) for row in rows]


@router.post("/zodiac", response_model=KBEntryOut, status_code=status.HTTP_201_CREATED)
async def create_zodiac_draft(body: ZodiacDraftIn, session: SessionDep) -> KBEntryOut:
    row = ZodiacKBEntry(
        level=body.level,
        key=body.key.lower(),
        parent_key=body.parent_key,
        version=await _next_zodiac_version(session, body.level, body.key.lower()),
        status="draft",
        payload=body.payload,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        "kb_draft_create",
        row.id,
        {"kind": "zodiac", "key": row.key, "version": row.version},
    )
    await session.commit()
    return _zodiac_out(row)


@router.put("/zodiac/{entry_id}", response_model=KBEntryOut)
async def update_zodiac_draft(
    entry_id: int, body: ZodiacDraftIn, session: SessionDep
) -> KBEntryOut:
    row = await _zodiac(session, entry_id)
    if row.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="published KB entries are immutable")
    row.level, row.key, row.parent_key, row.payload = (
        body.level,
        body.key.lower(),
        body.parent_key,
        body.payload,
    )
    _audit(session, "kb_draft_update", row.id, {"kind": "zodiac", "version": row.version})
    await session.commit()
    return _zodiac_out(row)


@router.post("/zodiac/{entry_id}/publish", response_model=KBEntryOut)
async def publish_zodiac_entry(entry_id: int, session: SessionDep) -> KBEntryOut:
    row = await _zodiac(session, entry_id)
    if row.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="only draft KB entries can be published"
        )
    row.status = "published"
    _audit(
        session, "kb_publish", row.id, {"kind": "zodiac", "key": row.key, "version": row.version}
    )
    await session.commit()
    return _zodiac_out(row)


@router.get("/mbti", response_model=list[KBEntryOut])
async def list_mbti_entries(
    session: SessionDep,
    key: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[KBEntryOut]:
    stmt = select(MBTIKBEntry)
    if key:
        stmt = stmt.where(MBTIKBEntry.key == key.upper())
    if status_:
        stmt = stmt.where(MBTIKBEntry.status == status_)
    rows = (
        (
            await session.execute(
                stmt.order_by(MBTIKBEntry.key, MBTIKBEntry.version.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_mbti_out(row) for row in rows]


@router.post("/mbti", response_model=KBEntryOut, status_code=status.HTTP_201_CREATED)
async def create_mbti_draft(body: MBTIDraftIn, session: SessionDep) -> KBEntryOut:
    key = body.key.upper()
    row = MBTIKBEntry(
        key=key,
        version=await _next_mbti_version(session, key),
        status="draft",
        payload=body.payload,
    )
    session.add(row)
    await session.flush()
    _audit(session, "kb_draft_create", row.id, {"kind": "mbti", "key": key, "version": row.version})
    await session.commit()
    return _mbti_out(row)


@router.put("/mbti/{entry_id}", response_model=KBEntryOut)
async def update_mbti_draft(entry_id: int, body: MBTIDraftIn, session: SessionDep) -> KBEntryOut:
    row = await _mbti(session, entry_id)
    if row.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="published KB entries are immutable")
    row.key, row.payload = body.key.upper(), body.payload
    _audit(session, "kb_draft_update", row.id, {"kind": "mbti", "version": row.version})
    await session.commit()
    return _mbti_out(row)


@router.post("/mbti/{entry_id}/publish", response_model=KBEntryOut)
async def publish_mbti_entry(entry_id: int, session: SessionDep) -> KBEntryOut:
    row = await _mbti(session, entry_id)
    if row.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="only draft KB entries can be published"
        )
    row.status = "published"
    _audit(session, "kb_publish", row.id, {"kind": "mbti", "key": row.key, "version": row.version})
    await session.commit()
    return _mbti_out(row)


@router.get("/feedback", response_model=list[FeedbackOut])
async def list_kb_feedback(
    session: SessionDep,
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[FeedbackOut]:
    stmt = select(KBFeedbackCandidate)
    if status_:
        stmt = stmt.where(KBFeedbackCandidate.status == status_)
    rows = (
        (
            await session.execute(
                stmt.order_by(KBFeedbackCandidate.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [FeedbackOut.model_validate(row, from_attributes=True) for row in rows]


async def _review_feedback(session: AsyncSession, candidate_id: int, outcome: str) -> FeedbackOut:
    row = await session.get(KBFeedbackCandidate, candidate_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="feedback candidate not found")
    if row.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="feedback candidate already reviewed")
    row.status = outcome
    _audit(session, f"kb_feedback_{outcome}", row.id, {"candidate_kind": row.kind})
    await session.commit()
    return FeedbackOut.model_validate(row, from_attributes=True)


@router.post("/feedback/{candidate_id}/accept", response_model=FeedbackOut)
async def accept_kb_feedback(candidate_id: int, session: SessionDep) -> FeedbackOut:
    return await _review_feedback(session, candidate_id, "accepted")


@router.post("/feedback/{candidate_id}/ignore", response_model=FeedbackOut)
async def ignore_kb_feedback(candidate_id: int, session: SessionDep) -> FeedbackOut:
    return await _review_feedback(session, candidate_id, "rejected")
