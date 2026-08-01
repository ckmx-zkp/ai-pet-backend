"""devices 路由测试（FakeSession + dependency_overrides + monkeypatch，同 test_auth 风格）。

覆盖：绑定成功、重复绑定 409（含他人绑定中设备不可抢）、列表只返回自己的设备、
详情/改名/解绑越权 404、改名、解绑置空 user_id（行与历史保留）、解绑后列表消失、
解绑后设备对任何人不可见、解绑后重绑（含跨用户重绑）、绑定/解绑写审计。
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.config import get_settings
from pet_common.db import get_session
from pet_common.models import AuditLog, Device
from web_api.main import create_app
from web_api.routers import devices as devices_router


class FakeSession:
    """内存版 AsyncSession：只实现 devices 流程用到的 add/flush/commit。"""

    def __init__(self) -> None:
        self.devices: dict[int, Device] = {}
        self.audit_logs: list[AuditLog] = []
        self.next_id = 1

    def add(self, obj: object) -> None:
        if isinstance(obj, Device):
            if obj.id is None:
                obj.id = self.next_id
                self.next_id += 1
            self.devices[obj.id] = obj
        elif isinstance(obj, AuditLog):
            self.audit_logs.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


def make_token(user_id: int, role: str = "user") -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(minutes=30)}
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def auth_headers(user_id: int = 1, role: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(user_id, role)}"}


def bind_device(
    client: TestClient, binding_id: str = "binding-aabbccddeeff001122334455"
) -> Response:
    resp: Response = client.post(
        "/api/devices/bind", json={"binding_id": binding_id}, headers=auth_headers()
    )
    return resp


def seed_device(
    store: FakeSession,
    user_id: int | None = 1,
    device_uid: str = "aa:bb:cc:dd:ee:ff",
    name: str | None = None,
    binding_id: str = "binding-aabbccddeeff001122334455",
) -> Device:
    device = Device(
        user_id=user_id,
        device_uid=device_uid,
        binding_id=binding_id,
        name=name,
        capabilities={},
    )
    store.add(device)
    return device


@pytest.fixture
def store() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(store: FakeSession, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_find_by_binding_id(session: AsyncSession, binding_id: str) -> Device | None:
        assert isinstance(session, FakeSession)
        return next((d for d in session.devices.values() if d.binding_id == binding_id), None)

    async def fake_list_by_user(
        session: AsyncSession, user_id: int, limit: int, offset: int
    ) -> list[Device]:
        assert isinstance(session, FakeSession)
        owned = sorted(
            (d for d in session.devices.values() if d.user_id == user_id), key=lambda d: d.id
        )
        return owned[offset : offset + limit]

    async def fake_get_by_id(session: AsyncSession, device_id: int) -> Device | None:
        assert isinstance(session, FakeSession)
        return session.devices.get(device_id)

    monkeypatch.setattr(devices_router, "_find_device_by_binding_id", fake_find_by_binding_id)
    monkeypatch.setattr(devices_router, "_list_devices_by_user", fake_list_by_user)
    monkeypatch.setattr(devices_router, "_get_device_by_id", fake_get_by_id)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, store)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_bind_success(client: TestClient, store: FakeSession) -> None:
    seed_device(store, user_id=None, name=None)
    resp = client.post(
        "/api/devices/bind",
        json={"binding_id": "binding-aabbccddeeff001122334455", "name": "小白"},
        headers=auth_headers(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["device_uid"] == "aa:bb:cc:dd:ee:ff"
    assert body["name"] == "小白"
    assert body["online"] is False
    assert body["capabilities"] == {}

    device = next(iter(store.devices.values()))
    assert device.user_id == 1
    assert [log.action for log in store.audit_logs] == ["device_bind"]
    assert store.audit_logs[0].actor == "user:1"
    assert store.audit_logs[0].target_type == "device"


def test_bind_duplicate_409(client: TestClient, store: FakeSession) -> None:
    seed_device(store, user_id=None)
    assert bind_device(client).status_code == 201
    # 同一用户重复绑定 409
    assert bind_device(client).status_code == 409
    # 他人无法认领「仍绑定中」的设备：同一 binding_id 仍为 409
    payload = {"binding_id": "binding-aabbccddeeff001122334455"}
    resp = client.post("/api/devices/bind", json=payload, headers=auth_headers(user_id=2))
    assert resp.status_code == 409


def test_list_only_own_devices(client: TestClient, store: FakeSession) -> None:
    seed_device(
        store,
        user_id=2,
        device_uid="11:22:33:44:55:66",
        name="别人的",
        binding_id="binding-112233445566001122334455",
    )
    seed_device(store, user_id=None)
    bind_device(client)

    resp = client.get("/api/devices", headers=auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert item["device_uid"] == "aa:bb:cc:dd:ee:ff"
    assert {"name", "online", "firmware_version", "capabilities"} <= item.keys()

    # 他人视角看不到我的设备
    other = client.get("/api/devices", headers=auth_headers(user_id=3))
    assert other.status_code == 200
    assert other.json() == []


def test_get_device_detail(client: TestClient, store: FakeSession) -> None:
    device = seed_device(store, name="小白")
    resp = client.get(f"/api/devices/{device.id}", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json()["name"] == "小白"


def test_get_device_cross_user_404(client: TestClient, store: FakeSession) -> None:
    device = seed_device(store, user_id=2)
    resp = client.get(f"/api/devices/{device.id}", headers=auth_headers(user_id=1))
    assert resp.status_code == 404  # 越权与不存在同 404，不泄露存在性
    assert client.get("/api/devices/9999", headers=auth_headers(user_id=2)).status_code == 404


def test_rename_device(client: TestClient, store: FakeSession) -> None:
    device = seed_device(store, name="旧名字")
    resp = client.patch(
        f"/api/devices/{device.id}", json={"name": "新名字"}, headers=auth_headers()
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名字"
    assert device.name == "新名字"


def test_rename_cross_user_404(client: TestClient, store: FakeSession) -> None:
    device = seed_device(store, user_id=2, name="别人的")
    resp = client.patch(
        f"/api/devices/{device.id}", json={"name": "改名"}, headers=auth_headers(user_id=1)
    )
    assert resp.status_code == 404
    assert device.name == "别人的"


def test_unbind_device(client: TestClient, store: FakeSession) -> None:
    seed_device(store, user_id=None)
    bind_device(client)
    device = next(iter(store.devices.values()))

    resp = client.delete(f"/api/devices/{device.id}", headers=auth_headers())
    assert resp.status_code == 204

    # 解绑不删行：devices 行仍在、user_id 置 NULL（历史数据因此全部保留）
    assert device.id in store.devices
    assert device.user_id is None
    # 解绑后列表消失
    assert client.get("/api/devices", headers=auth_headers()).json() == []


def test_unbound_device_invisible(client: TestClient, store: FakeSession) -> None:
    seed_device(store, user_id=None)
    bind_device(client)
    device = next(iter(store.devices.values()))
    client.delete(f"/api/devices/{device.id}", headers=auth_headers())

    # 已解绑设备对任何人（含原主）不可见不可操作：详情/改名/再解绑一律 404
    for uid in (1, 2):
        assert client.get(f"/api/devices/{device.id}", headers=auth_headers(uid)).status_code == 404
        resp = client.patch(
            f"/api/devices/{device.id}", json={"name": "x"}, headers=auth_headers(uid)
        )
        assert resp.status_code == 404
        resp = client.delete(f"/api/devices/{device.id}", headers=auth_headers(uid))
        assert resp.status_code == 404


def test_rebind_after_unbind(client: TestClient, store: FakeSession) -> None:
    seed_device(store, user_id=None)
    bind_device(client)
    device = next(iter(store.devices.values()))
    client.delete(f"/api/devices/{device.id}", headers=auth_headers())

    # 解绑后他人以同一 binding_id 重绑：同一行、id 不变、name 可更新
    resp = client.post(
        "/api/devices/bind",
        json={"binding_id": "binding-aabbccddeeff001122334455", "name": "新主人的名字"},
        headers=auth_headers(user_id=2),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == device.id
    assert body["name"] == "新主人的名字"
    assert device.user_id == 2
    assert len(store.devices) == 1  # 未新增行

    # 重绑后归新主：新主列表可见，旧主不可见
    assert len(client.get("/api/devices", headers=auth_headers(user_id=2)).json()) == 1
    assert client.get("/api/devices", headers=auth_headers()).json() == []
    assert [log.action for log in store.audit_logs] == [
        "device_bind",
        "device_unbind",
        "device_bind",
    ]


def test_unbind_writes_audit(client: TestClient, store: FakeSession) -> None:
    seed_device(store, user_id=None)
    bind_device(client)
    device = next(iter(store.devices.values()))
    client.delete(f"/api/devices/{device.id}", headers=auth_headers())

    assert [log.action for log in store.audit_logs] == ["device_bind", "device_unbind"]
    unbind_log = store.audit_logs[1]
    assert unbind_log.actor == "user:1"
    assert unbind_log.target_type == "device"
    assert unbind_log.detail == {"device_uid": "aa:bb:cc:dd:ee:ff"}


def test_unbind_cross_user_404(client: TestClient, store: FakeSession) -> None:
    device = seed_device(store, user_id=2)
    resp = client.delete(f"/api/devices/{device.id}", headers=auth_headers(user_id=1))
    assert resp.status_code == 404
    assert device.user_id == 2  # 仍绑定在原主名下


def test_devices_without_token_401(client: TestClient) -> None:
    assert client.get("/api/devices").status_code == 401
    resp = client.post(
        "/api/devices/bind", json={"binding_id": "binding-aabbccddeeff001122334455"}
    )
    assert resp.status_code == 401


def test_admin_cannot_claim_device(client: TestClient, store: FakeSession) -> None:
    seed_device(store, user_id=None)
    resp = client.post(
        "/api/devices/bind",
        json={"binding_id": "binding-aabbccddeeff001122334455"},
        headers=auth_headers(role="admin"),
    )
    assert resp.status_code == 403
