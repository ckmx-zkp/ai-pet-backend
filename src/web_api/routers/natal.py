"""简略西洋星盘（测测风格）。"""

from datetime import date, time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import NatalChart, OwnerBaziProfile
from pet_common.natal import compute_natal_chart, resolve_city
from web_api.deps import get_current_claims
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/devices/{device_id}/natal-chart", tags=["natal"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class NatalPutIn(BaseModel):
    birth_date: date | None = None
    birth_time: time | None = None
    birth_place: str | None = Field(default=None, max_length=64)
    use_bazi: bool = False


class NatalOut(BaseModel):
    device_id: int
    has_time: bool
    has_place: bool
    has_rising: bool
    headline: str
    bodies: dict[str, Any]
    ascendant: dict[str, Any] | None
    share_card: dict[str, Any]


def _to_out(device_id: int, chart: dict[str, Any]) -> NatalOut:
    bodies_raw = chart.get("bodies")
    share_raw = chart.get("share_card")
    rising_raw = chart.get("ascendant")
    return NatalOut(
        device_id=device_id,
        has_time=bool(chart.get("has_time")),
        has_place=bool(chart.get("has_place")),
        has_rising=bool(chart.get("has_rising")),
        headline=str(chart.get("headline") or ""),
        bodies=bodies_raw if isinstance(bodies_raw, dict) else {},
        ascendant=rising_raw if isinstance(rising_raw, dict) else None,
        share_card=share_raw if isinstance(share_raw, dict) else {},
    )


@router.get("", response_model=NatalOut)
async def get_natal_chart(device_id: int, claims: ClaimsDep, session: SessionDep) -> NatalOut:
    await _get_own_device(session, device_id, _current_user_id(claims))
    row = await session.get(NatalChart, device_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="natal chart not found")
    return _to_out(device_id, row.chart)


@router.put("", response_model=NatalOut)
async def put_natal_chart(
    device_id: int, body: NatalPutIn, claims: ClaimsDep, session: SessionDep
) -> NatalOut:
    await _get_own_device(session, device_id, _current_user_id(claims))
    birth_date = body.birth_date
    birth_time = body.birth_time
    place = body.birth_place
    if body.use_bazi:
        bazi = await session.get(OwnerBaziProfile, device_id)
        if bazi is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="bazi not recorded")
        if bazi.calendar_type != "solar":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="lunar bazi cannot be used for natal chart",
            )
        birth_date = bazi.birth_date
        birth_time = bazi.birth_time
        place = place or bazi.birth_place
    if birth_date is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="birth_date is required")
    coords = resolve_city(place)
    computed = compute_natal_chart(
        birth_date,
        birth_time=birth_time,
        latitude=coords[0] if coords else None,
        longitude=coords[1] if coords else None,
    )
    row = await session.get(NatalChart, device_id)
    if row is None:
        row = NatalChart(
            device_id=device_id,
            birth_date=birth_date,
            has_time=birth_time is not None,
            has_place=coords is not None,
            chart=computed,
        )
        session.add(row)
    else:
        row.birth_date = birth_date
        row.has_time = birth_time is not None
        row.has_place = coords is not None
        row.chart = computed
    await session.commit()
    return _to_out(device_id, computed)
