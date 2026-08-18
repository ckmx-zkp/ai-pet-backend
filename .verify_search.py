"""临时验证脚本：用仓库新版 llm.py 的真实 generate_sign_fortunes 全流程验证检索触发。

新代码经 docker cp 挂到容器 /tmp，importlib 加载；不改动容器内既有代码。
只打印 HTTP 状态/请求 tool_choice/响应块类型/解析结果键名，不打印密钥。
"""
import asyncio
import importlib.util
from datetime import date

import httpx

from pet_common.config import get_settings

spec = importlib.util.spec_from_file_location("llm_new", "/tmp/llm_new.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

settings = get_settings()
object.__setattr__(settings, "fortune_search_enabled", True)
object.__setattr__(settings, "fortune_search_model", "MiniMax-M3")

seen = {}
orig_post = httpx.AsyncClient.post


async def spy_post(self, url, **kwargs):
    resp = await orig_post(self, url, **kwargs)
    data = resp.json()
    body = kwargs.get("json", {})
    seen["url"] = str(url)
    seen["status"] = resp.status_code
    seen["tool_choice"] = body.get("tool_choice")
    seen["model"] = body.get("model")
    seen["stop"] = data.get("stop_reason")
    content = data.get("content")
    seen["blocks"] = [b.get("type") for b in content] if isinstance(content, list) else None
    return resp


httpx.AsyncClient.post = spy_post

result = asyncio.run(mod.generate_sign_fortunes(settings, date.today()))
print("url=", seen["url"])
print("http_status=", seen["status"])
print("model=", seen["model"])
print("request_tool_choice=", seen["tool_choice"])
print("stop_reason=", seen["stop"])
print("response_blocks=", seen["blocks"])
print("search_used=", bool(seen["blocks"]) and any(
    t in ("server_tool_use", "web_search_tool_result") for t in seen["blocks"]))
print("result_keys=", sorted(result.keys()))
signs = result.get("signs", {})
print("signs_count=", len(signs), "| has_metaphysics=", bool(result.get("metaphysics")))
