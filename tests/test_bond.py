"""相处关系枚举、换型阈值与 prompt 片段。"""

from pet_common.bond import (
    bond_prompt_fragment,
    merge_bond,
    normalize_kind,
    public_bond,
    should_apply_bond,
)


def test_normalize_kind_accepts_label() -> None:
    assert normalize_kind("爱子") == "beloved_child"
    assert normalize_kind("爱宠") == "cherished_pet"
    assert normalize_kind("love_hate") == "love_hate"
    assert normalize_kind("unknown") is None


def test_catalog_has_family_and_pet_roles() -> None:
    from pet_common.bond import RELATIONSHIP_KINDS, catalog

    assert len(RELATIONSHIP_KINDS) >= 20
    labels = {item["label"] for item in catalog()}
    assert {"爱宠", "家中幼崽", "掌上明珠", "情感伴侣", "逆子", "技术搭子"} <= labels


def test_first_bond_requires_moderate_confidence() -> None:
    inferred = {"kind": "partner", "confidence": 0.5, "decision": "approve"}
    assert should_apply_bond({}, inferred) is False
    inferred["confidence"] = 0.7
    assert should_apply_bond({}, inferred) is True


def test_kind_change_requires_high_confidence() -> None:
    current = {"kind": "beloved_child", "summary": "黏人"}
    inferred = {"kind": "rebellious_child", "confidence": 0.7, "decision": "approve"}
    assert should_apply_bond(current, inferred) is False
    inferred["confidence"] = 0.85
    merged = merge_bond(current, inferred, source="worker")
    assert merged is not None
    assert merged["kind"] == "rebellious_child"
    assert merged["label"] == "逆子"
    assert merged["source"] == "worker"


def test_hold_never_applies() -> None:
    assert (
        should_apply_bond({}, {"kind": "partner", "confidence": 0.99, "decision": "hold"})
        is False
    )


def test_prompt_fragment_separates_relationship_from_identity() -> None:
    line = bond_prompt_fragment(
        {"kind": "love_hate", "summary": "拌嘴但不散", "source": "worker", "confidence": 0.9}
    )
    assert line is not None
    assert "相爱相杀" in line
    assert "不是你的星座或 MBTI" in line
    assert public_bond({}) is None
