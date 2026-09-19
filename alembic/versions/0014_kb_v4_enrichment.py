"""KB v4：12 星座 + 4 元素 + 3 动力模式 + 16 MBTI 深度知识库扩展（融合玄学、五行与认知功能）。

只 INSERT version++ 的 published 新行，不 UPDATE 已发布行。

Revision ID: 0014_kb_v4_enrichment
Revises: 0013_companion_followups
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from persona_compiler.kb_v4 import (
    ELEMENT_V2,
    MBTI_V4,
    MODALITY_V1,
    SIGN_V4,
    element_v2_payload,
    mbti_v4_payload,
    modality_v1_payload,
    sign_v4_payload,
)

revision: str = "0014_kb_v4_enrichment"
down_revision: str | None = "0013_companion_followups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. 插入 4 元素 v2
    for entry in ELEMENT_V2:
        key = entry["key"]
        version = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM zodiac_kb_entries "
                "WHERE level = 'element' AND key = :key"
            ),
            {"key": key},
        ).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO zodiac_kb_entries "
                "(level, key, parent_key, version, status, payload) "
                "VALUES ('element', :key, NULL, :version, 'published', CAST(:payload AS jsonb))"
            ),
            {
                "key": key,
                "version": int(version or 1),
                "payload": json.dumps(element_v2_payload(entry), ensure_ascii=False),
            },
        )

    # 2. 插入 3 动力模式 (基本宫 / 固定宫 / 变动宫) v1
    for entry in MODALITY_V1:
        key = entry["key"]
        version = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM zodiac_kb_entries "
                "WHERE level = 'modality' AND key = :key"
            ),
            {"key": key},
        ).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO zodiac_kb_entries "
                "(level, key, parent_key, version, status, payload) "
                "VALUES ('modality', :key, NULL, :version, 'published', CAST(:payload AS jsonb))"
            ),
            {
                "key": key,
                "version": int(version or 1),
                "payload": json.dumps(modality_v1_payload(entry), ensure_ascii=False),
            },
        )

    # 3. 插入 12 星座 v4
    for entry in SIGN_V4:
        key = entry["key"]
        parent_key = entry["parent_key"]
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
                "payload": json.dumps(sign_v4_payload(entry), ensure_ascii=False),
            },
        )

    # 4. 插入 16 型 MBTI v4
    for entry in MBTI_V4:
        key = entry["key"]
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
                "payload": json.dumps(mbti_v4_payload(entry), ensure_ascii=False),
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    # 删除本次注入的带有 metaphysics 的 zodiac 记录
    conn.execute(
        sa.text(
            "DELETE FROM zodiac_kb_entries "
            "WHERE payload ? 'metaphysics'"
        )
    )
    # 删除本次注入的带有 cognitive_focus 的 mbti 记录
    conn.execute(
        sa.text(
            "DELETE FROM mbti_kb_entries "
            "WHERE payload ? 'cognitive_focus'"
        )
    )
