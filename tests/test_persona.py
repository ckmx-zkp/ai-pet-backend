"""人设读写路由：归属校验、选择校验与 KB 版本钉扎。"""

from collections.abc import AsyncIterator
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import Device, MBTIKBEntry, PersonaProfile, ZodiacKBEntry
from test_devices import auth_headers
from web_api.main import create_app
from web_api.routers import persona as persona_router


class FakeSession:
    def __init__(self) -> None:
        self.device = Device(
            id=1,
            user_id=1,
            device_uid="aa:bb:cc:dd:ee:ff",
            binding_id="binding-aabbccddeeff001122334455",
            capabilities={},
        )
        self.profile: PersonaProfile | None = None

    def add(self, obj: object) -> None:
        if isinstance(obj, PersonaProfile):
            self.profile = obj

    async def commit(self) -> None:
        pass


@pytest.fixture
def store() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(store: FakeSession, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_get_own_device(session: AsyncSession, device_id: int, user_id: int) -> Device:
        assert isinstance(session, FakeSession)
        if device_id != store.device.id or user_id != store.device.user_id:
            raise AssertionError("unexpected device ownership")
        return store.device

    async def fake_get_profile(session: AsyncSession, device_id: int) -> PersonaProfile | None:
        assert isinstance(session, FakeSession)
        assert device_id == store.device.id
        return store.profile

    async def fake_get_zodiac(
        session: AsyncSession, level: str, key: str, kb_version: int | None
    ) -> ZodiacKBEntry | None:
        assert isinstance(session, FakeSession)
        if level == "sign" and key == "pisces":
            return ZodiacKBEntry(
                level="sign",
                key="pisces",
                parent_key="water",
                version=5,
                status="published",
                payload={},
            )
        if level == "element" and key == "water":
            return ZodiacKBEntry(
                level="element",
                key="water",
                parent_key=None,
                version=3,
                status="published",
                payload={},
            )
        return None

    async def fake_get_mbti(
        session: AsyncSession, key: str, kb_version: int | None
    ) -> MBTIKBEntry | None:
        assert isinstance(session, FakeSession)
        if key == "INFP":
            return MBTIKBEntry(key="INFP", version=4, status="published", payload={})
        return None

    monkeypatch.setattr(persona_router, "_get_own_device", fake_get_own_device)
    monkeypatch.setattr(persona_router, "get_profile", fake_get_profile)
    monkeypatch.setattr(persona_router, "get_zodiac_entry", fake_get_zodiac)
    monkeypatch.setattr(persona_router, "get_mbti_entry", fake_get_mbti)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, store)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_get_persona_not_configured(client: TestClient) -> None:
    assert client.get("/api/devices/1/persona", headers=auth_headers()).status_code == 404


def test_put_persona_and_pin_kb_version(client: TestClient, store: FakeSession) -> None:
    response = client.put(
        "/api/devices/1/persona",
        json={
            "sun_sign": " PISCES ",
            "mbti": "infp",
            "overrides": {"taboo": ["催促"]},
            "follow_latest": False,
        },
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json() == {
        "device_id": 1,
        "sun_sign": "pisces",
        "mbti": "INFP",
        "overrides": {"taboo": ["催促"]},
        "follow_latest": False,
        "kb_version": 5,
    }
    assert store.profile is not None
    assert store.profile.user_id == 1


def test_put_persona_rejects_unseeded_selection(client: TestClient) -> None:
    response = client.put(
        "/api/devices/1/persona",
        json={"sun_sign": "aries", "mbti": "ENTJ"},
        headers=auth_headers(),
    )
    assert response.status_code == 422
