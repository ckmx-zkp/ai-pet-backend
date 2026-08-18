"""异步任务处理器：只消费脱敏历史，产出摘要、记忆和人设建议。"""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_worker.llm import (
    SIGN_KEYS,
    generate_bazi_text,
    generate_device_daily_content,
    generate_sign_fortunes,
    generate_structured_analysis,
)
from pet_common.config import get_settings
from pet_common.models import (
    AgentTask,
    AnalysisResult,
    AuditLog,
    ChatMessage,
    DailySignFortune,
    Device,
    DeviceDailyContent,
    Memory,
    OwnerBaziProfile,
    PersonaProfile,
)

TaskHandler = Callable[[dict[str, Any], AsyncSession], Awaitable[None]]

# 运势四维度钉死键（docs/12 §3）
_FORTUNE_KEYS = ("overall", "career", "wealth", "study", "love")


class TaskDeferredError(RuntimeError):
    """依赖尚未就绪（如当日 L1 星座运势未生成）：worker 延迟重试且不消耗重试次数。"""


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


def _task_date(payload: dict[str, Any]) -> date:
    """任务 payload 的 date 为 ISO 字符串；缺省为今天（UTC）。"""
    raw = payload.get("date")
    if raw is None:
        return datetime.now(UTC).date()
    if not isinstance(raw, str):
        raise ValueError("task payload 'date' must be an ISO date string")
    return date.fromisoformat(raw)


def _fortune_payload(row: dict[str, Any]) -> dict[str, str] | None:
    """校验并裁剪四维度 + 总述；缺任一键视为无效。"""
    values = {key: row.get(key) for key in _FORTUNE_KEYS}
    if not all(isinstance(value, str) and value.strip() for value in values.values()):
        return None
    return {key: str(value).strip()[:500] for key, value in values.items()}


async def _sign_fortune(
    session: AsyncSession, fortune_date: date, sign: str
) -> DailySignFortune | None:
    result = await session.execute(
        select(DailySignFortune).where(
            DailySignFortune.fortune_date == fortune_date, DailySignFortune.sign == sign
        )
    )
    return result.scalar_one_or_none()


async def _existing_fortune_signs(session: AsyncSession, fortune_date: date) -> set[str]:
    result = await session.execute(
        select(DailySignFortune.sign).where(DailySignFortune.fortune_date == fortune_date)
    )
    return set(result.scalars().all())


async def _device_content(
    session: AsyncSession, device_id: int, content_date: date, kind: str
) -> DeviceDailyContent | None:
    result = await session.execute(
        select(DeviceDailyContent).where(
            DeviceDailyContent.device_id == device_id,
            DeviceDailyContent.content_date == content_date,
            DeviceDailyContent.kind == kind,
        )
    )
    return result.scalar_one_or_none()


async def _bazi_profile(session: AsyncSession, device_id: int) -> OwnerBaziProfile | None:
    result = await session.execute(
        select(OwnerBaziProfile).where(OwnerBaziProfile.device_id == device_id)
    )
    return result.scalar_one_or_none()


