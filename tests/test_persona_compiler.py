"""persona-compiler 最小单测示例（vibe coding 红线：纯函数必须 pytest 覆盖）。

对应 docs/03 验收：编译单测——pisces 包包含 water 片段 + 双鱼差分。
"""

from persona_compiler import KBEntry, compile_persona

WATER = KBEntry(
    level="element",
    key="water",
    version=3,
    payload={
        "traits": {"共情": 0.9},
        "taboo": ["冷暴力"],
        "style": {"tone": "温柔"},
        "prompt_fragments": ["你是水相气质，先接住对方情绪"],
        "emotion_map": {"sad": "陪伴"},
        "retrieval_hints": {"tags": ["element_water"]},
    },
)

PISCES = KBEntry(
    level="sign",
    key="pisces",
    version=5,
    payload={
        "traits": {"爱做梦": 0.8},
        "taboo": ["冷暴力", "拆穿幻想"],  # 与 element 重复项应去重
        "prompt_fragments": ["双鱼差分：多用隐喻，陪TA做梦"],
    },
)

INFP = KBEntry(
    level="mbti",
    key="INFP",
    version=2,
    payload={"prompt_fragments": ["INFP：内倾共情，少讲道理多讲感受"]},
)


def test_pisces_pack_contains_water_fragments_and_sign_diff() -> None:
    pack = compile_persona(WATER, PISCES, INFP)

    # water 片段 + 双鱼差分 + mbti 片段全部进入 persona_pack
    assert "你是水相气质，先接住对方情绪" in pack["prompt_fragments"]
    assert "双鱼差分：多用隐喻，陪TA做梦" in pack["prompt_fragments"]
    assert "INFP：内倾共情，少讲道理多讲感受" in pack["prompt_fragments"]

    # 合并与去重
    assert pack["traits"] == {"共情": 0.9, "爱做梦": 0.8}
    assert pack["taboo"] == ["冷暴力", "拆穿幻想"]
    assert pack["style"] == {"tone": "温柔"}

    # kb_version 取参与条目最大 version；sign/mbti 键正确
    assert pack["kb_version"] == 5
    assert pack["sun_sign"] == "pisces"
    assert pack["mbti"] == "INFP"
    assert pack["daily_context"] is None


def test_overrides_have_highest_priority() -> None:
    overrides = {
        "style": {"tone": "活泼"},
        "prompt_fragments": ["用户忌口：不要提水"],
    }
    pack = compile_persona(WATER, PISCES, INFP, overrides=overrides, daily_context="今日宜倾诉")

    assert pack["style"]["tone"] == "活泼"  # overrides 覆盖 element
    assert "用户忌口：不要提水" in pack["prompt_fragments"]
    assert pack["daily_context"] == "今日宜倾诉"
