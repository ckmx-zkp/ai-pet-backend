"""趣味测验、作答记录与简略星盘表。

Revision ID: 0010_fun_quiz_and_natal
Revises: 0009_kb_v3_first_person
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from pet_common.fun_quiz import SEED_QUIZZES

revision: str = "0010_fun_quiz_and_natal"
down_revision: str | None = "0009_kb_v3_first_person"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fun_quizzes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("subtitle", sa.String(240), nullable=False, server_default=""),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source", sa.String(16), nullable=False, server_default="seed"),
        sa.Column("quiz_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_fun_quizzes_date_kind", "fun_quizzes", ["quiz_date", "kind"])
    op.create_table(
        "fun_quiz_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "device_id", sa.BigInteger(), sa.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "quiz_id", sa.BigInteger(), sa.ForeignKey("fun_quizzes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "answers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_fun_quiz_attempts_user_created", "fun_quiz_attempts", ["user_id", "created_at"]
    )
    op.create_table(
        "natal_charts",
        sa.Column(
            "device_id",
            sa.BigInteger(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("has_time", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("has_place", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "chart",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    conn = op.get_bind()
    for seed in SEED_QUIZZES:
        conn.execute(
            sa.text(
                "INSERT INTO fun_quizzes (kind, title, subtitle, payload, source, quiz_date) "
                "VALUES (:kind, :title, :subtitle, CAST(:payload AS jsonb), 'seed', NULL)"
            ),
            {
                "kind": seed["kind"],
                "title": seed["title"],
                "subtitle": seed["subtitle"],
                "payload": json.dumps(seed["payload"], ensure_ascii=False),
            },
        )


def downgrade() -> None:
    op.drop_table("natal_charts")
    op.drop_index("ix_fun_quiz_attempts_user_created", table_name="fun_quiz_attempts")
    op.drop_table("fun_quiz_attempts")
    op.drop_index("ix_fun_quizzes_date_kind", table_name="fun_quizzes")
    op.drop_table("fun_quizzes")