async def _recent_summary(session: AsyncSession, device_id: int) -> AnalysisResult | None:
    """近 36h 最新一条 daily_summary（与 C5 上下文同一窗口）。"""
    since = datetime.now(UTC) - timedelta(hours=36)
    result = await session.execute(
        select(AnalysisResult)
        .where(
            AnalysisResult.device_id == device_id,
            AnalysisResult.kind == "daily_summary",
            AnalysisResult.created_at >= since,
        )
        .order_by(AnalysisResult.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _top_active_memories(session: AsyncSession, device_id: int) -> list[Memory]:
    result = await session.execute(
        select(Memory)
        .where(Memory.device_id == device_id, Memory.status == "active")
        .order_by(Memory.updated_at.desc())
        .limit(3)
    )
    return list(result.scalars().all())


async def daily_sign_fortune_handler(payload: dict[str, Any], session: AsyncSession) -> None:
    """L1：一次生成当日 12 星座四维度运势；已存在的星座跳过（幂等）。"""
    fortune_date = _task_date(payload)
    existing = await _existing_fortune_signs(session, fortune_date)
    missing = [sign for sign in SIGN_KEYS if sign not in existing]
    if not missing:
        return
    settings = get_settings()
    result = await generate_sign_fortunes(settings, fortune_date)
    digest = str(result.get("source_digest", "")).strip()[:500]
    # 搜索源未接入（docs/12 §8 待决）：关闭时强制标注"非实时检索"，不全信 prompt。
    if not settings.fortune_search_enabled and "非实时检索" not in digest:
        digest = f"{digest}（非实时检索）" if digest else "非实时检索"
    signs = result.get("signs")
    if not isinstance(signs, dict):
        raise ValueError("LLM sign fortunes response missing 'signs' object")
    for sign in missing:
        row = signs.get(sign)
        if not isinstance(row, dict):
            continue
        fortune = _fortune_payload(row)
        if fortune is None:
            continue
        fortune["source_digest"] = digest
        session.add(
            DailySignFortune(
                fortune_date=fortune_date,
                sign=sign,
                payload=fortune,
                llm_model=settings.llm_model or None,
            )
        )


async def daily_device_content_handler(payload: dict[str, Any], session: AsyncSession) -> None:
    """L2：生成设备当日 greeting（恒产）与 bazi_fortune（有八字时，四维度）。

    L1 当日星座运势缺失时先入队 daily_sign_fortune，自身延迟重试（不消耗重试次数）。
    """
    device_id = payload.get("device_id")
    if not isinstance(device_id, int):
        raise ValueError("daily_device_content payload requires integer device_id")
    content_date = _task_date(payload)
    profile = await _profile(session, device_id)
    if profile is None or profile.sun_sign is None:
        return  # 未配置人设：无可生成内容，直接完成，避免懒触发反复入队空转
    sign_fortune = await _sign_fortune(session, content_date, profile.sun_sign)
    if sign_fortune is None:
        session.add(
            AgentTask(
                kind="daily_sign_fortune",
                payload={"date": content_date.isoformat()},
                status="pending",
            )
        )
        raise TaskDeferredError(
            f"L1 sign fortune missing: date={content_date.isoformat()} sign={profile.sun_sign}"
        )

    greeting_row = await _device_content(session, device_id, content_date, "greeting")
    bazi = await _bazi_profile(session, device_id)
    bazi_row = (
        await _device_content(session, device_id, content_date, "bazi_fortune")
        if bazi is not None
        else None
    )
    if greeting_row is not None and (bazi is None or bazi_row is not None):
        return  # 幂等：当日内容已齐全

    settings = get_settings()
    if bazi is not None and not bazi.bazi_text:
        # bazi_text 为空先排盘缓存；敏感数据只进 LLM 请求，不落日志。
        bazi.bazi_text = await generate_bazi_text(
            settings,
            {
                "calendar_type": bazi.calendar_type,
                "birth_date": bazi.birth_date.isoformat(),
                "birth_time": bazi.birth_time.strftime("%H:%M") if bazi.birth_time else None,
                "birth_place": bazi.birth_place,
                "gender": bazi.gender,
            },
        )

    summary = await _recent_summary(session, device_id)
    memories = await _top_active_memories(session, device_id)
    context: dict[str, Any] = {
        "date": content_date.isoformat(),
        "persona": {
            "sun_sign": profile.sun_sign,
            "mbti": profile.mbti,
            "dossier": profile.dossier,
        },
        "recent_summary": (summary.payload.get("summary") if summary is not None else None),
        "memories": [memory.content[:200] for memory in memories],
        "sign_fortune": {key: sign_fortune.payload.get(key) for key in _FORTUNE_KEYS},
        "owner_bazi": bazi.bazi_text if bazi is not None else None,
    }
    result = await generate_device_daily_content(settings, context)

    if greeting_row is None:
        greeting = result.get("greeting")
        if isinstance(greeting, str) and greeting.strip():
            session.add(
                DeviceDailyContent(
                    device_id=device_id,
                    content_date=content_date,
                    kind="greeting",
                    payload={"text": greeting.strip()[:500]},
                )
            )
    if bazi is not None and bazi_row is None:
        bazi_fortune = result.get("bazi_fortune")
        if isinstance(bazi_fortune, dict):
            fortune = _fortune_payload(bazi_fortune)
            if fortune is not None:
                session.add(
                    DeviceDailyContent(
                        device_id=device_id,
                        content_date=content_date,
                        kind="bazi_fortune",
                        payload=fortune,
                    )
                )


TASK_REGISTRY: dict[str, TaskHandler] = {
    "daily_summary": daily_summary_handler,
    "daily_sign_fortune": daily_sign_fortune_handler,
    "daily_device_content": daily_device_content_handler,
}
