"""隔离联调服务入口，复用内部鉴权；不加载业务路由或运行迁移。"""

from fastapi import Depends, FastAPI

from web_api.deps import require_internal_token
from web_api.routers.social_test import router

app = FastAPI(title="AI Pet 单机社交联调")
app.include_router(router, prefix="/api", dependencies=[Depends(require_internal_token)])


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "mode": "social_test_only"}
