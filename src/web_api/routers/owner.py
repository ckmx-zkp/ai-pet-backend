"""主人档案：一账号一份，多设备共享（docs/06）。"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from persona_compiler import question_public_view, score_mbti
from pet_common.db import get_session
from pet_common.models import OwnerProfile
from web_api.deps import get_current_claims
from web_api.owner_service import get_or_create_owner_profile, get_owner_profile
from web_api.persona_service import get_mbti_entry, get_zodiac_entry
from web_api.routers.devices import _current_user_id

router = APIRouter(prefix="/owner", tags=["owner"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class OwnerOut(BaseModel):
    user_id: int
    sun_sign: str | None
    mbti: str | None
    quiz_results: dict[str, Any]
    updated_at: datetime | None = None


class OwnerPutRequest(BaseModel):
    sun_sign: str | None = None
    mbti: str | None = None

    @field_validator("sun_sign", mode="before")
    @classmethod
    def normalize_optional_sign(cls, value: Any) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        return str(value).strip().lower()

    @field_validator("mbti", mode="before")
    @classmethod
    def normalize_optional_mbti(cls, value: Any) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        return str(value).strip().upper()


class QuestionnaireOut(BaseModel):
    answers_required: int
    questions: list[dict[str, str]]
    subject: str = "owner"


class QuestionnaireIn(BaseModel):
    answers: list[str] = Field(min_length=1, max_length=40)
    sun_sign: str | None = None

    @field_validator("sun_sign", mode="before")
    @classmethod
    def normalize_optional_sign(cls, value: Any) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        return str(value).strip().lower()


def to_owner_out(row: OwnerProfile) -> OwnerOut:
    return OwnerOut(
        user_id=row.user_id,
        sun_sign=row.sun_sign,
        mbti=row.mbti,
        quiz_results=row.quiz_results if isinstance(row.quiz_results, dict) else {},
        updated_at=row.updated_at,
    )


async def validate_owner_sign(session: AsyncSession, sun_sign: str) -> None:
    sign = await get_zodiac_entry(session, "sign", sun_sign, None)
    if sign is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported owner sun_sign"
        )


async def validate_owner_mbti(session: AsyncSession, mbti: str) -> None:
    entry = await get_mbti_entry(session, mbti, None)
    if entry is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported owner mbti")


async def apply_questionnaire(
    session: AsyncSession, user_id: int, body: QuestionnaireIn
) -> OwnerProfile:
    try:
        mbti_key = score_mbti(body.answers)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if body.sun_sign is not None:
        await validate_owner_sign(session, body.sun_sign)
    owner = await get_or_create_owner_profile(session, user_id)
    owner.mbti = mbti_key
    if body.sun_sign is not None:
        owner.sun_sign = body.sun_sign
    return owner


@router.get("", response_model=OwnerOut)
async def get_owner(claims: ClaimsDep, session: SessionDep) -> OwnerOut:
    owner = await get_owner_profile(session, _current_user_id(claims))
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="owner profile not configured")
    return to_owner_out(owner)


@router.put("", response_model=OwnerOut)
async def put_owner(body: OwnerPutRequest, claims: ClaimsDep, session: SessionDep) -> OwnerOut:
    if body.sun_sign is not None:
        await validate_owner_sign(session, body.sun_sign)
    if body.mbti is not None:
        await validate_owner_mbti(session, body.mbti)
    owner = await get_or_create_owner_profile(session, _current_user_id(claims))
    if body.sun_sign is not None:
        owner.sun_sign = body.sun_sign
    if body.mbti is not None:
        owner.mbti = body.mbti
    await session.commit()
    await session.refresh(owner)
    return to_owner_out(owner)


@router.get("/questionnaire", response_model=QuestionnaireOut)
async def get_owner_questionnaire() -> QuestionnaireOut:
    questions = question_public_view()
    return QuestionnaireOut(answers_required=len(questions), questions=questions)


@router.post("/questionnaire", response_model=OwnerOut)
async def submit_owner_questionnaire(
    body: QuestionnaireIn, claims: ClaimsDep, session: SessionDep
) -> OwnerOut:
    owner = await apply_questionnaire(session, _current_user_id(claims), body)
    await session.commit()
    await session.refresh(owner)
    return to_owner_out(owner)
