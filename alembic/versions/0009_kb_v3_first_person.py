"""KB v3：12 星座 + 16 MBTI 第一人称片段（B5）。

只 INSERT version++ 的 published 新行，不 UPDATE 已发布行。

Revision ID: 0009_kb_v3_first_person
Revises: 0008_daily_fortune
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from persona_compiler.kb_v3 import MBTI_V3, SIGN_V3, mbti_payload, sign_payload

revision: str = "0009_kb_v3_first_person"
down_revision: str | None = "0008_daily_fortune"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    for key, parent_key, fragment, style, taboo in SIGN_V3:
        version = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM zodiac_kb_entries "
                "WHERE level = 'sign' AND key = :key"
            ),
            {"key": key},
        ).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO zodiac_kb_entries "
                "(level, key, parent_key, version, status, payload) "
                "VALUES ('sign', :key, :parent_key, :version, 'published', CAST(:payload AS jsonb))"
            ),
            {
                "key": key,
                "parent_key": parent_key,
                "version": int(version or 1),
                "payload": json.dumps(sign_payload(fragment, style, taboo, key), ensure_ascii=False),
            },
        )
    for key, fragment, style in MBTI_V3:
        version = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM mbti_kb_entries WHERE key = :key"
            ),
            {"key": key},
        ).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO mbti_kb_entries (key, version, status, payload) "
                "VALUES (:key, :version, 'published', CAST(:payload AS jsonb))"
            ),
            {
                "key": key,
                "version": int(version or 1),
                "payload": json.dumps(mbti_payload(fragment, style), ensure_ascii=False),
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM zodiac_kb_entries WHERE level = 'sign' "
            "AND payload->>'voice' = 'first_person_pet'"
        )
    )
    conn.execute(sa.text("DELETE FROM mbti_kb_entries WHERE payload->>'voice' = 'first_person_pet'"))
