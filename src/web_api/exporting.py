"""E8 用户数据导出：只组装已允许对用户可见的字段，不含生辰原文与 device_uid。"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.models import (
    AnalysisResult,
    ChatMessage,
    Device,
    DeviceDailyContent,
    Memory,
    OwnerBaziProfile,
    OwnerProfile,
    PersonaProfile,
)

_MESSAGE_LIMIT = 200
_LIST_LIMIT = 100


async def build_export_bundle(session: AsyncSession, device: Device) -> dict[str, Any]:
    profile = await session.scalar(
        select(PersonaProfile).where(PersonaProfile.device_id == device.id)
    )
    owner = None
    bazi = None
    if device.user_id is not None:
        owner = await session.scalar(
            select(OwnerProfile).where(OwnerProfile.user_id == device.user_id)
        )
        bazi = await session.scalar(
            select(OwnerBaziProfile).where(OwnerBaziProfile.user_id == device.user_id)
        )
    memories = (
        (
            await session.execute(
                select(Memory)
                .where(Memory.device_id == device.id, Memory.status != "rejected")
                .order_by(Memory.updated_at.desc())
                .limit(_LIST_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    messages = (
        (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.device_id == device.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(_MESSAGE_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    analyses = (
        (
            await session.execute(
                select(AnalysisResult)
                .where(AnalysisResult.device_id == device.id)
                .order_by(AnalysisResult.created_at.desc())
                .limit(_LIST_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    greetings = (
        (
            await session.execute(
                select(DeviceDailyContent)
                .where(DeviceDailyContent.device_id == device.id)
                .order_by(DeviceDailyContent.content_date.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    persona: dict[str, Any] | None = None
    if profile is not None:
        persona = {
            "sun_sign": profile.sun_sign,
            "mbti": profile.mbti,
            "follow_latest": profile.follow_latest,
            "kb_version": profile.kb_version,
            "overrides": profile.overrides,
            "bond": profile.bond,
        }
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "device": {"id": device.id, "name": device.name, "device_uid_redacted": True},
        "persona": persona,
        "owner": (
            {
                "sun_sign": owner.sun_sign,
                "mbti": owner.mbti,
                "quiz_results": owner.quiz_results,
            }
            if owner is not None
            else None
        ),
        "bazi_recorded": bazi is not None,
        "memories": [
            {
                "id": row.id,
                "title": row.title,
                "content": row.content,
                "status": row.status,
                "tags": row.tags,
            }
            for row in memories
        ],
        "messages": [
            {
                "id": row.id,
                "role": row.role,
                "content_redacted": row.content_redacted,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in messages
        ],
        "analyses": [
            {
                "id": row.id,
                "kind": row.kind,
                "payload": row.payload,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in analyses
            if row.kind != "data_export"
        ],
        "daily_contents": [
            {
                "date": row.content_date.isoformat(),
                "kind": row.kind,
                "payload": row.payload,
            }
            for row in greetings
        ],
    }
