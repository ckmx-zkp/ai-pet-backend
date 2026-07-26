"""initial schema — 按 docs/02-数据模型与表结构 建首版全部表（含 △ 可选表）

覆盖：users / devices / zodiac_kb_entries / mbti_kb_entries / persona_profiles /
chat_sessions / chat_messages / memories / analysis_results / device_peripheral_state /
audit_logs / kb_feedback_candidates(△) / persona_daily_context(△) / agent_tasks(队列基础设施)。

索引纪律：历史类走 (device_id, created_at) 复合索引；device_uid 唯一；每表 2~3 个克制；
memories.embedding 用 pgvector vector 列（首版不建 HNSW 索引）。

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB_EMPTY = sa.text("'{}'::jsonb")
_NOW = sa.text("now()")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("login_name", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_users_login_name", "users", ["login_name"], unique=True)

    op.create_table(
        "devices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_uid", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("online_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("firmware_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_devices_device_uid", "devices", ["device_uid"], unique=True)
    op.create_index("ix_devices_user_id", "devices", ["user_id"])

    op.create_table(
        "zodiac_kb_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("parent_key", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("payload", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_zodiac_kb_level_key_version",
        "zodiac_kb_entries",
        ["level", "key", "version"],
        unique=True,
    )
    op.create_index("ix_zodiac_kb_status", "zodiac_kb_entries", ["status"])

    op.create_table(
        "mbti_kb_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=8), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("payload", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_mbti_kb_key_version", "mbti_kb_entries", ["key", "version"], unique=True)
    op.create_index("ix_mbti_kb_status", "mbti_kb_entries", ["status"])

    op.create_table(
        "persona_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("sun_sign", sa.String(length=32), nullable=True),
        sa.Column("mbti", sa.String(length=8), nullable=True),
        sa.Column("kb_version", sa.Integer(), nullable=True),
        sa.Column("follow_latest", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("overrides", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("compiled_summary", postgresql.JSONB(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_persona_profiles_device_id", "persona_profiles", ["device_id"], unique=True)
    op.create_index("ix_persona_profiles_user_id", "persona_profiles", ["user_id"])

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_sessions_device_created", "chat_sessions", ["device_id", "created_at"]
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content_redacted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_device_created", "chat_messages", ["device_id", "created_at"]
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    op.create_table(
        "memories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memories_device_created", "memories", ["device_id", "created_at"])
    op.create_index("ix_memories_device_status", "memories", ["device_id", "status"])

    op.create_table(
        "analysis_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_results_device_created", "analysis_results", ["device_id", "created_at"]
    )
    op.create_index("ix_analysis_results_device_kind", "analysis_results", ["device_id", "kind"])

    op.create_table(
        "device_peripheral_state",
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("eye_emotion", sa.String(length=32), nullable=True),
        sa.Column("eye_gaze", sa.String(length=32), nullable=True),
        sa.Column("eye_closed", sa.Boolean(), nullable=True),
        sa.Column("extra", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("detail", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id"])

    op.create_table(
        "kb_feedback_candidates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kb_feedback_status_created", "kb_feedback_candidates", ["status", "created_at"]
    )

    op.create_table(
        "persona_daily_context",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sign", sa.String(length=32), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="template"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_persona_daily_context_sign_date", "persona_daily_context", ["sign", "date"], unique=True
    )

    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_tasks_status_run_at", "agent_tasks", ["status", "run_at"])


def downgrade() -> None:
    op.drop_table("agent_tasks")
    op.drop_table("persona_daily_context")
    op.drop_table("kb_feedback_candidates")
    op.drop_table("audit_logs")
    op.drop_table("device_peripheral_state")
    op.drop_table("analysis_results")
    op.drop_table("memories")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("persona_profiles")
    op.drop_table("mbti_kb_entries")
    op.drop_table("zodiac_kb_entries")
    op.drop_table("devices")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
