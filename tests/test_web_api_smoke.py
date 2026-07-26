"""web-api 应用工厂冒烟测试：/healthz 可用、内部路由鉴权生效。"""

from fastapi.testclient import TestClient

from web_api.main import create_app


def test_healthz() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["x-trace-id"]  # 中间件注入 trace_id


def test_internal_requires_token() -> None:
    client = TestClient(create_app())
    resp = client.post("/api/internal/chat/events")
    assert resp.status_code == 401


def test_user_routes_require_jwt() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/devices")
    assert resp.status_code == 401
