"""E10 每日运势与个性化内容三表（docs/12 §3，docs/02 末尾三节）。

daily_sign_fortunes（L1 共享星座日运）/ device_daily_contents（L2 设备级日内容）/
owner_bazi_profiles（主人八字，敏感数据，一设备一行）。
索引纪律：唯一约束 + 一个查询索引，每表不超过 3 个。

Revision ID: 0008_daily_fortune
Revises: 0007_persona_dossier
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_daily_fortune"
down_revision: str | None = "0007_persona_dossier"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB_EMPTY = sa.text("'{}'::jsonb")
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "daily_sign_fortunes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("fortune_date", sa.Date(), nullable=False),
        sa.Column("sign", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("llm_model", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_daily_sign_fortunes_date_sign",
        "daily_sign_fortunes",
        ["fortune_date", "sign"],
        unique=True,
    )
    op.create_index("ix_daily_sign_fortunes_date", "daily_sign_fortunes", ["fortune_date"])

    op.create_table(
        "device_daily_contents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("content_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default=_JSONB_EMPTY, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_device_daily_contents_device_date_kind",
        "device_daily_contents",
        ["device_id", "content_date", "kind"],
        unique=True,
    )
    op.create_index(
        "ix_device_daily_contents_device_date",
        "device_daily_contents",
        ["device_id", "content_date"],
    )

    op.create_table(
        "owner_bazi_profiles",
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("calendar_type", sa.String(length=8), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("birth_time", sa.Time(), nullable=True),
        sa.Column("birth_place", sa.String(length=128), nullable=True),
        sa.Column("gender", sa.String(length=16), nullable=True),
        sa.Column("bazi_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )


def downgrade() -> None:
    op.drop_table("owner_bazi_profiles")
    op.drop_index("ix_device_daily_contents_device_date", table_name="device_daily_contents")
    op.drop_index(
        "uq_device_daily_contents_device_date_kind", table_name="device_daily_contents"
    )
    op.drop_table("device_daily_contents")
    op.drop_index("ix_daily_sign_fortunes_date", table_name="daily_sign_fortunes")
    op.drop_index("uq_daily_sign_fortunes_date_sign", table_name="daily_sign_fortunes")
    op.drop_table("daily_sign_fortunes")
