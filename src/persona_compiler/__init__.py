"""persona-compiler：element→sign 差分继承 + MBTI + overrides 编译为 persona_pack（docs/03）。

纯函数库，无 IO、无入口；结果可缓存（key=device_id+kb_version+daily_date）。
"""

from persona_compiler.compiler import compile_persona
from persona_compiler.mbti_quiz import QUESTIONS, question_public_view, score_mbti
from persona_compiler.types import KBEntry, PersonaPack

__all__ = [
    "KBEntry",
    "PersonaPack",
    "QUESTIONS",
    "compile_persona",
    "question_public_view",
    "score_mbti",
]
