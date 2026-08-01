"""对话内容脱敏（docs/04 §脱敏历史 + 红线 1）：落库前执行，chat_messages 只存 content_redacted。

规则最小可用（V0.2）：手机号 / 身份证号 / 邮箱 / 银行卡号 → ``[已脱敏:类型]``。
命中顺序即替换顺序：身份证号（18 位）先于银行卡号（16~19 位），
避免 18 位纯数字证件号被银行卡规则误切。
"""

import re

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("银行卡号", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
)


def redact_text(content: str) -> str:
    """对单条文本执行全部脱敏规则，返回脱敏后文本（无命中时原样返回）。"""
    for label, pattern in _RULES:
        content = pattern.sub(f"[已脱敏:{label}]", content)
    return content
