"""日志中间件：为每个请求注入 trace_id，并透传 device/session/kb 上下文字段。

固定字段（docs/08 §4）：ts/level/service/trace_id/device_id/session_id/kb_version。
trace_id 由本中间件生成（uuid4 hex），写入响应头 X-Trace-Id，供三服务串联。
device_id/session_id/kb_version 若请求头携带（X-Device-Id 等）则绑定进日志上下文。
"""

from uuid import uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from pet_common.logging import get_logger


class TraceLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        # 可选上下文字段：由网内调用方（xiaozhi-server 等）透传
        for header, field in (
            ("x-device-id", "device_id"),
            ("x-session-id", "session_id"),
            ("x-kb-version", "kb_version"),
        ):
            value = request.headers.get(header)
            if value:
                structlog.contextvars.bind_contextvars(**{field: value})

        log = get_logger()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response
