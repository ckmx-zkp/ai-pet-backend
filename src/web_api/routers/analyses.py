"""用户侧分析结果读取与数据导出入口。"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import AnalysisResult, AuditLog, PersonaProfile
from web_api.deps import get_current_claims
from web_api.exporting import build_export_bundle
from web_api.routers.devices import _current_user_id, _get_own_device

router = APIRouter(prefix="/devices/{device_id}", tags=["analyses"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClaimsDep = Annotated[dict[str, Any], Depends(get_current_claims)]


class AnalysisResponse(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime


async def _list_analyses(
    session: AsyncSession, device_id: int, kind: str | None, limit: int, offset: int
) -> list[AnalysisResult]:
    statement = select(AnalysisResult).where(AnalysisResult.device_id == device_id)
    if kind:
        statement = statement.where(AnalysisResult.kind == kind)
    result = await session.execute(
        statement.order_by(AnalysisResult.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


@router.get("/analyses")
async def list_analyses(
    device_id: int,
    claims: ClaimsDep,
    session: SessionDep,
    kind: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),  # 分页强制 limit，上限 100
    offset: int = Query(default=0, ge=0),
) -> list[AnalysisResponse]:
    """分析结果：日摘要/记忆画像/人设成长/导出快照等（kind 见 docs/04）。"""
    await _get_own_device(session, device_id, _current_user_id(claims))
    results = await _list_analyses(session, device_id, kind, limit, offset)
    return [
        AnalysisResponse(
            id=item.id, kind=item.kind, payload=item.payload, created_at=item.created_at
        )
        for item in results
    ]


@router.post("/export")
async def export_device_data(
    device_id: int, claims: ClaimsDep, session: SessionDep
) -> dict[str, Any]:
    """导出我的数据（E8）：同步 JSON 包，并落 data_export 快照。"""
    device = await _get_own_device(session, device_id, _current_user_id(claims))
    bundle = await build_export_bundle(session, device)
    session.add(AnalysisResult(device_id=device_id, kind="data_export", payload=bundle))
    await session.commit()
    return bundle


@router.post("/analyses/{analysis_id}/apply-persona-growth", response_model=AnalysisResponse)
async def apply_persona_growth(
    device_id: int, analysis_id: int, claims: ClaimsDep, session: SessionDep
) -> AnalysisResponse:
    """将已保存的人设建议应用为该设备私有 overrides，保留审计与可见结果。"""
    user_id = _current_user_id(claims)
    await _get_own_device(session, device_id, user_id)
    analysis = await session.get(AnalysisResult, analysis_id)
    if analysis is None or analysis.device_id != device_id or analysis.kind != "persona_growth":
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="persona growth analysis not found")
    suggested = analysis.payload.get("suggested_overrides")
    if not isinstance(suggested, dict) or not suggested:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_409_CONFLICT, detail="analysis has no applicable overrides")
    profile = await session.scalar(
        select(PersonaProfile).where(PersonaProfile.device_id == device_id)
    )
    if profile is None:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_409_CONFLICT, detail="persona not configured")
    profile.overrides = {**profile.overrides, **suggested}
    analysis.payload = {**analysis.payload, "applied": True}
    session.add(
        AuditLog(
            actor=f"user:{user_id}",
            action="persona_growth_apply",
            target_type="analysis",
            target_id=str(analysis_id),
            detail={"keys": sorted(suggested)[:20]},
        )
    )
    await session.commit()
    return AnalysisResponse(
        id=analysis.id, kind=analysis.kind, payload=analysis.payload, created_at=analysis.created_at
    )
