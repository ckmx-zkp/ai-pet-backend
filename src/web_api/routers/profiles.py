"""主人/宠物档案合读，以及该设备上的相处关系。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.bond import RELATIONSHIP_KINDS, catalog, merge_bond, normalize_kind, public_bond
from pet_common.db import get_session
from web_api.deps import get_current_claims
from web_api.owner_service import get_owner_profile
from web_api.persona_service import get_profile
from web_api.routers.devices import _current_user_id, _get_own_device
from web_api.routers.owner import OwnerOut, to_owner_out
from web_api.routers.persona import PersonaResponse, _to_response

router = APIRouter(prefix="/devices/{device_id}", tags=["profiles"])
kinds_router = APIRouter(prefix="/relationship-kinds", tags=["profiles"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class BondOut(BaseModel):
    kind: str
    label: str
    summary: str
    source: str
    confidence: float
    updated_at: str | None = None


class BondPut(BaseModel):
    kind: str
    summary: str = Field(default="", max_length=200)


class ProfilesOut(BaseModel):
    owner: OwnerOut | None
    pet: PersonaResponse | None
    relationship: BondOut | None


@kinds_router.get("")
async def list_relationship_kinds() -> list[dict[str, str]]:
    """全部相处关系种类，供 App 直选。无需设备。"""
    return catalog()


def bond_out(raw: object) -> BondOut | None:
    viewed = public_bond(raw)
    if viewed is None:
        return None
    return BondOut.model_validate(viewed)


@router.get("/profiles", response_model=ProfilesOut)
async def get_profiles(device_id: int, claims: ClaimsDep, session: SessionDep) -> ProfilesOut:
    """一次读出主人档案、宠物人设、相处关系；主体已分开。"""
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    owner = await get_owner_profile(session, user_id)
    pet = await get_profile(session, device_id)
    return ProfilesOut(
        owner=to_owner_out(owner) if owner is not None else None,
        pet=_to_response(pet) if pet is not None else None,
        relationship=bond_out(pet.bond) if pet is not None else None,
    )


@router.get("/relationship", response_model=BondOut)
async def get_relationship(device_id: int, claims: ClaimsDep, session: SessionDep) -> BondOut:
    await _get_own_device(session, device_id, _current_user_id(claims))
    profile = await get_profile(session, device_id)
    viewed = bond_out(profile.bond) if profile is not None else None
    if viewed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="relationship not set")
    return viewed


@router.put("/relationship", response_model=BondOut)
async def put_relationship(
    device_id: int, body: BondPut, claims: ClaimsDep, session: SessionDep
) -> BondOut:
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    kind = normalize_kind(body.kind)
    if kind is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported relationship kind; use {', '.join(RELATIONSHIP_KINDS)}",
        )
    profile = await get_profile(session, device_id)
    if profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="persona not configured")
    merged = merge_bond(
        None,
        {"kind": kind, "summary": body.summary, "confidence": 1.0, "decision": "approve"},
        source="manual",
    )
    if merged is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid relationship")
    profile.bond = merged
    await session.commit()
    viewed = bond_out(profile.bond)
    if viewed is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="bond write failed")
    return viewed
