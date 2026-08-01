"""用户侧分析/外设读取：只允许设备归属用户访问。"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import AnalysisResult, Device, DevicePeripheralState
from test_devices import auth_headers
from web_api.main import create_app
from web_api.routers import analyses as analyses_router
from web_api.routers import peripheral as peripheral_router


class FakeSession:
    def __init__(self) -> None:
        self.device = Device(
            id=1,
            user_id=1,
            device_uid="aa:bb:cc:dd:ee:ff",
            binding_id="binding-aabbccddeeff001122334455",
            capabilities={},
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store = FakeSession()

    async def fake_get_own_device(session: AsyncSession, device_id: int, user_id: int) -> Device:
        assert cast(object, session) is store
        assert (device_id, user_id) == (1, 1)
        return store.device

    async def fake_list_analyses(
        session: AsyncSession, device_id: int, kind: str | None, limit: int, offset: int
    ) -> list[AnalysisResult]:
        assert cast(object, session) is store
        assert (device_id, kind, limit, offset) == (1, "daily_summary", 20, 0)
        return [
            AnalysisResult(
                id=8,
                device_id=1,
                kind="daily_summary",
                payload={"summary": "今天聊得很开心"},
                created_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        ]

    async def fake_get_peripheral_state(
        session: AsyncSession, device_id: int
    ) -> DevicePeripheralState | None:
        assert cast(object, session) is store
        assert device_id == 1
        return DevicePeripheralState(
            device_id=1,
            eye_emotion="happy",
            eye_gaze="center",
            eye_closed=False,
            extra={"battery": 87},
            updated_at=datetime(2026, 8, 2, tzinfo=UTC),
        )

    monkeypatch.setattr(analyses_router, "_get_own_device", fake_get_own_device)
    monkeypatch.setattr(peripheral_router, "_get_own_device", fake_get_own_device)
    monkeypatch.setattr(analyses_router, "_list_analyses", fake_list_analyses)
    monkeypatch.setattr(peripheral_router, "_get_peripheral_state", fake_get_peripheral_state)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, store)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_list_own_analyses(client: TestClient) -> None:
    response = client.get(
        "/api/devices/1/analyses?kind=daily_summary", headers=auth_headers()
    )
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 8,
            "kind": "daily_summary",
            "payload": {"summary": "今天聊得很开心"},
            "created_at": "2026-08-02T00:00:00Z",
        }
    ]


def test_get_own_peripheral(client: TestClient) -> None:
    response = client.get("/api/devices/1/peripheral", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["extra"] == {"battery": 87}
    assert response.json()["eye_emotion"] == "happy"
