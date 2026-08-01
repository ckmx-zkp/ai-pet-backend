"""异步任务处理器：只消费脱敏历史，产出摘要、记忆和人设建议。"""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_worker.llm import generate_structured_analysis
from pet_common.config import get_settings
from pet_common.models import AnalysisResult, AuditLog, ChatMessage, Device, Memory, PersonaProfile

TaskHandler = Callable[[dict[str, Any], AsyncSession], Awaitable[None]]


def _text_list(value: object, maximum: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()][:maximum]


def _confidence(value: object) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return 0.0


async def _session_messages(session: AsyncSession, session_id: int) -> list[dict[str, str]]:
    rows = (
        (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at)
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [{"role": row.role, "content": row.content_redacted} for row in rows]


async def _profile(session: AsyncSession, device_id: int) -> PersonaProfile | None:
    result = await session.execute(
        select(PersonaProfile).where(PersonaProfile.device_id == device_id)
    )
    return result.scalar_one_or_none()


async def daily_summary_handler(payload: dict[str, Any], session: AsyncSession) -> None:
    """一会话一次 LLM 分析；结果全部可审计且不进入实时语音路径。"""
    device_id = payload.get("device_id")
    session_id = payload.get("session_id")
    if not isinstance(device_id, int) or not isinstance(session_id, int):
        raise ValueError("daily_summary payload requires integer device_id and session_id")
    messages = await _session_messages(session, session_id)
    if not messages:
        session.add(
            AnalysisResult(device_id=device_id, kind="daily_summary", payload={"empty": True})
        )
        return

    result = await generate_structured_analysis(get_settings(), messages)
    daily = result.get("daily_summary")
    if not isinstance(daily, dict):
        daily = {}
    summary_payload = {
        "session_id": session_id,
        "summary": str(daily.get("summary", ""))[:2000],
        "topics": _text_list(daily.get("topics")),
        "user_mood": str(daily.get("user_mood", "unknown"))[:64],
        "follow_up": _text_list(daily.get("follow_up")),
    }
    session.add(AnalysisResult(device_id=device_id, kind="daily_summary", payload=summary_payload))

    candidates = result.get("memory_candidates")
    if isinstance(candidates, list):
        device = await session.get(Device, device_id)
        if device is not None and device.user_id is not None:
            for candidate in candidates[:10]:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content")
                decision = candidate.get("decision")
                if not isinstance(content, str) or not content.strip() or decision == "reject":
                    continue
                confidence = _confidence(candidate.get("confidence"))
                sensitive = candidate.get("sensitive") is True
                status = (
                    "active"
                    if decision == "approve" and confidence >= 0.8 and not sensitive
                    else "candidate"
                )
                memory = Memory(
                    device_id=device_id,
                    user_id=device.user_id,
                    title=str(candidate.get("title", "自动提取记忆"))[:200],
                    content=content.strip()[:4000],
                    tags=_text_list(candidate.get("tags")),
                    status=status,
                    source="agent",
                )
                session.add(memory)
                session.add(
                    AuditLog(
                        actor="service:agent-worker",
                        action="memory_llm_review",
                        target_type="memory",
                        target_id=None,
                        detail={
                            "decision": status,
                            "confidence": confidence,
                            "sensitive": sensitive,
                        },
                    )
                )

    growth = result.get("persona_growth")
    if isinstance(growth, dict):
        suggested = growth.get("suggested_overrides")
        if not isinstance(suggested, dict):
            suggested = {}
        confidence = _confidence(growth.get("confidence"))
        decision = str(growth.get("decision", "candidate"))
        growth_payload = {
            "session_id": session_id,
            "summary": str(growth.get("summary", ""))[:2000],
            "suggested_overrides": suggested,
            "confidence": confidence,
            "decision": decision,
            "evidence": _text_list(growth.get("evidence")),
            "applied": False,
        }
        analysis = AnalysisResult(
            device_id=device_id, kind="persona_growth", payload=growth_payload
        )
        session.add(analysis)
        settings = get_settings()
        profile = await _profile(session, device_id)
        if (
            settings.llm_auto_apply_persona_growth
            and profile is not None
            and decision == "approve"
            and confidence >= 0.8
            and suggested
        ):
            profile.overrides = {**profile.overrides, **suggested}
            growth_payload["applied"] = True
            session.add(
                AuditLog(
                    actor="service:agent-worker",
                    action="persona_growth_auto_apply",
                    target_type="device",
                    target_id=str(device_id),
                    detail={"confidence": confidence, "keys": sorted(suggested)[:20]},
                )
            )


TASK_REGISTRY: dict[str, TaskHandler] = {"daily_summary": daily_summary_handler}
