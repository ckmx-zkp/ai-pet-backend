"""简略星盘与趣味测验纯函数。"""

from datetime import date, time

from pet_common.fun_quiz import SEED_QUIZZES, public_questions, score_fun_quiz
from pet_common.natal import compute_natal_chart, resolve_city, sign_from_longitude


def test_sign_from_longitude_boundaries() -> None:
    assert sign_from_longitude(0)[0] == "aries"
    assert sign_from_longitude(29.9)[0] == "aries"
    assert sign_from_longitude(30)[0] == "taurus"
    assert sign_from_longitude(359)[0] == "pisces"


def test_scorpio_sun_on_known_date() -> None:
    chart = compute_natal_chart(date(1995, 11, 8))
    assert chart["bodies"]["sun"]["sign"] == "scorpio"
    assert chart["has_rising"] is False
    assert "白羊" not in chart["headline"] or "日天蝎" in chart["headline"]
    assert chart["share_card"]["result"].startswith("日天蝎")


def test_rising_requires_time_and_place() -> None:
    coords = resolve_city("北京")
    assert coords is not None
    chart = compute_natal_chart(
        date(1995, 11, 8),
        birth_time=time(14, 30),
        latitude=coords[0],
        longitude=coords[1],
    )
    assert chart["has_rising"] is True
    assert chart["ascendant"] is not None
    assert chart["ascendant"]["sign"] in {
        "aries",
        "taurus",
        "gemini",
        "cancer",
        "leo",
        "virgo",
        "libra",
        "scorpio",
        "sagittarius",
        "capricorn",
        "aquarius",
        "pisces",
    }


def test_seed_psychology_all_a_is_spark() -> None:
    seed = next(item for item in SEED_QUIZZES if item["kind"] == "psychology")
    public = public_questions(seed["payload"])
    assert 4 <= len(public) <= 20
    assert "scores" not in public[0]["options"][0]
    scored = score_fun_quiz(seed["payload"], ["a"] * len(seed["payload"]["questions"]))
    assert scored["archetype"] == "spark"
    assert "太阳" in scored["title"]
