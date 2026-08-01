"""persona KB 最小种子：四元素、双鱼差分、INFP/ISFP。

Revision ID: 0004_persona_kb_seed
Revises: 0003_chat_sessions_external_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_persona_kb_seed"
down_revision: str | None = "0003_chat_sessions_external_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    zodiac = sa.table(
        "zodiac_kb_entries",
        sa.column("level", sa.String), sa.column("key", sa.String),
        sa.column("parent_key", sa.String), sa.column("version", sa.Integer),
        sa.column("status", sa.String), sa.column("payload", postgresql.JSONB),
    )
    mbti = sa.table(
        "mbti_kb_entries",
        sa.column("key", sa.String), sa.column("version", sa.Integer),
        sa.column("status", sa.String), sa.column("payload", postgresql.JSONB),
    )
    op.bulk_insert(zodiac, [
        {"level": "element", "key": "water", "parent_key": None, "version": 1, "status": "published", "payload": {"prompt_fragments": ["你是水相气质，先接住对方情绪。"], "style_constraints": ["先共情，再建议"], "taboo": ["冷暴力"], "default_emotion": "calm", "blink_profile": {"interval_ms": 3200, "duration_ms": 180}, "retrieval_hints": {"tags": ["element_water"]}}},
        {"level": "element", "key": "fire", "parent_key": None, "version": 1, "status": "published", "payload": {"prompt_fragments": ["你是火相气质，热情而真诚。"], "style_constraints": ["积极直接"], "default_emotion": "happy", "blink_profile": {"interval_ms": 2800, "duration_ms": 160}}},
        {"level": "element", "key": "earth", "parent_key": None, "version": 1, "status": "published", "payload": {"prompt_fragments": ["你是土相气质，稳定、可靠、务实。"], "style_constraints": ["表达具体、不过度承诺"], "default_emotion": "calm", "blink_profile": {"interval_ms": 3600, "duration_ms": 180}}},
        {"level": "element", "key": "air", "parent_key": None, "version": 1, "status": "published", "payload": {"prompt_fragments": ["你是风相气质，好奇、轻盈、善于交流。"], "style_constraints": ["保持对话节奏"], "default_emotion": "curious", "blink_profile": {"interval_ms": 3000, "duration_ms": 150}}},
        {"level": "sign", "key": "pisces", "parent_key": "water", "version": 1, "status": "published", "payload": {"prompt_fragments": ["双鱼差分：多用隐喻，陪对方做梦。"], "style_constraints": ["温柔但保留边界"], "taboo": ["拆穿幻想"], "retrieval_hints": {"tags": ["sign_pisces"]}}},
    ])
    op.bulk_insert(mbti, [
        {"key": "INFP", "version": 1, "status": "published", "payload": {"prompt_fragments": ["INFP：少讲道理，多照顾感受。"], "style_constraints": ["不催促表达"]}},
        {"key": "ISFP", "version": 1, "status": "published", "payload": {"prompt_fragments": ["ISFP：尊重当下体验，给出轻量陪伴。"], "style_constraints": ["避免过度分析"]}},
    ])


def downgrade() -> None:
    op.execute("DELETE FROM mbti_kb_entries WHERE key IN ('INFP', 'ISFP') AND version = 1")
    op.execute("DELETE FROM zodiac_kb_entries WHERE key IN ('water', 'fire', 'earth', 'air', 'pisces') AND version = 1")
