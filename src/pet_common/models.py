"""SQLAlchemy 2.0 声明式模型，严格对应 docs/02-数据模型与表结构。

索引纪律（docs/08 §8.4 + AGENTS.md）：
- 历史类查询走 (device_id, created_at) 复合索引短路径；
- 每表索引克制在 2~3 个；
- 向量只挂 memories.embedding（pgvector，首版不建 HNSW，量起后再评估）。

`agent_tasks` 为 docs/08 决策的 PG SKIP LOCKED 队列表（docs/02 未列，属基础设施）。
"""

from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有模型的声明式基类。"""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    login_name: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")  # user|admin
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    __table_args__ = (Index("uq_users_login_name", "login_name", unique=True),)


class Device(TimestampMixin, Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 可空：解绑 = user_id 置 NULL（保留行与历史，可重绑），见迁移 0002
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    device_uid: Mapped[str] = mapped_column(String(64), nullable=False)  # MAC/UUID
    # app 认领凭据：独立于 MAC 与连续平台主键，首见设备时生成。
    binding_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmware_version: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("uq_devices_device_uid", "device_uid", unique=True),
        Index("uq_devices_binding_id", "binding_id", unique=True),
        Index("ix_devices_user_id", "user_id"),
    )


class ZodiacKBEntry(Base):
    __tablename__ = "zodiac_kb_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)  # element|sign|modality
    key: Mapped[str] = mapped_column(String(64), nullable=False)  # water / pisces ...
    parent_key: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft"
    )  # draft|published|archived
    # payload 建议键：traits, taboo, style, prompt_fragments, emotion_map, retrieval_hints
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_zodiac_kb_level_key_version", "level", "key", "version", unique=True),
        Index("ix_zodiac_kb_status", "status"),
    )


class MBTIKBEntry(Base):
    __tablename__ = "mbti_kb_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(8), nullable=False)  # INFP ...
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_mbti_kb_key_version", "key", "version", unique=True),
        Index("ix_mbti_kb_status", "status"),
    )


class PersonaProfile(Base):
    __tablename__ = "persona_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    sun_sign: Mapped[str | None] = mapped_column(String(32))
    mbti: Mapped[str | None] = mapped_column(String(8))
    kb_version: Mapped[int | None] = mapped_column(Integer)  # follow_latest=false 时钉死
    follow_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # 稳定角色档案：由用户/Admin 明确维护，不由单次会话 LLM 凭空改写。
    dossier: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    compiled_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # 编译缓存摘要
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_persona_profiles_device_id", "device_id", unique=True),  # 一设备一人设
        Index("ix_persona_profiles_user_id", "user_id"),
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # xiaozhi 侧分配的字符串会话号（UUID 风格），全局唯一；内部自增 id 不暴露给小智
    external_session_id: Mapped[str | None] = mapped_column(String(128))
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_chat_sessions_device_created", "device_id", "created_at"),
        Index("uq_chat_sessions_external_session_id", "external_session_id", unique=True),
    )


class ChatMessage(Base):
    """脱敏消息：红线——只存 content_redacted，不落原文。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user|assistant|system
    content_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_chat_messages_device_created", "device_id", "created_at"),
        Index("ix_chat_messages_session_id", "session_id"),
    )


class Memory(TimestampMixin, Base):
    """长期记忆。source=agent 的记录默认 status=candidate，人审后才 active。"""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )  # active|candidate|archived
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # manual|agent|import
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))  # 首版不建 HNSW 索引

    __table_args__ = (
        Index("ix_memories_device_created", "device_id", "created_at"),
        Index("ix_memories_device_status", "device_id", "status"),
    )


class AnalysisResult(Base):
    """agent-worker 异步产出：日摘要/情绪标签/记忆候选/人设契合/运势小记。"""

    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    # daily_summary|emotion_tags|memory_suggest|persona_fit_review|daily_horoscope_note
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_analysis_results_device_created", "device_id", "created_at"),
        Index("ix_analysis_results_device_kind", "device_id", "kind"),
    )


class DevicePeripheralState(Base):
    """外设快照：一设备一行，POST /api/internal/peripheral/events 覆盖写。"""

    __tablename__ = "device_peripheral_state"

    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    eye_emotion: Mapped[str | None] = mapped_column(String(32))
    eye_gaze: Mapped[str | None] = mapped_column(String(32))
    eye_closed: Mapped[bool | None] = mapped_column(Boolean)
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditLog(Base):
    """审计：删除历史、KB 发布、memory.forget 等敏感操作必写。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)  # user:1 / service:mcp ...
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )


class KBFeedbackCandidate(Base):
    """KB 优化候选（docs/02 △ 可选表）：agent-worker 产出，admin 审核合并。"""

    __tablename__ = "kb_feedback_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )  # pending|accepted|rejected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_kb_feedback_status_created", "status", "created_at"),)


class PersonaDailyContext(Base):
    """日运短上下文（docs/02 △ 可选表）：按日缓存一小段，不进实时重算路径。"""

    __tablename__ = "persona_daily_context"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sign: Mapped[str] = mapped_column(String(32), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="template")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("uq_persona_daily_context_sign_date", "sign", "date", unique=True),)


class DailySignFortune(Base):
    """L1 共享星座日运（E10/docs/12）：全站按 (fortune_date, sign) 唯一，每日每星座一行。"""

    __tablename__ = "daily_sign_fortunes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fortune_date: Mapped[date] = mapped_column(Date, nullable=False)
    sign: Mapped[str] = mapped_column(String(32), nullable=False)  # 12 星座稳定键 aries...
    # payload 钉死键：overall/career/wealth/study/love/source_digest
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    llm_model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("uq_daily_sign_fortunes_date_sign", "fortune_date", "sign", unique=True),
        Index("ix_daily_sign_fortunes_date", "fortune_date"),
    )


class DeviceDailyContent(Base):
    """L2 设备级日内容（E10/docs/12）：kind=greeting|bazi_fortune，按 (device_id, date, kind) 唯一。
    """

    __tablename__ = "device_daily_contents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    content_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # greeting|bazi_fortune
    # greeting: {"text": "..."}；bazi_fortune: {"overall","career","wealth","study","love"}
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "uq_device_daily_contents_device_date_kind",
            "device_id",
            "content_date",
            "kind",
            unique=True,
        ),
        Index("ix_device_daily_contents_device_date", "device_id", "content_date"),
    )


class OwnerBaziProfile(TimestampMixin, Base):
    """主人八字（E10/docs/12，敏感数据）：一设备一行；原始生辰只供 worker 生成使用，

    不进 persona_pack/C5/日志；bazi_text 为 LLM 排盘缓存，出生信息变更时清空重排。
    """

    __tablename__ = "owner_bazi_profiles"

    device_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_type: Mapped[str] = mapped_column(String(8), nullable=False)  # solar|lunar
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    birth_time: Mapped[dt_time | None] = mapped_column(Time)  # 可空=时辰未知
    birth_place: Mapped[str | None] = mapped_column(String(128))
    gender: Mapped[str | None] = mapped_column(String(16))
    bazi_text: Mapped[str | None] = mapped_column(Text)  # LLM 四柱排盘缓存


class AgentTask(TimestampMixin, Base):
    """PG SKIP LOCKED 队列表（docs/08 决策，Redis 仅缓存不入队）。

    出队语义见 agent_worker.worker._claim_next_task：
    SELECT ... WHERE status='pending' AND run_at<=now() ORDER BY id FOR UPDATE SKIP LOCKED。
    """

    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # 对应 worker 注册表 key
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )  # pending|running|done|failed
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_agent_tasks_status_run_at", "status", "run_at"),)
