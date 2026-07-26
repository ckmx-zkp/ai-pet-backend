"""FastAPI 应用工厂。路由前缀 /api，路径契约见 docs/06。"""

from fastapi import Depends, FastAPI

from pet_common.config import get_settings
from pet_common.logging import configure_logging
from web_api.deps import get_current_claims, require_admin, require_internal_token
from web_api.middleware import TraceLoggingMiddleware
from web_api.routers import (
    admin,
    analyses,
    auth,
    devices,
    internal,
    memories,
    messages,
    peripheral,
    persona,
)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(service=settings.service_name, level=settings.log_level)

    app = FastAPI(title="ai-pet-backend web-api", version="0.1.0")
    app.add_middleware(TraceLoggingMiddleware)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # 用户侧路由：JWT 鉴权
    user_dep = [Depends(get_current_claims)]
    app.include_router(auth.router, prefix="/api")
    app.include_router(devices.router, prefix="/api", dependencies=user_dep)
    app.include_router(persona.router, prefix="/api", dependencies=user_dep)
    app.include_router(messages.router, prefix="/api", dependencies=user_dep)
    app.include_router(memories.router, prefix="/api", dependencies=user_dep)
    app.include_router(analyses.router, prefix="/api", dependencies=user_dep)
    app.include_router(peripheral.router, prefix="/api", dependencies=user_dep)

    # 管理台路由：JWT + admin 角色
    app.include_router(admin.router, prefix="/api", dependencies=[Depends(require_admin)])

    # 服务间路由：内部 token，挂 /internal 前缀（/api/internal/*）
    app.include_router(
        internal.router, prefix="/api", dependencies=[Depends(require_internal_token)]
    )

    return app


app = create_app()
