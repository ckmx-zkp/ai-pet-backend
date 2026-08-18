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

from pet_common.bond import kind_prompt_block, kind_union
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
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    memories: list[dict[str, str]] | None = None,
    current_bond: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """会话结束后的离线分析：摘要 + 记忆候选 + 人设成长 + 相处关系。"""
    system = """你是 AI 陪伴产品的离线分析器。输入为已脱敏会话，以及可选的已确认记忆与当前相处关系。
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
  },
  "relationship": {
    "kind": "KIND_UNION",
    "summary": "不超过80字，描述这对主人和宠物此刻怎么相处",
    "confidence": 0.0,
    "decision": "approve|hold",
    "evidence": ["从对话或记忆摘的一句"]
  },
  "kb_feedback": {
    "kb_kind": "sign|mbti|element|",
    "key": "string",
    "parent_key": "string",
    "suggestion": "string",
    "draft_payload": {"prompt_fragments": ["string"]},
    "reason": "string"
  }
}
GLOSSARY
证据不足或只是单次玩笑时 decision=hold，不要因为一句气话就改成逆子。
没有合适内容时数组为空，suggested_overrides 为空对象。
kb_feedback 仅在对话反复暴露同一条可复用的沟通风格偏差时给出，否则为 null。
draft_payload 必须是宠物第一人称短句，不得包含主人原话或敏感属性。"""
    system = system.replace("KIND_UNION", kind_union()).replace("GLOSSARY", kind_prompt_block())
    return await _chat_json(
        settings,
        system,
        json.dumps(
            {
                "messages": messages,
                "memories": memories or [],
                "current_bond": current_bond or {},
            },
            ensure_ascii=False,
        ),
    )


def _web_search_evidence(blocks: list[object]) -> tuple[bool, str]:
    """从 Anthropic content 块提取是否真正检索，以及可供二次生成的摘要。

    只收检索词、来源标题和模型正文；不收录结果页正文，避免把长网页送进二次
    生成或日志。无检索块视为未执行。
    """
    executed = False
    queries: list[str] = []
    titles: list[str] = []
    texts: list[str] = []
    for raw in blocks:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("type")
        if kind in {"server_tool_use", "web_search_tool_result"}:
            executed = True
        if kind == "server_tool_use" and raw.get("name") == "web_search":
            inp = raw.get("input")
            if isinstance(inp, dict):
                query = inp.get("query")
                if isinstance(query, str) and query.strip():
                    queries.append(query.strip()[:80])
        if kind == "web_search_tool_result":
            content = raw.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        title = item.get("title")
                        if isinstance(title, str) and title.strip():
                            titles.append(title.strip()[:80])
        if kind == "text":
            text = raw.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    parts: list[str] = []
    if texts:
        parts.append(" ".join(texts)[:800])
    if titles:
        parts.append("来源：" + "；".join(titles[:8]))
    if queries:
        parts.append("检索词：" + "；".join(queries[:4]))
    return executed, " ".join(parts).strip()[:1500]


