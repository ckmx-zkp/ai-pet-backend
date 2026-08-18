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
    generate_fun_quiz,
    generate_memory_profile,
    generate_sign_fortunes,
    generate_structured_analysis,
)
from pet_common.config import get_settings
from pet_common.dates import today_cn
from pet_common.fun_quiz import QUIZ_KINDS, public_questions
from pet_common.models import (
    AgentTask,
    AnalysisResult,
    AuditLog,
    ChatMessage,
    DailySignFortune,
    Device,
    DeviceDailyContent,
    FunQuiz,
    KBFeedbackCandidate,
    Memory,
    OwnerBaziProfile,
    OwnerProfile,
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

    created_active = False
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
                if status == "active":
                    created_active = True

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

    feedback = result.get("kb_feedback")
    if isinstance(feedback, dict):
        suggestion = feedback.get("suggestion")
        kb_kind = str(feedback.get("kb_kind") or "").strip()
        key = str(feedback.get("key") or "").strip()
        if isinstance(suggestion, str) and suggestion.strip() and kb_kind and key:
            session.add(
                KBFeedbackCandidate(
                    device_id=device_id,
                    kind=kb_kind[:48],
                    payload={
                        "kb_kind": kb_kind[:16],
                        "key": key[:64],
                        "parent_key": str(feedback.get("parent_key") or "")[:64],
                        "suggestion": suggestion.strip()[:1000],
                        "draft_payload": feedback.get("draft_payload")
                        if isinstance(feedback.get("draft_payload"), dict)
                        else {"prompt_fragments": [suggestion.strip()[:400]]},
                        "reason": str(feedback.get("reason") or "")[:500],
                    },
                    status="pending",
                )
            )
    if created_active:
        session.add(
            AgentTask(
                kind="memory_profile",
                payload={"device_id": device_id, "reason": "approve"},
                status="pending",
            )
        )


def _task_date(payload: dict[str, Any]) -> date:
    """任务 payload 的 date 为 ISO 字符串；缺省为今天（东八区，docs/12 §4）。"""
    raw = payload.get("date")
    if raw is None:
        return today_cn()
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


async def _bazi_profile(session: AsyncSession, user_id: int) -> OwnerBaziProfile | None:
    return await session.get(OwnerBaziProfile, user_id)


async def _owner_profile(session: AsyncSession, user_id: int) -> OwnerProfile | None:
    return await session.get(OwnerProfile, user_id)


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
    # digest 必须区分检索来源（docs/12 §4）：联网检索成功标注"已联网检索"，
    # 搜索关闭时强制标注"非实时检索"，不全信 prompt。
    if settings.fortune_search_enabled:
        if "已联网检索" not in digest:
            digest = f"{digest}（已联网检索）" if digest else "已联网检索"
    elif "非实时检索" not in digest:
        digest = f"{digest}（非实时检索）" if digest else "非实时检索"
    # 共享玄学/命理摘要：payload 扩展键，逐行写入（docs/12 §4）
    metaphysics = str(result.get("metaphysics", "")).strip()[:500]
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
        if metaphysics:
            fortune["metaphysics"] = metaphysics
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
        return  # 未配置宠物人设：无可生成内容，直接完成，避免懒触发反复入队空转
    owner = await _owner_profile(session, profile.user_id)
    owner_sign = owner.sun_sign if owner is not None else None
    sign_fortune = (
        await _sign_fortune(session, content_date, owner_sign) if owner_sign is not None else None
    )
    if owner_sign is not None and sign_fortune is None:
        session.add(
            AgentTask(
                kind="daily_sign_fortune",
                payload={"date": content_date.isoformat()},
                status="pending",
            )
        )
        raise TaskDeferredError(
            f"L1 sign fortune missing: date={content_date.isoformat()} sign={owner_sign}"
        )

    greeting_row = await _device_content(session, device_id, content_date, "greeting")
    bazi = await _bazi_profile(session, profile.user_id)
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
        "sign_fortune": (
            {key: sign_fortune.payload.get(key) for key in _FORTUNE_KEYS}
            if sign_fortune is not None
            else None
        ),
        "owner_sign": owner_sign,
        "owner_mbti": owner.mbti if owner is not None else None,
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


async def _claimed_device_ids(session: AsyncSession) -> list[int]:
    """已认领且已配置人设（有星座）的设备 id；强制 limit，不全表扫（红线 5/8）。"""
    result = await session.execute(
        select(Device.id)
        .join(PersonaProfile, PersonaProfile.device_id == Device.id)
        .where(Device.user_id.is_not(None), PersonaProfile.sun_sign.is_not(None))
        .order_by(Device.id)
        .limit(500)
    )
    return list(result.scalars().all())


async def _devices_with_content(
    session: AsyncSession, device_ids: list[int], content_date: date, kind: str
) -> set[int]:
    if not device_ids:
        return set()
    result = await session.execute(
        select(DeviceDailyContent.device_id).where(
            DeviceDailyContent.device_id.in_(device_ids),
            DeviceDailyContent.content_date == content_date,
            DeviceDailyContent.kind == kind,
        )
    )
    return set(result.scalars().all())


async def prefill_daily_content(session: AsyncSession, content_date: date) -> dict[str, int]:
    """每日定时预生成（docs/12 §4）：为已认领设备补齐当日 L1/L2 内容。

    沿用懒触发去重思路：先查目标表再入队，同一 (date, kind) 幂等跳过；
    返回各 kind 入队计数供日志记录。由 worker 周期调度调用（东八区 05:00 后）。
    """
    enqueued = {"daily_sign_fortune": 0, "daily_device_content": 0}
    existing = await _existing_fortune_signs(session, content_date)
    if any(sign not in existing for sign in SIGN_KEYS):
        session.add(
            AgentTask(
                kind="daily_sign_fortune",
                payload={"date": content_date.isoformat()},
                status="pending",
            )
        )
        enqueued["daily_sign_fortune"] += 1
    device_ids = await _claimed_device_ids(session)
    have_greeting = await _devices_with_content(session, device_ids, content_date, "greeting")
    for device_id in device_ids:
        if device_id in have_greeting:
            continue  # 幂等：当日 greeting 已存在
        session.add(
            AgentTask(
                kind="daily_device_content",
                payload={"device_id": device_id, "date": content_date.isoformat()},
                status="pending",
            )
        )
        enqueued["daily_device_content"] += 1
    existing_kinds = await _existing_quiz_kinds(session, content_date)
    missing_kinds = [kind for kind in QUIZ_KINDS if kind not in existing_kinds]
    if missing_kinds:
        session.add(
            AgentTask(
                kind="fun_quiz_generate",
                payload={"date": content_date.isoformat(), "kinds": missing_kinds},
                status="pending",
            )
        )
        enqueued["fun_quiz_generate"] = 1
    else:
        enqueued["fun_quiz_generate"] = 0
    return enqueued


async def _existing_quiz_kinds(session: AsyncSession, quiz_date: date) -> set[str]:
    result = await session.execute(select(FunQuiz.kind).where(FunQuiz.quiz_date == quiz_date))
    return set(result.scalars().all())


async def fun_quiz_generate_handler(payload: dict[str, Any], session: AsyncSession) -> None:
    """每日补齐三类趣味测验；已有的 kind 跳过。"""
    quiz_date = _task_date(payload)
    wanted = payload.get("kinds")
    kinds = [str(item) for item in wanted] if isinstance(wanted, list) else list(QUIZ_KINDS)
    existing = set(
        (await session.execute(select(FunQuiz.kind).where(FunQuiz.quiz_date == quiz_date)))
        .scalars()
        .all()
    )
    settings = get_settings()
    for kind in kinds:
        if kind not in QUIZ_KINDS or kind in existing:
            continue
        raw = await generate_fun_quiz(settings, kind, quiz_date)
        questions = public_questions(raw)
        archetypes = raw.get("archetypes")
        if len(questions) < 4 or not isinstance(archetypes, dict) or len(archetypes) < 2:
            raise ValueError("generated quiz failed validation")
        # public_questions 丢掉了 scores，入库必须保留模型返回的完整 questions
        raw_questions = raw.get("questions")
        full_questions = raw_questions[:20] if isinstance(raw_questions, list) else []
        session.add(
            FunQuiz(
                kind=kind,
                title=str(raw.get("title") or "今日小测试")[:120],
                subtitle=str(raw.get("subtitle") or "")[:240],
                payload={"questions": full_questions, "archetypes": archetypes},
                source="llm",
                quiz_date=quiz_date,
            )
        )


async def memory_profile_handler(payload: dict[str, Any], session: AsyncSession) -> None:
    """E6.1：根据 active 记忆生成可展示画像；无记忆也写空卡片。"""
    device_id = payload.get("device_id")
    if not isinstance(device_id, int):
        raise ValueError("memory_profile payload requires integer device_id")
    reason = str(payload.get("reason") or "update")[:32]
    memories = (
        (
            await session.execute(
                select(Memory)
                .where(Memory.device_id == device_id, Memory.status == "active")
                .order_by(Memory.updated_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "title": (memory.title or "")[:200],
            "content": memory.content[:400],
            "tags": memory.tags[:10],
        }
        for memory in memories
    ]
    if not items:
        session.add(
            AnalysisResult(
                device_id=device_id,
                kind="memory_profile",
                payload={
                    "remembered": [],
                    "companion_impact": "还没有已确认的长期记忆。",
                    "memory_count": 0,
                    "updated_from": reason,
                },
            )
        )
        return
    result = await generate_memory_profile(get_settings(), items, reason)
    remembered_raw = result.get("remembered")
    remembered: list[dict[str, Any]] = []
    if isinstance(remembered_raw, list):
        for item in remembered_raw[:8]:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or "").strip()[:120]
            title = str(item.get("title") or "").strip()[:80]
            if not summary and not title:
                continue
            remembered.append(
                {
                    "title": title or "记忆",
                    "summary": summary,
                    "tags": _text_list(item.get("tags"), maximum=8),
                }
            )
    impact = str(result.get("companion_impact") or "").strip()[:400]
    session.add(
        AnalysisResult(
            device_id=device_id,
            kind="memory_profile",
            payload={
                "remembered": remembered,
                "companion_impact": impact or "已确认记忆可用于之后的陪伴。",
                "memory_count": len(items),
                "updated_from": reason,
            },
        )
    )


async def purge_expired_data(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """E8 数据保留：按文档窗口物理删除过期行。"""
    from sqlalchemy import delete

    moment = now or datetime.now(UTC)
    counts = {"messages": 0, "analyses": 0, "tasks": 0}
    msg_result = await session.execute(
        delete(ChatMessage).where(ChatMessage.created_at < moment - timedelta(days=180))
    )
    counts["messages"] = int(getattr(msg_result, "rowcount", 0) or 0)
    analysis_result = await session.execute(
        delete(AnalysisResult).where(
            AnalysisResult.kind.in_(("daily_summary", "persona_growth", "data_export")),
            AnalysisResult.created_at < moment - timedelta(days=90),
        )
    )
    counts["analyses"] = int(getattr(analysis_result, "rowcount", 0) or 0)
    profile_result = await session.execute(
        delete(AnalysisResult).where(
            AnalysisResult.kind == "memory_profile",
            AnalysisResult.created_at < moment - timedelta(days=180),
        )
    )
    counts["analyses"] += int(getattr(profile_result, "rowcount", 0) or 0)
    task_result = await session.execute(
        delete(AgentTask).where(
            AgentTask.status.in_(("done", "failed")),
            AgentTask.updated_at < moment - timedelta(days=30),
        )
    )
    counts["tasks"] = int(getattr(task_result, "rowcount", 0) or 0)
    return counts


TASK_REGISTRY: dict[str, TaskHandler] = {
    "daily_summary": daily_summary_handler,
    "daily_sign_fortune": daily_sign_fortune_handler,
    "daily_device_content": daily_device_content_handler,
    "memory_profile": memory_profile_handler,
    "fun_quiz_generate": fun_quiz_generate_handler,
}
