"""Memory MCP server（官方 Python MCP SDK，stdio 传输）。

工具签名先行，实现返回 not_implemented，待 Epic A 后续任务接入 memories 表。
红线：memory.add 默认 status=candidate（source=agent）；memory.forget 软删并写 audit_logs。
"""

from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from sqlalchemy import or_, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from pet_common.config import get_settings
from pet_common.db import get_session_factory
from pet_common.logging import configure_logging
from pet_common.models import AuditLog, Device, Memory

settings = get_settings()
mcp = FastMCP(
    "memory-mcp",
    host=settings.memory_mcp_host,
    port=settings.memory_mcp_port,
    stateless_http=True,
    json_response=True,
)


async def _find_device(session: Any, device_uid: str) -> Device | None:
    result: Device | None = await session.scalar(
        select(Device).where(Device.device_uid == device_uid.strip().lower())
    )
    return result


class InternalTokenMiddleware(BaseHTTPMiddleware):
    """Keep the HTTP MCP endpoint service-to-service only."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if request.headers.get("X-Internal-Token") != get_settings().internal_service_token:
            return JSONResponse(status_code=401, content={"detail": "invalid internal token"})
        return await call_next(request)


@mcp.tool(name="memory.search", description="按设备检索长期记忆（docs/05）")
async def memory_search(
    device_uid: str,
    query: str,
    tags: list[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """按 device + query/tags 检索记忆；可吃 KB 的 retrieval_hints。

    仅检索 status=active 的记忆（除非显式指定）；强制 limit 上限。
    """
    bounded_limit = max(1, min(limit, 20))
    async with get_session_factory()() as session:
        device = await _find_device(session, device_uid)
        if device is None or device.user_id is None:
            return {"items": []}
        statement = select(Memory).where(Memory.device_id == device.id, Memory.status == "active")
        if query.strip():
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(Memory.title.ilike(pattern), Memory.content.ilike(pattern))
            )
        if tags:
            statement = statement.where(Memory.tags.overlap(tags[:20]))
        rows = (
            (
                await session.execute(
                    statement.order_by(Memory.updated_at.desc()).limit(bounded_limit)
                )
            )
            .scalars()
            .all()
        )
    return {
        "items": [
            {"id": row.id, "title": row.title, "content": row.content, "tags": row.tags}
            for row in rows
        ]
    }


@mcp.tool(name="memory.add", description="新增记忆，默认 candidate 待人审（docs/05）")
async def memory_add(
    device_uid: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    status: str = "candidate",
) -> dict[str, Any]:
    """新增记忆：source=agent，默认 status=candidate，人审后才 active。"""
    async with get_session_factory()() as session:
        device = await _find_device(session, device_uid)
        if device is None or device.user_id is None:
            return {"status": "not_found"}
        # Agent may only create candidates: it must not bypass the approval boundary.
        row = Memory(
            device_id=device.id,
            user_id=device.user_id,
            title=title[:200],
            content=content[:4000],
            tags=(tags or [])[:20],
            source="agent",
            status="candidate" if status != "candidate" else status,
        )
        session.add(row)
        await session.flush()
        memory_id = row.id
        session.add(
            AuditLog(
                actor="service:memory-mcp",
                action="memory_mcp_add",
                target_type="memory",
                target_id=str(memory_id),
                detail={},
            )
        )
        await session.commit()
    return {"status": "candidate", "id": memory_id}


@mcp.tool(name="memory.forget", description="遗忘记忆：软删/归档并写审计（docs/05）")
async def memory_forget(device_uid: str, memory_id: int) -> dict[str, Any]:
    """软删/归档记忆（status=archived），必须写 audit_logs。"""
    async with get_session_factory()() as session:
        device = await _find_device(session, device_uid)
        if device is None or device.user_id is None:
            return {"status": "not_found"}
        row = await session.scalar(
            select(Memory).where(Memory.id == memory_id, Memory.device_id == device.id)
        )
        if row is None:
            return {"status": "not_found"}
        row.status = "archived"
        session.add(
            AuditLog(
                actor="service:memory-mcp",
                action="memory_mcp_forget",
                target_type="memory",
                target_id=str(row.id),
                detail={},
            )
        )
        await session.commit()
    return {"status": "archived", "id": memory_id}


def main() -> None:
    configure_logging(service="memory-mcp", level=settings.log_level)
    if settings.memory_mcp_transport == "stdio":
        mcp.run(transport="stdio")
        return
    if settings.memory_mcp_transport != "streamable-http":
        raise ValueError("MEMORY_MCP_TRANSPORT must be stdio or streamable-http")
    app = mcp.streamable_http_app()
    app.add_middleware(InternalTokenMiddleware)
    uvicorn.run(app, host=settings.memory_mcp_host, port=settings.memory_mcp_port)


if __name__ == "__main__":
    main()
