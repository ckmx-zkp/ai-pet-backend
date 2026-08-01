"""chat_sessions 加 external_session_id — 存 xiaozhi 侧字符串会话号

线上 bug 修复：xiaozhi 的 session_id 是字符串（UUID 风格，如 "sess-e3-test-001"），
E3 初版误用内部自增 id 对接，导致 /internal/chat/events 与 /sessions/{id}/end 全部 422。
本迁移新增可空字符串列 external_session_id（唯一索引），内部自增 id 保留不动、不暴露给小智。

可空：迁移前已存在的行无外部会话号；唯一索引在 PG 下天然跳过 NULL，不冲突。

Revision ID: 0003_chat_sessions_external_id
Revises: 0002_devices_user_id_nullable
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_chat_sessions_external_id"
down_revision: str | None = "0002_devices_user_id_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions", sa.Column("external_session_id", sa.String(length=128), nullable=True)
    )
    op.create_index(
        "uq_chat_sessions_external_session_id",
        "chat_sessions",
        ["external_session_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_chat_sessions_external_session_id", table_name="chat_sessions")
    op.drop_column("chat_sessions", "external_session_id")
