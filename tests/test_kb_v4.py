"""测试 KB v4 知识库数据与编译器集成。"""

from persona_compiler import KBEntry, compile_persona
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


def test_kb_v4_completeness() -> None:
    # 4 元素
    assert len(ELEMENT_V2) == 4
    element_keys = {e["key"] for e in ELEMENT_V2}
    assert element_keys == {"fire", "earth", "air", "water"}

    # 3 动力
    assert len(MODALITY_V1) == 3
    modality_keys = {m["key"] for m in MODALITY_V1}
    assert modality_keys == {"cardinal", "fixed", "mutable"}

    # 12 星座
    assert len(SIGN_V4) == 12
    sign_keys = {s["key"] for s in SIGN_V4}
    assert sign_keys == {
        "aries", "taurus", "gemini", "cancer",
        "leo", "virgo", "libra", "scorpio",
        "sagittarius", "capricorn", "aquarius", "pisces",
    }

    # 16 MBTI
    assert len(MBTI_V4) == 16
    mbti_keys = {m["key"] for m in MBTI_V4}
    assert mbti_keys == {
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP",
    }


def test_kb_v4_payload_format() -> None:
    # 检查 element
    for e in ELEMENT_V2:
        payload = element_v2_payload(e)
        assert payload["voice"] == "first_person_pet"
        assert len(payload["prompt_fragments"]) >= 1
        assert "metaphysics" in payload
        assert "tags" in payload["retrieval_hints"]

    # 检查 modality
    for m in MODALITY_V1:
        payload = modality_v1_payload(m)
        assert payload["voice"] == "first_person_pet"
        assert len(payload["prompt_fragments"]) >= 1
        assert "metaphysics" in payload

    # 检查 sign
    for s in SIGN_V4:
        payload = sign_v4_payload(s)
        assert payload["voice"] == "first_person_pet"
        assert len(payload["prompt_fragments"]) >= 1
        assert len(payload["taboo"]) >= 1
        assert "wuxing_affinity" in payload["metaphysics"]

    # 检查 mbti
    for m in MBTI_V4:
        payload = mbti_v4_payload(m)
        assert payload["voice"] == "first_person_pet"
        assert len(payload["prompt_fragments"]) >= 1
        assert "cognitive_focus" in payload


def test_compile_persona_with_v4() -> None:
    # 抽取 pisces 与 water 与 INFP 测试编译兼容
    water_entry = next(e for e in ELEMENT_V2 if e["key"] == "water")
    pisces_entry = next(s for s in SIGN_V4 if s["key"] == "pisces")
    infp_entry = next(m for m in MBTI_V4 if m["key"] == "INFP")

    water_kb = KBEntry(level="element", key="water", version=2, payload=element_v2_payload(water_entry))
    pisces_kb = KBEntry(level="sign", key="pisces", version=4, payload=sign_v4_payload(pisces_entry))
    infp_kb = KBEntry(level="mbti", key="INFP", version=4, payload=mbti_v4_payload(infp_entry))

    pack = compile_persona(water_kb, pisces_kb, infp_kb)
    assert pack["kb_version"] == 4
    assert pack["sun_sign"] == "pisces"
    assert pack["mbti"] == "INFP"
    assert any("双鱼座" in frag for frag in pack["prompt_fragments"])
    assert any("Fi-Ne" in frag for frag in pack["prompt_fragments"])
    assert len(pack["taboo"]) >= 2
