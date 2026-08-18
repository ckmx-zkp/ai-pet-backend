"""趣味测验：列表、作答、回看与分享海报文案。"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.fun_quiz import public_questions, score_fun_quiz, share_card_for
from pet_common.models import FunQuiz, FunQuizAttempt, Memory
from web_api.deps import get_current_claims
from web_api.owner_service import get_or_create_owner_profile, record_fun_quiz_result
from web_api.queue import enqueue_memory_profile
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/fun-quizzes", tags=["fun-quizzes"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]

_KIND_ZH = {"psychology": "心理", "astrology": "星座", "metaphysics": "玄学"}


class QuizListItem(BaseModel):
    id: int
    kind: str
    title: str
    subtitle: str
    source: str
    question_count: int
    quiz_date: str | None
    created_at: datetime


class QuizDetail(QuizListItem):
    questions: list[dict[str, Any]]


class SubmitIn(BaseModel):
    answers: list[str] = Field(min_length=1, max_length=20)
    device_id: int | None = None
    apply: str = "none"


class AttemptOut(BaseModel):
    id: int
    quiz_id: int
    quiz_title: str
    kind: str
    result: dict[str, Any]
    share_card: dict[str, Any]
    created_at: datetime


def _list_item(row: FunQuiz) -> QuizListItem:
    questions = public_questions(row.payload)
    return QuizListItem(
        id=row.id,
        kind=row.kind,
        title=row.title,
        subtitle=row.subtitle,
        source=row.source,
        question_count=len(questions),
        quiz_date=row.quiz_date.isoformat() if row.quiz_date else None,
        created_at=row.created_at,
    )


@router.get("", response_model=list[QuizListItem])
async def list_fun_quizzes(
    session: SessionDep,
    kind: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[QuizListItem]:
    stmt = select(FunQuiz)
    if kind:
        stmt = stmt.where(FunQuiz.kind == kind)
    rows = (
        (
            await session.execute(
                stmt.order_by(FunQuiz.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_list_item(row) for row in rows]


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
async def get_attempt(attempt_id: int, claims: ClaimsDep, session: SessionDep) -> AttemptOut:
    row = await session.get(FunQuizAttempt, attempt_id)
    if row is None or row.user_id != _current_user_id(claims):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="attempt not found")
    quiz = await session.get(FunQuiz, row.quiz_id)
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="quiz not found")
    result = row.result if isinstance(row.result, dict) else {}
    share = result.get("share_card")
    if not isinstance(share, dict):
        share = share_card_for(_KIND_ZH.get(quiz.kind, quiz.kind), quiz.title, "")
    return AttemptOut(
        id=row.id,
        quiz_id=quiz.id,
        quiz_title=quiz.title,
        kind=quiz.kind,
        result=result,
        share_card=share,
        created_at=row.created_at,
    )


@router.get("/{quiz_id}", response_model=QuizDetail)
async def get_fun_quiz(quiz_id: int, session: SessionDep) -> QuizDetail:
    row = await session.get(FunQuiz, quiz_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="quiz not found")
    item = _list_item(row)
    return QuizDetail(**item.model_dump(), questions=public_questions(row.payload))


@router.post("/{quiz_id}/submit", response_model=AttemptOut)
async def submit_fun_quiz(
    quiz_id: int, body: SubmitIn, claims: ClaimsDep, session: SessionDep
) -> AttemptOut:
    quiz = await session.get(FunQuiz, quiz_id)
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="quiz not found")
    try:
        scored = score_fun_quiz(quiz.payload, body.answers)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    share = share_card_for(
        _KIND_ZH.get(quiz.kind, quiz.kind),
        scored["title"],
        scored["share_line"],
    )
    result = {**scored, "share_card": share, "apply": body.apply}
    user_id = _current_user_id(claims)
    device_id = body.device_id
    if body.apply == "memory":
        if device_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="device_id required to save memory"
            )
        await _get_own_device(session, device_id, user_id)
        session.add(
            Memory(
                device_id=device_id,
                user_id=user_id,
                title=f"趣味测试：{scored['title']}"[:200],
                content=scored["summary"][:4000],
                tags=["fun_quiz", quiz.kind],
                source="manual",
                status="active",
            )
        )
        await enqueue_memory_profile(session, device_id, "create")
    elif body.apply not in {"none", "memory"}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="apply must be none or memory"
        )
    attempt = FunQuizAttempt(
        user_id=user_id,
        device_id=device_id,
        quiz_id=quiz.id,
        answers=body.answers,
        result=result,
    )
    session.add(attempt)
    await session.flush()
    owner = await get_or_create_owner_profile(session, user_id)
    record_fun_quiz_result(owner, quiz.kind, scored, quiz.id, attempt.id)
    await session.commit()
    await session.refresh(attempt)
    return AttemptOut(
        id=attempt.id,
        quiz_id=quiz.id,
        quiz_title=quiz.title,
        kind=quiz.kind,
        result=result,
        share_card=share,
        created_at=attempt.created_at,
    )
