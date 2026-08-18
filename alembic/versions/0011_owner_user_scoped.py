"""主人档案挂用户账号；八字与星盘从设备级迁到账号级。

Revision ID: 0011_owner_user_scoped
Revises: 0010_fun_quiz_and_natal
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_owner_user_scoped"
down_revision: str | None = "0010_fun_quiz_and_natal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "owner_profiles",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sun_sign", sa.String(32), nullable=True),
        sa.Column("mbti", sa.String(8), nullable=True),
        sa.Column(
            "quiz_results",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO owner_profiles (user_id, quiz_results)
            SELECT user_id, jsonb_object_agg(kind, payload)
            FROM (
                SELECT DISTINCT ON (a.user_id, q.kind)
                    a.user_id,
                    q.kind,
                    jsonb_build_object(
                        'archetype', a.result->'archetype',
                        'title', a.result->'title',
                        'summary', a.result->'summary',
                        'quiz_id', a.quiz_id,
                        'attempt_id', a.id
                    ) AS payload
                FROM fun_quiz_attempts a
                JOIN fun_quizzes q ON q.id = a.quiz_id
                ORDER BY a.user_id, q.kind, a.created_at DESC
            ) latest
            GROUP BY user_id
            """
        )
    )

    op.create_table(
        "owner_bazi_profiles_user",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("calendar_type", sa.String(8), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("birth_time", sa.Time(), nullable=True),
        sa.Column("birth_place", sa.String(128), nullable=True),
        sa.Column("gender", sa.String(16), nullable=True),
        sa.Column("bazi_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO owner_bazi_profiles_user (
                user_id, calendar_type, birth_date, birth_time, birth_place,
                gender, bazi_text, created_at, updated_at
            )
            SELECT DISTINCT ON (d.user_id)
                d.user_id, b.calendar_type, b.birth_date, b.birth_time, b.birth_place,
                b.gender, b.bazi_text, b.created_at, b.updated_at
            FROM owner_bazi_profiles b
            JOIN devices d ON d.id = b.device_id
            WHERE d.user_id IS NOT NULL
            ORDER BY d.user_id, b.updated_at DESC, b.device_id DESC
            """
        )
    )
    op.drop_table("owner_bazi_profiles")
    op.rename_table("owner_bazi_profiles_user", "owner_bazi_profiles")

    op.create_table(
        "natal_charts_user",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO natal_charts_user (
                user_id, birth_date, has_time, has_place, chart, created_at, updated_at
            )
            SELECT DISTINCT ON (d.user_id)
                d.user_id, n.birth_date, n.has_time, n.has_place, n.chart,
                n.created_at, n.updated_at
            FROM natal_charts n
            JOIN devices d ON d.id = n.device_id
            WHERE d.user_id IS NOT NULL
            ORDER BY d.user_id, n.updated_at DESC, n.device_id DESC
            """
        )
    )
    op.drop_table("natal_charts")
    op.rename_table("natal_charts_user", "natal_charts")

    conn.execute(
        sa.text(
            """
            INSERT INTO owner_profiles (user_id, sun_sign)
            SELECT user_id, chart->'bodies'->'sun'->>'sign'
            FROM natal_charts
            WHERE chart->'bodies'->'sun'->>'sign' IS NOT NULL
            ON CONFLICT (user_id) DO UPDATE
            SET sun_sign = COALESCE(owner_profiles.sun_sign, EXCLUDED.sun_sign)
            """
        )
    )


def downgrade() -> None:
    op.create_table(
        "natal_charts_device",
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.drop_table("natal_charts")
    op.rename_table("natal_charts_device", "natal_charts")

    op.create_table(
        "owner_bazi_profiles_device",
        sa.Column(
            "device_id",
            sa.BigInteger(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("calendar_type", sa.String(8), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("birth_time", sa.Time(), nullable=True),
        sa.Column("birth_place", sa.String(128), nullable=True),
        sa.Column("gender", sa.String(16), nullable=True),
        sa.Column("bazi_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.drop_table("owner_bazi_profiles")
    op.rename_table("owner_bazi_profiles_device", "owner_bazi_profiles")
    op.drop_table("owner_profiles")
