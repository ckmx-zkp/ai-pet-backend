"""宠物与主人的相处关系：一设备一份，可由直选或 worker 根据对话/记忆更新。"""

from datetime import UTC, datetime
from typing import Any

RELATIONSHIP_KINDS: dict[str, str] = {
    "cherished_pet": "爱宠",
    "family_cub": "家中幼崽",
    "pack_youngest": "窝里最小的",
    "treasure": "掌上明珠",
    "warm_jacket": "小棉袄",
    "spoiled_pet": "被惯坏的主子",
    "beloved_child": "爱子",
    "rebellious_child": "逆子",
    "daughter": "女儿",
    "son": "儿子",
    "little_sibling": "弟妹",
    "partner": "情感伴侣",
    "old_couple": "老夫老妻",
    "ambiguous": "暧昧对象",
    "love_hate": "相爱相杀",
    "bickering": "欢喜冤家",
    "roast_buddy": "损友",
    "confidant": "知己",
    "bestie": "闺蜜",
    "companion": "陪伴伙伴",
    "tree_hole": "树洞",
    "healer": "疗愈系",
    "guardian": "守护者",
    "steward": "管家",
    "advisor": "军师",
    "tech_buddy": "技术搭子",
    "tsukkomi": "吐槽役",
}

_KIND_ALIASES: dict[str, str] = {
    "爱宠": "cherished_pet",
    "宠物": "cherished_pet",
    "幼崽": "family_cub",
    "小主子": "spoiled_pet",
    "明珠": "treasure",
}

_FIRST_APPLY = 0.6
_CHANGE_KIND = 0.8
_REFRESH_SAME = 0.5


def label_for(kind: str) -> str:
    return RELATIONSHIP_KINDS[kind]


def catalog() -> list[dict[str, str]]:
    return [{"kind": key, "label": label} for key, label in RELATIONSHIP_KINDS.items()]


def kind_union() -> str:
    return "|".join(RELATIONSHIP_KINDS)


def kind_prompt_block() -> str:
    lines = "，".join(f"{key}={label}" for key, label in RELATIONSHIP_KINDS.items())
    return (
        f"relationship.kind 必须是：{kind_union()}。"
        f"含义：{lines}。"
        "优先看已确认记忆和多次出现的家庭/命名设定；"
        "单次硬件调试、麦克风漏字或唤醒词闲聊不得单独改成技术搭子或陪伴伙伴。"
    )


def normalize_kind(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace("-", "_")
    if key in RELATIONSHIP_KINDS:
        return key
    inverted = {label: kind for kind, label in RELATIONSHIP_KINDS.items()}
    raw = value.strip()
    return inverted.get(raw) or _KIND_ALIASES.get(raw)


def public_bond(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = normalize_kind(raw.get("kind"))
    if kind is None:
        return None
    summary = raw.get("summary")
    return {
        "kind": kind,
        "label": label_for(kind),
        "summary": summary.strip()[:200] if isinstance(summary, str) else "",
        "source": raw.get("source") if raw.get("source") in {"manual", "worker"} else "worker",
        "confidence": _as_confidence(raw.get("confidence")),
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None,
    }


def bond_prompt_fragment(raw: object) -> str | None:
    viewed = public_bond(raw)
    if viewed is None:
        return None
    summary = viewed["summary"]
    extra = f"：{summary}" if summary else ""
    return (
        f"你和主人此刻的关系是「{viewed['label']}」{extra}。"
        "说话、亲昵或顶嘴都按这个关系来；这是你们之间的关系，不是你的星座或 MBTI。"
    )


def should_apply_bond(current: object, inferred: dict[str, Any]) -> bool:
    kind = normalize_kind(inferred.get("kind"))
    if kind is None:
        return False
    if inferred.get("decision") == "hold":
        return False
    confidence = _as_confidence(inferred.get("confidence"))
    current_kind = None
    if isinstance(current, dict):
        current_kind = normalize_kind(current.get("kind"))
    if current_kind is None:
        return confidence >= _FIRST_APPLY
    if current_kind == kind:
        return confidence >= _REFRESH_SAME
    return confidence >= _CHANGE_KIND


def merge_bond(current: object, inferred: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    if not should_apply_bond(current, inferred):
        return None
    kind = normalize_kind(inferred.get("kind"))
    if kind is None:
        return None
    summary = inferred.get("summary")
    return {
        "kind": kind,
        "label": label_for(kind),
        "summary": summary.strip()[:200] if isinstance(summary, str) else "",
        "source": source,
        "confidence": _as_confidence(inferred.get("confidence")),
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _as_confidence(value: object) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return 0.0
