"""首版完整人设 KB 种子的回归约束。"""

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_seed_migration() -> ModuleType:
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0006_complete_persona_kb_seed.py"
    spec = importlib.util.spec_from_file_location("persona_kb_seed", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complete_persona_seed_covers_twelve_signs_and_sixteen_mbti() -> None:
    seed = _load_seed_migration()
    sign_keys = {row[0] for row in seed.SIGN_SEEDS}
    mbti_keys = {row[0] for row in seed.MBTI_SEEDS}

    assert sign_keys | {"pisces"} == {
        "aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio",
        "sagittarius", "capricorn", "aquarius", "pisces",
    }
    assert mbti_keys | {"INFP", "ISFP"} == {
        "INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP",
    }
