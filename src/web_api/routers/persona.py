"""GET/PUT /devices/{id}/persona（docs/06 §人设与知识库）。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import PersonaProfile
from web_api.deps import get_current_claims
from web_api.persona_service import get_mbti_entry, get_profile, get_zodiac_entry
from web_api.routers._common import not_implemented
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/devices/{device_id}/persona", tags=["persona"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class PersonaResponse(BaseModel):
    device_id: int
    sun_sign: str | None
    mbti: str | None
    overrides: dict[str, Any]
    follow_latest: bool
    kb_version: int | None


class PersonaPutRequest(BaseModel):
    sun_sign: str
    mbti: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    follow_latest: bool = True

    @field_validator("sun_sign", mode="before")
    @classmethod
    def normalize_sign(cls, value: Any) -> str:
        return str(value).strip().lower()

    @field_validator("mbti", mode="before")
    @classmethod
    def normalize_mbti(cls, value: Any) -> str:
        return str(value).strip().upper()


def _to_response(profile: PersonaProfile) -> PersonaResponse:
    return PersonaResponse(
        device_id=profile.device_id,
        sun_sign=profile.sun_sign,
        mbti=profile.mbti,
        overrides=profile.overrides,
        follow_latest=profile.follow_latest,
        kb_version=profile.kb_version,
    )


@router.get("")
async def get_persona(device_id: int, claims: ClaimsDep, session: SessionDep) -> PersonaResponse:
    """读人设：星座、MBTI、忌口、钉扎（follow_latest / kb_version）。"""
    await _get_own_device(session, device_id, _current_user_id(claims))
    profile = await get_profile(session, device_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="persona not configured")
    return _to_response(profile)


@router.put("")
async def put_persona(
    device_id: int, payload: PersonaPutRequest, claims: ClaimsDep, session: SessionDep
) -> PersonaResponse:
    """写人设。kb_version 钉扎规则见 docs/03 §发布与钉扎。"""
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    sign = await get_zodiac_entry(session, "sign", payload.sun_sign, None)
    mbti = await get_mbti_entry(session, payload.mbti, None)
    if sign is None or mbti is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported persona selection"
        )
    element = await get_zodiac_entry(session, "element", sign.parent_key or "", None)
    if element is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="published zodiac KB unavailable")
    profile = await get_profile(session, device_id)
    kb_version = None if payload.follow_latest else max(element.version, sign.version, mbti.version)
    if profile is None:
        profile = PersonaProfile(
            user_id=user_id,
            device_id=device_id,
            sun_sign=payload.sun_sign,
            mbti=payload.mbti,
            overrides=payload.overrides,
            follow_latest=payload.follow_latest,
            kb_version=kb_version,
        )
        session.add(profile)
    else:
        profile.sun_sign = payload.sun_sign
        profile.mbti = payload.mbti
        profile.overrides = payload.overrides
        profile.follow_latest = payload.follow_latest
        profile.kb_version = kb_version
    await session.commit()
    return _to_response(profile)


@router.post("/questionnaire")
async def submit_questionnaire(device_id: int) -> None:
    """问卷提交（可选）。"""
    not_implemented()
