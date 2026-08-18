"""GET/PUT /devices/{id}/persona（docs/06 §人设与知识库）。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.bond import public_bond
from pet_common.db import get_session
from pet_common.models import PersonaProfile
from web_api.deps import get_current_claims
from web_api.persona_service import (
    compile_profile,
    get_mbti_entry,
    get_profile,
    get_zodiac_entry,
)
from web_api.routers.devices import _current_user_id, _get_own_device
from web_api.routers.owner import (
    QuestionnaireIn,
    QuestionnaireOut,
    apply_questionnaire,
    get_owner_questionnaire,
    to_owner_out,
)

router = APIRouter(prefix="/devices/{device_id}/persona", tags=["persona"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class PersonaDossier(BaseModel):
    identity: str = Field(default="", max_length=1200)
    background: list[str] = Field(default_factory=list, max_length=8)
    roles: list[str] = Field(default_factory=list, max_length=8)
    goals: list[str] = Field(default_factory=list, max_length=8)
    evolution_rules: list[str] = Field(default_factory=list, max_length=8)
    relationship: str = Field(default="", max_length=600)


class BondView(BaseModel):
    kind: str
    label: str
    summary: str
    source: str
    confidence: float
    updated_at: str | None = None


class PersonaResponse(BaseModel):
    subject: str = "pet"
    device_id: int
    sun_sign: str | None
    mbti: str | None
    overrides: dict[str, Any]
    follow_latest: bool
    kb_version: int | None
    dossier: PersonaDossier
    bond: BondView | None = None


class PersonaPutRequest(BaseModel):
    sun_sign: str
    mbti: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    follow_latest: bool = True
    dossier: PersonaDossier = Field(default_factory=PersonaDossier)

    @field_validator("sun_sign", mode="before")
    @classmethod
    def normalize_sign(cls, value: Any) -> str:
        return str(value).strip().lower()

    @field_validator("mbti", mode="before")
    @classmethod
    def normalize_mbti(cls, value: Any) -> str:
        return str(value).strip().upper()


def _to_response(profile: PersonaProfile) -> PersonaResponse:
    viewed = public_bond(profile.bond)
    return PersonaResponse(
        subject="pet",
        device_id=profile.device_id,
        sun_sign=profile.sun_sign,
        mbti=profile.mbti,
        overrides=profile.overrides,
        follow_latest=profile.follow_latest,
        kb_version=profile.kb_version,
        dossier=PersonaDossier.model_validate(profile.dossier),
        bond=BondView.model_validate(viewed) if viewed is not None else None,
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
            dossier=payload.dossier.model_dump(),
        )
        session.add(profile)
    else:
        profile.sun_sign = payload.sun_sign
        profile.mbti = payload.mbti
        profile.overrides = payload.overrides
        profile.follow_latest = payload.follow_latest
        profile.kb_version = kb_version
        profile.dossier = payload.dossier.model_dump()
    await session.commit()
    return _to_response(profile)


@router.get("/questionnaire", response_model=QuestionnaireOut)
async def get_questionnaire(
    device_id: int, claims: ClaimsDep, session: SessionDep
) -> QuestionnaireOut:
    """主人问卷题面（设备路径别名）；不算型、不改宠物人设。"""
    await _get_own_device(session, device_id, _current_user_id(claims))
    return await get_owner_questionnaire()


@router.post("/questionnaire")
async def submit_questionnaire(
    device_id: int, body: QuestionnaireIn, claims: ClaimsDep, session: SessionDep
) -> dict[str, Any]:
    """提交主人问卷：计分写入 owner_profiles，不改宠物 persona。"""
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    owner = await apply_questionnaire(session, user_id, body)
    await session.commit()
    return to_owner_out(owner).model_dump(mode="json")


@router.post("/preview")
async def preview_persona(
    device_id: int, payload: PersonaPutRequest, claims: ClaimsDep, session: SessionDep
) -> dict[str, Any]:
    """编译预览：不改库，返回固定 7 字段 persona_pack。"""
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    sign = await get_zodiac_entry(session, "sign", payload.sun_sign, None)
    mbti = await get_mbti_entry(session, payload.mbti, None)
    if sign is None or mbti is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported persona selection"
        )
    transient = PersonaProfile(
        user_id=user_id,
        device_id=device_id,
        sun_sign=payload.sun_sign,
        mbti=payload.mbti,
        overrides=payload.overrides,
        follow_latest=payload.follow_latest,
        kb_version=None,
        dossier=payload.dossier.model_dump(),
    )
    return await compile_profile(session, transient)
