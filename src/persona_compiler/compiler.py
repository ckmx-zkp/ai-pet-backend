"""PersonaCompiler：纯函数编译器（docs/03 §分层模型）。

输入：published 的 element + sign + mbti KB 条目 + profile.overrides + 可选 daily_context
输出：persona_pack（见 types.PersonaPack）

合并规则（后者覆盖前者，overrides 最高优先级）：
- prompt_fragments / taboo：列表按序拼接并去重（保序）；
- traits / style / emotion_map / retrieval_hints：dict 浅合并，后者键覆盖前者。
"""

from collections.abc import Iterable
from typing import Any

from persona_compiler.types import KBEntry, PersonaPack


def _merge_dicts(dicts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for d in dicts:
        merged.update(d)
    return merged


def _merge_lists(lists: Iterable[list[str]]) -> list[str]:
    """保序去重拼接。"""
    seen: set[str] = set()
    merged: list[str] = []
    for items in lists:
        for item in items:
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return merged


def _get_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    return list(value) if isinstance(value, list) else []


def _get_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    return dict(value) if isinstance(value, dict) else {}


def compile_persona(
    element: KBEntry,
    sign: KBEntry,
    mbti: KBEntry,
    overrides: dict[str, Any] | None = None,
    daily_context: str | None = None,
) -> PersonaPack:
    """编译 element + sign 差分 + mbti + overrides 为 persona_pack。纯函数，无副作用。"""
    layers = [element.payload, sign.payload, mbti.payload, overrides or {}]
    return PersonaPack(
        kb_version=max(element.version, sign.version, mbti.version),
        sun_sign=sign.key,
        mbti=mbti.key,
        traits=_merge_dicts(_get_dict(p, "traits") for p in layers),
        taboo=_merge_lists(_get_list(p, "taboo") for p in layers),
        style=_merge_dicts(_get_dict(p, "style") for p in layers),
        prompt_fragments=_merge_lists(_get_list(p, "prompt_fragments") for p in layers),
        emotion_map=_merge_dicts(_get_dict(p, "emotion_map") for p in layers),
        retrieval_hints=_merge_dicts(_get_dict(p, "retrieval_hints") for p in layers),
        daily_context=daily_context,
    )
