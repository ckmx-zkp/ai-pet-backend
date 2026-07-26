"""Memory MCP server（官方 Python MCP SDK，stdio 传输）。

工具签名先行，实现返回 not_implemented，待 Epic A 后续任务接入 memories 表。
红线：memory.add 默认 status=candidate（source=agent）；memory.forget 软删并写 audit_logs。
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from pet_common.config import get_settings
from pet_common.logging import configure_logging

mcp = FastMCP("memory-mcp")

_NOT_IMPLEMENTED: dict[str, str] = {"status": "not_implemented"}


@mcp.tool(name="memory.search", description="按设备检索长期记忆（docs/05）")
async def memory_search(
    device_id: int,
    query: str,
    tags: list[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """按 device + query/tags 检索记忆；可吃 KB 的 retrieval_hints。

    仅检索 status=active 的记忆（除非显式指定）；强制 limit 上限。
    """
    _ = (device_id, query, tags, limit)
    return _NOT_IMPLEMENTED


@mcp.tool(name="memory.add", description="新增记忆，默认 candidate 待人审（docs/05）")
async def memory_add(
    device_id: int,
    title: str,
    content: str,
    tags: list[str] | None = None,
    status: str = "candidate",
) -> dict[str, Any]:
    """新增记忆：source=agent，默认 status=candidate，人审后才 active。"""
    _ = (device_id, title, content, tags, status)
    return _NOT_IMPLEMENTED


@mcp.tool(name="memory.forget", description="遗忘记忆：软删/归档并写审计（docs/05）")
async def memory_forget(device_id: int, memory_id: int) -> dict[str, Any]:
    """软删/归档记忆（status=archived），必须写 audit_logs。"""
    _ = (device_id, memory_id)
    return _NOT_IMPLEMENTED


def main() -> None:
    settings = get_settings()
    configure_logging(service="memory-mcp", level=settings.log_level)
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