async def _web_search_digest(settings: Settings, query: str) -> str:
    """MiniMax Anthropic Messages API + 服务端 web_search，只做检索摘要。

    服务端工具仅该端点支持。检索本身不要求旗舰模型：官方示例只需声明
    web_search_20250305，由供应商执行搜索。M2.5 会把该工具降级为客户端
    tool_use（不执行），故搜索模型走 settings.fortune_search_model。
    请求刻意不要求 JSON、不带 tool_choice：与官方示例一致。线上回归表明
    「同一次请求既检索又输出 12 星座 JSON」会导致模型跳过检索或截断 JSON。
    响应未出现 server_tool_use/web_search_tool_result 块仍视为检索未执行，抛
    LLMUnavailableError 走延迟重试——不静默降级为纯生成。
    """
    if not settings.llm_base_url or not settings.llm_api_key:
        raise LLMUnavailableError("LLM_BASE_URL and LLM_API_KEY must be configured")
    base = settings.llm_base_url.rstrip("/")
    # OpenAI 兼容端点（.../v1）与 Anthropic 端点（.../anthropic）同源派生
    anthropic_base = f"{base[:-3]}/anthropic" if base.endswith("/v1") else f"{base}/anthropic"
    body = {
        "model": settings.fortune_search_model or settings.llm_model,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": query}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }
    headers = {
        "x-api-key": settings.llm_api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    # 服务端检索在单次请求内完成，耗时显著长于普通生成，超时下限放宽到 60s
    timeout = max(settings.llm_timeout_seconds, 60.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{anthropic_base}/v1/messages", headers=headers, json=body
            )
    except httpx.RequestError as exc:
        raise LLMUnavailableError(f"LLM request unavailable: {type(exc).__name__}") from exc
    if _is_retryable_status(response.status_code):
        raise LLMUnavailableError(f"LLM API temporarily unavailable: HTTP {response.status_code}")
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise ValueError("LLM response has no content blocks")
    executed, digest = _web_search_evidence(blocks)
    if not executed:
        raise LLMUnavailableError("web search was not executed by the provider")
    if not digest:
        raise LLMUnavailableError("web search returned no usable digest")
    return digest


async def generate_sign_fortunes(settings: Settings, fortune_date: date) -> dict[str, Any]:
    """生成 12 星座当日四维度运势 + 共享玄学段（E10 L1 层）。

    fortune_search_enabled=true 时分两步：先用 fortune_search_model（须能执行
    服务端 web_search，现网仅 MiniMax-M3）做整合检索摘要，再用 llm_model 按
    摘要分发 12 星座 JSON。关闭时纯 LLM 按星象常识生成，source_digest 由
    prompt 与调用方双重保证标注“非实时检索”（docs/12 §4）。
    """
    sign_list = ", ".join(SIGN_KEYS)
    if settings.fortune_search_enabled:
        search_query = (
            f"请搜索 {fortune_date.isoformat()} 当日公开的十二星座运势、"
            "黄历宜忌、吉时、五行等信息，用 3 到 6 句话汇总关键事实。"
            "不要编写各星座完整运势，不要输出 JSON。"
        )
        digest = await _web_search_digest(settings, search_query)
        system = f"""你是星座运势内容生成器，为 AI 陪伴产品生成当日 12 星座运势。
输入是已联网检索到的当日信息，必须基于这些信息分发到各星座，不得忽略检索结果。
source_digest 必须以“已联网检索”开头并概括检索要点。
只返回一个 JSON 对象，禁止 Markdown。JSON 结构：
{{
  "source_digest": "已联网检索：当日信息一句话摘要（不含链接正文）",
  "metaphysics": "当日玄学/命理共享摘要（黄历宜忌、吉时、五行等，1~2 句）",
  "signs": {{
    "aries": {{"overall": "一句总述", "career": "事业", "wealth": "财运",
      "study": "学业", "love": "情感"}},
    ...其余 11 星座同构...
  }}
}}
signs 必须恰好包含这 12 个键：{sign_list}。每个维度一句话，语气温和积极，
不做医疗/投资建议，不做宿命论断。"""
        user = json.dumps(
            {"date": fortune_date.isoformat(), "search_digest": digest},
            ensure_ascii=False,
        )
        return await _chat_json(settings, system, user)

    sign_list_note = (
        "当前无联网检索能力，按星象常识生成；source_digest 必须注明“非实时检索”。"
    )
    system = f"""你是星座运势内容生成器，为 AI 陪伴产品生成当日 12 星座运势。{sign_list_note}
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


async def generate_memory_profile(
    settings: Settings, memories: list[dict[str, Any]], reason: str
) -> dict[str, Any]:
    """根据已确认记忆生成可展示的画像卡片（E6.1）。"""
    system = """你是 AI 陪伴产品的记忆画像器。输入仅为已确认（active）记忆。
只返回一个 JSON 对象，禁止 Markdown。不得推断疾病、性取向、精确住址或未提供的敏感属性。
JSON 结构：
{
  "remembered": [{"title": "string", "summary": "一句话", "tags": ["string"]}],
  "companion_impact": "这些记忆应如何影响陪伴，1~2 句",
  "relationship": {
    "kind": "KIND_UNION",
    "summary": "不超过80字",
    "confidence": 0.0,
    "decision": "approve|hold",
    "evidence": ["一句记忆证据"]
  }
}
remembered 最多 8 条，summary 不超过 80 字。没有记忆时 remembered 为空数组，
companion_impact 说明暂无已确认记忆。关系证据不足时 decision=hold。
GLOSSARY"""
    system = system.replace("KIND_UNION", kind_union()).replace("GLOSSARY", kind_prompt_block())
    return await _chat_json(
        settings,
        system,
        json.dumps({"reason": reason, "memories": memories}, ensure_ascii=False),
    )


async def generate_fun_quiz(settings: Settings, kind: str, quiz_date: date) -> dict[str, Any]:
    """生成一套 ≤20 题的趣味测验（计分规则一并返回，提交时不再调模型）。"""
    kind_zh = {"psychology": "心理", "astrology": "星座气场", "metaphysics": "玄学宜忌"}.get(
        kind, kind
    )
    system = f"""你是趣味小测试出题人，为 AI 陪伴 App 出一套{kind_zh}向测验。
只返回 JSON，禁止 Markdown。题量 6～12 题（最多 20）。必须是娱乐向，不得诊断疾病、
不得询问真实生日/身份证/住址。JSON：
{{
  "title": "不超过16字",
  "subtitle": "不超过24字",
  "questions": [
    {{"id": "q1", "prompt": "题干", "options": [
      {{"key": "a", "text": "选项", "scores": {{"alpha": 2, "beta": 0}}}},
      {{"key": "b", "text": "选项", "scores": {{"alpha": 0, "beta": 2}}}}
    ]}}
  ],
  "archetypes": {{
    "alpha": {{"title": "结果名", "summary": "一句话", "share_line": "适合发朋友圈的一句"}},
    "beta": {{"title": "结果名", "summary": "一句话", "share_line": "适合发朋友圈的一句"}}
  }}
}}
每题 2～4 个选项，key 用 a/b/c/d。scores 的键必须覆盖全部 archetype。"""
    return await _chat_json(
        settings,
        system,
        json.dumps({"date": quiz_date.isoformat(), "kind": kind}, ensure_ascii=False),
    )


async def generate_device_daily_content(
    settings: Settings, context: dict[str, Any]
) -> dict[str, Any]:
    """生成设备级当日内容：greeting（恒产）与 bazi_fortune（有八字时，四维度）。"""
    system = """你是 AI 陪伴宠物的每日内容生成器。输入含该设备宠物人设（口吻）、
主人太阳星座/MBTI（可能为 null）、近期摘要、已确认记忆、主人星座的当日运势与主人八字排盘。
只返回一个 JSON 对象，禁止 Markdown。JSON 结构：
{
  "greeting": "今天开场素材，1~2 句，宠物口吻，可引主人运势或记忆，勿把主人星座说成自己的",
  "bazi_fortune": {"overall": "一句总述", "career": "事业", "wealth": "财运",
    "study": "学业", "love": "情感"}
}
主人八字为 null 时 bazi_fortune 返回 null。每个维度一句话，语气温和积极，
不做医疗/投资建议，不做宿命论断。"""
    return await _chat_json(settings, system, json.dumps(context, ensure_ascii=False))
