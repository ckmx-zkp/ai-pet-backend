"""主人档案挂用户账号：问卷写 owner，不改宠物人设。"""

from collections.abc import AsyncIterator
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import Device, MBTIKBEntry, OwnerProfile, ZodiacKBEntry
from test_devices import auth_headers
from web_api.main import create_app
from web_api.owner_service import owner_prompt_fragment
from web_api.routers import owner as owner_router
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
        self.owner: OwnerProfile | None = None

    def add(self, obj: object) -> None:
        if isinstance(obj, OwnerProfile):
            self.owner = obj

    async def get(self, model: type[object], ident: object) -> object | None:
        if model is OwnerProfile and ident == 1:
            return self.owner
        return None

    async def commit(self) -> None:
        pass

    async def refresh(self, obj: object) -> None:
        pass


@pytest.fixture
def store() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(store: FakeSession, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_get_own_device(session: AsyncSession, device_id: int, user_id: int) -> Device:
        assert device_id == store.device.id and user_id == store.device.user_id
        return store.device

    async def fake_get_zodiac(
        session: AsyncSession, level: str, key: str, kb_version: int | None
    ) -> ZodiacKBEntry | None:
        if level == "sign" and key == "pisces":
            return ZodiacKBEntry(
                level="sign",
                key="pisces",
                parent_key="water",
                version=1,
                status="published",
                payload={},
            )
        return None

    async def fake_get_mbti(
        session: AsyncSession, key: str, kb_version: int | None
    ) -> MBTIKBEntry | None:
        if key in {"INFP", "ESTJ"}:
            return MBTIKBEntry(key=key, version=1, status="published", payload={})
        return None

    monkeypatch.setattr(persona_router, "_get_own_device", fake_get_own_device)
    monkeypatch.setattr(owner_router, "get_zodiac_entry", fake_get_zodiac)
    monkeypatch.setattr(owner_router, "get_mbti_entry", fake_get_mbti)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, store)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_get_owner_not_configured(client: TestClient) -> None:
    assert client.get("/api/owner", headers=auth_headers()).status_code == 404


def test_owner_questionnaire_roundtrip(client: TestClient, store: FakeSession) -> None:
    listed = client.get("/api/owner/questionnaire", headers=auth_headers())
    assert listed.status_code == 200
    assert listed.json()["subject"] == "owner"
    assert listed.json()["answers_required"] == 20

    response = client.post(
        "/api/owner/questionnaire",
        json={"answers": ["b"] * 20, "sun_sign": "pisces"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["mbti"] == "INFP"
    assert response.json()["sun_sign"] == "pisces"
    assert store.owner is not None
    assert store.owner.mbti == "INFP"

    fetched = client.get("/api/owner", headers=auth_headers())
    assert fetched.status_code == 200
    assert fetched.json()["mbti"] == "INFP"


def test_put_owner_sets_mbti(client: TestClient, store: FakeSession) -> None:
    response = client.put("/api/owner", json={"mbti": "infp"}, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["mbti"] == "INFP"
    assert store.owner is not None


def test_owner_prompt_fragment_marks_owner_not_pet() -> None:
    owner = OwnerProfile(
        user_id=1,
        sun_sign="capricorn",
        mbti="INFP",
        quiz_results={"psychology": {"title": "太阳充电"}},
    )
    line = owner_prompt_fragment(owner)
    assert line is not None
    assert line.startswith("这些是主人的事")
    assert "摩羯座" in line
    assert "INFP" in line
    assert "太阳充电" in line
