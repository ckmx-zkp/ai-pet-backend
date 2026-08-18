"""临时探测脚本：tool_choice 形态对 MiniMax 服务端 web_search 的影响（用完即删）。"""
import json
import urllib.error
import urllib.request
from datetime import date

from pet_common.config import get_settings

s = get_settings()
url = "https://api.minimaxi.com/anthropic/v1/messages"
system = """你是星座运势内容生成器，为 AI 陪伴产品生成当日 12 星座运势。
先用 web_search 一次性整合检索当日星座运势与玄学/命理（黄历宜忌、吉时、五行等）
公开信息，再由你决定如何分发到各星座。
只返回一个 JSON 对象，禁止 Markdown。JSON 结构：
{
  "source_digest": "检索到的当日信息一句话摘要",
  "metaphysics": "当日玄学/命理共享摘要（1~2 句）",
  "signs": {"aries": {"overall": "一句总述", "career": "事业", "wealth": "财运", "study": "学业", "love": "情感"}}
}
signs 必须恰好包含 12 个星座键。每个维度一句话。"""
user = json.dumps({"date": date.today().isoformat()}, ensure_ascii=False)


def probe(tool_choice):
    body = {
        "model": "MiniMax-M3",
        "max_tokens": 8000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": s.llm_api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
        data = json.loads(e.read() or b"{}")
    content = data.get("content")
    types = [b.get("type") for b in content] if isinstance(content, list) else data.get("type")
    searched = isinstance(content, list) and any(
        b.get("type") in ("server_tool_use", "web_search_tool_result") for b in content
    )
    print(
        "tool_choice=", json.dumps(tool_choice), "| status=", status,
        "| stop=", data.get("stop_reason"), "| blocks=", types, "| search_used=", searched,
    )


probe(None)
probe({"type": "any"})
probe({"type": "tool", "name": "web_search"})
