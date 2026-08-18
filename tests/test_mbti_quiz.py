"""E2.1：MBTI 计分纯函数，客户端不得自己算型。"""

import pytest

from persona_compiler import QUESTIONS, question_public_view, score_mbti


def test_question_public_view_hides_scoring_keys() -> None:
    public = question_public_view()
    assert len(public) == 20
    assert len(QUESTIONS) == 20
    assert "a_trait" not in public[0]
    assert {"id", "dimension", "prompt", "a", "b"} <= set(public[0])


def test_score_mbti_all_a_is_estj() -> None:
    assert score_mbti(["a"] * 20) == "ESTJ"


def test_score_mbti_all_b_is_infp() -> None:
    assert score_mbti(["b"] * 20) == "INFP"


def test_score_mbti_rejects_bad_length_or_value() -> None:
    with pytest.raises(ValueError):
        score_mbti(["a"] * 19)
    with pytest.raises(ValueError):
        score_mbti(["c"] * 20)
