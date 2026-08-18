"""受限的 OpenAI 兼容 LLM 客户端，仅供异步 worker 使用。

调用输入只能来自 ``chat_messages.content_redacted``、已确认记忆/摘要与
E10 运势任务的非对话输入（星座运势生成、八字排盘，docs/12）；不得把原始音频、
未脱敏文本、JWT 或数据库连接信息发送给模型服务。八字生辰属敏感数据，只用于
排盘与运势生成，永不写入日志。
"""

import json
import re
from datetime import date
from typing import Any

import httpx

from pet_common.config import Settings

# 12 星座稳定键（docs/12 §3），顺序固定便于 prompt 与校验。
SIGN_KEYS = (
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
)


class LLMUnavailableError(RuntimeError):
    """部署尚未配置模型服务时，任务应可重试而不是伪造分析结果。"""


def _is_retryable_status(status_code: int) -> bool:
    """模型供应商鉴权、限流或服务端故障可能在配置修复后恢复。"""
    return status_code in {401, 403, 408, 409, 425, 429} or status_code >= 500


def _extract_json(content: str) -> dict[str, Any]:
    """接受纯 JSON 或模型偶发包裹的 Markdown JSON code fence。"""
    # Reasoning-capable OpenAI-compatible models may prepend <think>...</think>
    # despite JSON output requests. Never persist that reasoning in analysis output.
    value = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else ""
        if value.endswith("```"):
            value = value[:-3]
    parsed: object = json.loads(value.strip())
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


async def _chat_json(settings: Settings, system: str, user_content: str) -> dict[str, Any]:
    """请求一次模型并要求返回严格 JSON；调用方负责 schema/业务校验。"""
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise LLMUnavailableError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must be configured")
    body = {
        "model": settings.llm_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
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


async def generate_structured_analysis(
    settings: Settings, messages: list[dict[str, str]]
) -> dict[str, Any]:
    """会话结束后的离线分析：摘要 + 记忆候选 + 人设成长建议。"""
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
    return await _chat_json(
        settings, system, json.dumps({"messages": messages}, ensure_ascii=False)
    )


async def generate_sign_fortunes(settings: Settings, fortune_date: date) -> dict[str, Any]:
    """一次生成 12 星座当日四维度运势（E10 L1 层）。

    联网搜索源未接入（docs/12 §8 待决）：fortune_search_enabled=false 时纯 LLM
    按星象常识生成，source_digest 由 prompt 与调用方双重保证标注"非实时检索"。
    """
    if settings.fortune_search_enabled:
        source_note = "可联网检索当日星象/运势公开信息作为依据，source_digest 概述检索到的信息。"
    else:
        source_note = (
            "当前无联网检索能力，按星象常识生成；source_digest 必须注明“非实时检索”。"
        )
    sign_list = ", ".join(SIGN_KEYS)
    system = f"""你是星座运势内容生成器，为 AI 陪伴产品生成当日 12 星座运势。{source_note}
只返回一个 JSON 对象，禁止 Markdown。JSON 结构：
{{
  "source_digest": "当日信息一句话摘要（便于运营排查，不含链接正文）",
  "signs": {{
    "aries": {{"overall": "一句总述", "career": "事业", "wealth": "财运",
      "study": "学业", "love": "情感"}},
    ...其余 11 星座同构...
  }}
}}
signs 必须恰好包含这 12 个键：{sign_list}。每个维度一句话，语气温和积极，
不做医疗/投资建议，不做宿命论断。"""
    user = json.dumps({"date": fortune_date.isoformat()}, ensure_ascii=False)
    return await _chat_json(settings, system, user)


async def generate_bazi_text(settings: Settings, birth: dict[str, Any]) -> str:
    """按出生信息排四柱八字，返回可缓存的排盘文本（敏感数据，仅 worker 内部使用）。"""
    system = """你是八字排盘器。根据输入的出生信息（公历/农历、出生日期、时辰、地点、性别）
排出四柱八字。只返回一个 JSON 对象，禁止 Markdown：{"bazi_text": "四柱、日主与简要格局"}。
时辰未知时注明“时辰未知”并按无时辰排盘，不得臆造时辰。"""
    result = await _chat_json(settings, system, json.dumps(birth, ensure_ascii=False))
    text = result.get("bazi_text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("LLM bazi chart response missing bazi_text")
    return text.strip()[:1000]


async def generate_device_daily_content(
    settings: Settings, context: dict[str, Any]
) -> dict[str, Any]:
    """生成设备级当日内容：greeting（恒产）与 bazi_fortune（有八字时，四维度）。"""
    system = """你是 AI 陪伴宠物的每日内容生成器。输入为该设备的人设（星座/MBTI/档案）、
近期摘要、已确认记忆、当日星座运势与主人八字排盘（可能为 null）。
只返回一个 JSON 对象，禁止 Markdown。JSON 结构：
{
  "greeting": "今天开场时可以自然提到的素材，1~2 句，人设口吻，自然引用运势或记忆，不堆砌",
  "bazi_fortune": {"overall": "一句总述", "career": "事业", "wealth": "财运",
    "study": "学业", "love": "情感"}
}
主人八字为 null 时 bazi_fortune 返回 null。每个维度一句话，语气温和积极，
不做医疗/投资建议，不做宿命论断。"""
    return await _chat_json(settings, system, json.dumps(context, ensure_ascii=False))
