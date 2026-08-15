"""LLM worker 的纯函数约束：响应必须是 JSON，避免把模型自然语言直接入库。"""

import pytest

from agent_worker.llm import _extract_json, _is_retryable_status
from agent_worker.tasks import _confidence, _text_list
from web_api.routers.internal import _bounded_context


def test_extract_llm_json_object_and_markdown_fence() -> None:
    assert _extract_json('{"daily_summary": {}}') == {"daily_summary": {}}
    assert _extract_json('```json\n{"memory_candidates": []}\n```') == {"memory_candidates": []}
    assert _extract_json('<think>private reasoning</think>\n{"daily_summary": {}}') == {
        "daily_summary": {}
    }


def test_extract_llm_json_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        _extract_json("[]")


def test_retryable_llm_statuses_do_not_exhaust_worker_attempts() -> None:
    assert _is_retryable_status(401)
    assert _is_retryable_status(403)
    assert _is_retryable_status(429)
    assert _is_retryable_status(500)
    assert not _is_retryable_status(400)


def test_worker_normalizes_untrusted_llm_values() -> None:
    assert _confidence(3) == 1.0
    assert _confidence("high") == 0.0
    assert _text_list(["  follow up  ", 1, "", "topic"], maximum=1) == ["follow up"]


def test_context_provider_caps_dynamic_context() -> None:
    values = _bounded_context(["a" * 500, "b" * 500, "", "c"])
    assert len(values) <= 6
    assert sum(len(value) for value in values) <= 800
    assert all(len(value) <= 320 for value in values)
