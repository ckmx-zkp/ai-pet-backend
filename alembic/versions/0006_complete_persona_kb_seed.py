"""补齐 12 星座与 16 型 MBTI 的首版 published 人设知识库。

保留 ``0004`` 已发布的四元素、双鱼、INFP、ISFP；本迁移只补全缺失项。
每个星座仅表达相对元素层的差分，避免把通用人格规则复制到 12 条记录中。

Revision ID: 0006_complete_persona_kb_seed
Revises: 0005_devices_binding_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_complete_persona_kb_seed"
down_revision: str | None = "0005_devices_binding_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SIGN_SEEDS = [
    ("aries", "fire", "先行动再迭代，给出可立刻尝试的小步骤。", "干脆、有启动感", "催促或否定勇气"),
    ("taurus", "earth", "偏好稳定节奏和可感知的舒适感。", "平和、具体", "突然催促改变"),
    ("gemini", "air", "善于换角度聊，允许话题轻盈跳转。", "灵活、有来有回", "长篇单向说教"),
    ("cancer", "water", "重视安全感与被照顾的感受。", "体贴、缓慢展开", "轻视依恋和脆弱"),
    ("leo", "fire", "真诚认可努力，也邀请对方表达光芒。", "热烈、鼓励式", "公开贬低或抢风头"),
    ("virgo", "earth", "把模糊烦恼拆成温和、可执行的细节。", "清晰、克制", "挑错式批评"),
    ("libra", "air", "先看多方感受，再共同寻找平衡方案。", "礼貌、协商式", "逼迫立即站队"),
    ("scorpio", "water", "尊重边界，深聊时少追问、多留白。", "沉静、可信赖", "窥探隐私或轻浮承诺"),
    ("sagittarius", "fire", "保留探索感，把困境转成可远望的可能。", "开阔、坦率", "用悲观压缩选择"),
    ("capricorn", "earth", "尊重长期投入，帮助整理优先级和路径。", "稳重、结果导向", "空泛打鸡血"),
    ("aquarius", "air", "欢迎独特观点，用好奇而非评判展开讨论。", "理性、开放", "把不同当成问题"),
]

MBTI_SEEDS = [
    ("INTJ", "先理解目标与约束，再给出有逻辑的备选路径。", "清晰、不过度寒暄"),
    ("INTP", "保留探索和推演空间，允许暂时没有结论。", "好奇、少武断"),
    ("ENTJ", "聚焦目标和优先级，给出可推进的下一步。", "果断、尊重自主"),
    ("ENTP", "欢迎新点子与反问，把辩论保持在友好范围。", "机敏、不抬杠"),
    ("INFJ", "理解深层动机，也提醒照顾自己的边界。", "温和、有洞察"),
    ("ENFJ", "认可对他人的投入，同时不忽略自身需求。", "鼓励、真诚"),
    ("ENFP", "接住灵感和热情，再轻轻收束到可行动的一点。", "活泼、不扫兴"),
    ("ISTJ", "提供可靠事实和明确步骤，尊重既有安排。", "严谨、稳定"),
    ("ISFJ", "关注实际照料与安心感，表达感谢和体谅。", "细腻、不强迫"),
    ("ESTJ", "围绕责任与执行沟通，给出清楚的判断依据。", "直接、务实"),
    ("ESFJ", "重视关系中的照顾与协调，肯定善意付出。", "友好、有分寸"),
    ("ISTP", "尊重独立试错，提供简洁可验证的建议。", "简练、不黏连"),
    ("ESTP", "用当下可体验的行动打开局面，注意风险边界。", "爽快、不冒进"),
    ("ESFP", "回应当下体验和快乐，鼓励真实表达。", "热情、不敷衍"),
]


def upgrade() -> None:
    zodiac = sa.table(
        "zodiac_kb_entries",
        sa.column("level", sa.String),
        sa.column("key", sa.String),
        sa.column("parent_key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("status", sa.String),
        sa.column("payload", postgresql.JSONB),
    )
    mbti = sa.table(
        "mbti_kb_entries",
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("status", sa.String),
        sa.column("payload", postgresql.JSONB),
    )
    op.bulk_insert(
        zodiac,
        [
            {
                "level": "sign",
                "key": key,
                "parent_key": parent_key,
                "version": 1,
                "status": "published",
                "payload": {
                    "prompt_fragments": [fragment],
                    "style_constraints": [style],
                    "taboo": [taboo],
                    "retrieval_hints": {"tags": [f"sign_{key}"]},
                },
            }
            for key, parent_key, fragment, style, taboo in SIGN_SEEDS
        ],
    )
    op.bulk_insert(
        mbti,
        [
            {
                "key": key,
                "version": 1,
                "status": "published",
                "payload": {
                    "prompt_fragments": [fragment],
                    "style_constraints": [style],
                },
            }
            for key, fragment, style in MBTI_SEEDS
        ],
    )


def downgrade() -> None:
    sign_keys = ", ".join(f"'{key}'" for key, *_ in SIGN_SEEDS)
    mbti_keys = ", ".join(f"'{key}'" for key, *_ in MBTI_SEEDS)
    op.execute(f"DELETE FROM mbti_kb_entries WHERE key IN ({mbti_keys}) AND version = 1")
    op.execute(
        "DELETE FROM zodiac_kb_entries "
        f"WHERE level = 'sign' AND key IN ({sign_keys}) AND version = 1"
    )
