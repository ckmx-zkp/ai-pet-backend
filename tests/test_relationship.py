"""宠物-主人关系读写，以及 worker 回写。"""

from collections.abc import AsyncIterator
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

import agent_worker.tasks as worker_tasks
from pet_common.db import get_session
from pet_common.models import AnalysisResult, Device, PersonaProfile
from test_devices import auth_headers
from web_api.main import create_app
from web_api.routers import persona as persona_router
from web_api.routers import profiles as profiles_router


class FakeSession:
    def __init__(self) -> None:
        self.device = Device(
            id=1,
            user_id=1,
            device_uid="aa:bb:cc:dd:ee:ff",
            binding_id="binding-aabbccddeeff001122334455",
            capabilities={},
        )
        self.profile = PersonaProfile(
            user_id=1,
            device_id=1,
            sun_sign="pisces",
            mbti="INFP",
            follow_latest=True,
            overrides={},
            dossier={},
            bond={},
        )
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

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
        return store.device

    async def fake_get_profile(session: AsyncSession, device_id: int) -> PersonaProfile | None:
        return store.profile

    async def fake_get_owner(session: AsyncSession, user_id: int) -> None:
        return None

    monkeypatch.setattr(persona_router, "_get_own_device", fake_get_own_device)
    monkeypatch.setattr(persona_router, "get_profile", fake_get_profile)
    monkeypatch.setattr(profiles_router, "_get_own_device", fake_get_own_device)
    monkeypatch.setattr(profiles_router, "get_profile", fake_get_profile)
    monkeypatch.setattr(profiles_router, "get_owner_profile", fake_get_owner)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, store)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_put_relationship_sets_beloved_child(client: TestClient, store: FakeSession) -> None:
    response = client.put(
        "/api/devices/1/relationship",
        json={"kind": "爱子", "summary": "惯着你"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "beloved_child"
    assert body["label"] == "爱子"
    assert body["source"] == "manual"
    assert store.profile.bond["kind"] == "beloved_child"


def test_put_relationship_rejects_unknown_kind(client: TestClient) -> None:
    response = client.put(
        "/api/devices/1/relationship",
        json={"kind": "boss"},
        headers=auth_headers(),
    )
    assert response.status_code == 422


def test_get_profiles_separates_owner_and_pet(client: TestClient, store: FakeSession) -> None:
    store.profile.bond = {
        "kind": "love_hate",
        "label": "相爱相杀",
        "summary": "拌嘴",
        "source": "worker",
        "confidence": 0.9,
        "updated_at": "2026-08-18T00:00:00+00:00",
    }
    response = client.get("/api/devices/1/profiles", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["owner"] is None
    assert body["pet"]["subject"] == "pet"
    assert body["pet"]["bond"]["kind"] == "love_hate"
    assert body["relationship"]["label"] == "相爱相杀"


def test_apply_relationship_writes_analysis_and_bond() -> None:
    store = FakeSession()
    worker_tasks._apply_relationship(
        cast(AsyncSession, store),
        1,
        store.profile,
        {
            "kind": "partner",
            "summary": "互相依靠",
            "confidence": 0.88,
            "decision": "approve",
            "evidence": ["说想你"],
        },
        trigger="session",
    )
    assert store.profile.bond["kind"] == "partner"
    assert store.profile.bond["label"] == "情感伴侣"
    updates = [obj for obj in store.added if isinstance(obj, AnalysisResult)]
    assert updates[0].kind == "relationship_update"
    assert updates[0].payload["applied"] is True


def test_apply_relationship_hold_does_not_overwrite() -> None:
    store = FakeSession()
    store.profile.bond = {"kind": "beloved_child", "label": "爱子", "summary": "黏"}
    worker_tasks._apply_relationship(
        cast(AsyncSession, store),
        1,
        store.profile,
        {"kind": "rebellious_child", "confidence": 0.5, "decision": "hold"},
        trigger="memory",
    )
    assert store.profile.bond["kind"] == "beloved_child"
    updates = [obj for obj in store.added if isinstance(obj, AnalysisResult)]
    assert updates[0].payload["applied"] is False
