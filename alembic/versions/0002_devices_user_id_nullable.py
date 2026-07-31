"""devices.user_id 置可空 — 支持「解绑不删历史」语义

解绑（DELETE /devices/{id}）由删行改为 user_id=NULL 的 UPDATE：保留 devices 行与
全部历史（chat_sessions/chat_messages/memories/analysis_results 仍指向该设备），
device_uid 可被重绑（UPDATE 回原行）。

注意：downgrade 前若存在 user_id 为 NULL 的孤儿行会失败，需先重绑或清理。

Revision ID: 0002_devices_user_id_nullable
Revises: 0001_initial
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_devices_user_id_nullable"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("devices", "user_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column("devices", "user_id", existing_type=sa.BigInteger(), nullable=False)
