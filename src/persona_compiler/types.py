"""persona-compiler 的类型定义。

payload 建议键（docs/02）：traits, taboo, style, prompt_fragments, emotion_map, retrieval_hints。
"""

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass(frozen=True)
class KBEntry:
    """一条 published KB 条目（zodiac element/sign 或 mbti）。

    对应 zodiac_kb_entries / mbti_kb_entries 中 status=published 的行。
    """

    level: str  # element | sign | modality | mbti
    key: str  # water / pisces / INFP ...
    version: int
    payload: dict[str, Any] = field(default_factory=dict)


class PersonaPack(TypedDict):
    """编译产物（persona_pack），供 xiaozhi-server 会话前拉取。

    kb_version 取参与编译的各 KB 条目 version 最大值，作为钉扎/缓存依据。
    """

    kb_version: int
    sun_sign: str
    mbti: str
    traits: dict[str, Any]
    taboo: list[str]
    style: dict[str, Any]
    prompt_fragments: list[str]
    emotion_map: dict[str, Any]
    retrieval_hints: dict[str, Any]
    daily_context: str | None
