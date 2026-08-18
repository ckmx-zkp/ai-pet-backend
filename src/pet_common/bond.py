"""宠物与主人的相处关系：一设备一份，可由直选或 worker 根据对话/记忆更新。"""

from datetime import UTC, datetime
from typing import Any

RELATIONSHIP_KINDS: dict[str, str] = {
    "partner": "情感伴侣",
    "rebellious_child": "逆子",
    "beloved_child": "爱子",
    "love_hate": "相爱相杀",
    "confidant": "知己",
    "companion": "陪伴伙伴",
    "guardian": "守护者",
}

_FIRST_APPLY = 0.6
_CHANGE_KIND = 0.8
_REFRESH_SAME = 0.5


def label_for(kind: str) -> str:
    return RELATIONSHIP_KINDS[kind]


def normalize_kind(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace("-", "_")
    if key in RELATIONSHIP_KINDS:
        return key
    inverted = {label: kind for kind, label in RELATIONSHIP_KINDS.items()}
    return inverted.get(value.strip())


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
