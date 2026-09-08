"""增加会话内约定表；只新增表，不修改现有身份或历史。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_companion_followups"
down_revision: str | None = "0012_pet_owner_bond"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companion_followups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "device_id",
            sa.BigInteger(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "uq_companion_followup_request",
        "companion_followups",
        ["device_id", "user_id", "request_id"],
        unique=True,
    )
    op.create_index(
        "ix_companion_followup_due",
        "companion_followups",
        ["device_id", "user_id", "status", "due_at"],
    )


def downgrade() -> None:
    op.drop_table("companion_followups")
