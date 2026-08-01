"""消息历史路由：仅返回脱敏内容、分页与受限删除审计。"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import AuditLog, ChatMessage, Device
from test_devices import auth_headers
from web_api.main import create_app
from web_api.routers import messages as messages_router


class FakeSession:
    def __init__(self) -> None:
        self.device = Device(
            id=1,
            user_id=1,
            device_uid="aa:bb:cc:dd:ee:ff",
            binding_id="binding-aabbccddeeff001122334455",
            capabilities={},
        )
        self.audit_logs: list[AuditLog] = []
        self.deleted: tuple[int, datetime | None, datetime | None] | None = None

    def add(self, obj: object) -> None:
        if isinstance(obj, AuditLog):
            self.audit_logs.append(obj)

    async def commit(self) -> None:
        pass


@pytest.fixture
def store() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(store: FakeSession, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_get_own_device(session: AsyncSession, device_id: int, user_id: int) -> Device:
        assert cast(object, session) is store
        assert (device_id, user_id) == (1, 1)
        return store.device

    async def fake_list_messages(
        session: AsyncSession,
        device_id: int,
        from_: datetime | None,
        to: datetime | None,
        limit: int,
        offset: int,
    ) -> list[ChatMessage]:
        assert cast(object, session) is store
        assert (device_id, limit, offset) == (1, 20, 0)
        return [
            ChatMessage(
                id=9,
                session_id=7,
                device_id=1,
                role="user",
                content_redacted="手机号是[已脱敏:手机号]",
                created_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        ]

    async def fake_delete_messages(
        session: AsyncSession, device_id: int, from_: datetime | None, to: datetime | None
    ) -> int:
        assert cast(object, session) is store
        store.deleted = (device_id, from_, to)
        return 2

    monkeypatch.setattr(messages_router, "_get_own_device", fake_get_own_device)
    monkeypatch.setattr(messages_router, "_list_messages", fake_list_messages)
    monkeypatch.setattr(messages_router, "_delete_messages", fake_delete_messages)
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, store)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_list_messages_returns_redacted_content(client: TestClient) -> None:
    response = client.get("/api/devices/1/messages", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()[0]["content_redacted"] == "手机号是[已脱敏:手机号]"


def test_delete_messages_requires_time_filter(client: TestClient) -> None:
    assert client.delete("/api/devices/1/messages", headers=auth_headers()).status_code == 422


def test_delete_messages_writes_audit_log(client: TestClient, store: FakeSession) -> None:
    response = client.delete(
        "/api/devices/1/messages?from=2026-08-01T00:00:00Z", headers=auth_headers()
    )
    assert response.status_code == 204
    assert store.deleted is not None
    assert store.audit_logs[0].action == "messages_delete"
    assert store.audit_logs[0].detail["deleted_count"] == 2
