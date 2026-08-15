"""受限的 OpenAI 兼容 LLM 客户端，仅供异步 worker 使用。

调用输入只能来自 ``chat_messages.content_redacted``；不得把原始音频、未脱敏文本、
JWT 或数据库连接信息发送给模型服务。
"""

import json
from typing import Any

import httpx

from pet_common.config import Settings


class LLMUnavailableError(RuntimeError):
    """部署尚未配置模型服务时，任务应可重试而不是伪造分析结果。"""


def _is_retryable_status(status_code: int) -> bool:
    """模型供应商鉴权、限流或服务端故障可能在配置修复后恢复。"""
    return status_code in {401, 403, 408, 409, 425, 429} or status_code >= 500


def _extract_json(content: str) -> dict[str, Any]:
    """接受纯 JSON 或模型偶发包裹的 Markdown JSON code fence。"""
    value = content.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else ""
        if value.endswith("```"):
            value = value[:-3]
    parsed: object = json.loads(value.strip())
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


async def generate_structured_analysis(
    settings: Settings, messages: list[dict[str, str]]
) -> dict[str, Any]:
    """请求一次模型并要求返回严格 JSON；调用方负责 schema/业务校验。"""
    system = """你是 AI 陪伴产品的离线分析器。输入均为已脱敏的会话消息。
只返回一个 JSON 对象，禁止 Markdown。不得推断敏感属性、诊断疾病、生成性内容，
不得把单次临时表达当作长期记忆。JSON 结构：
{
  "daily_summary": {
    "summary": "string", "topics": ["string"], "user_mood": "string", "follow_up": ["string"]
  },
  "memory_candidates": [{
    "title": "string", "content": "string", "tags": ["string"], "confidence": 0.0,
    "sensitive": false, "decision": "approve|candidate|reject", "reason": "string"
  }],
  "persona_growth": {
    "summary": "string", "suggested_overrides": {}, "confidence": 0.0,
    "decision": "approve|candidate|reject", "evidence": ["string"]
  }
}
没有合适内容时数组为空，suggested_overrides 为空对象。"""
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise LLMUnavailableError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must be configured")
    body = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"messages": messages}, ensure_ascii=False)},
        ],
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.RequestError as exc:
        raise LLMUnavailableError(f"LLM request unavailable: {type(exc).__name__}") from exc
    if _is_retryable_status(response.status_code):
        raise LLMUnavailableError(f"LLM API temporarily unavailable: HTTP {response.status_code}")
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM response has no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("LLM response has no text content")
    return _extract_json(content)
