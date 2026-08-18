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
            "dossier": {
                "identity": "",
                "background": [],
                "roles": [],
                "goals": [],
                "evolution_rules": [],
                "relationship": "",
            },
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


async def test_compile_profile_prepends_identity_fragment(
    store: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """身份行必须在 KB 风格片段之前，模型才有事实依据承认自己的星座。"""
    from web_api import persona_service

    async def fake_get_zodiac(
        session: AsyncSession, level: str, key: str, kb_version: int | None
    ) -> ZodiacKBEntry | None:
        if level == "sign":
            return ZodiacKBEntry(
                level="sign",
                key="scorpio",
                parent_key="water",
                version=2,
                status="published",
                payload={"prompt_fragments": ["与天蝎风格用户交流时减少表面寒暄。"]},
            )
        return ZodiacKBEntry(
            level="element",
            key="water",
            parent_key=None,
            version=1,
            status="published",
            payload={},
        )

    async def fake_get_mbti(
        session: AsyncSession, key: str, kb_version: int | None
    ) -> MBTIKBEntry | None:
        return MBTIKBEntry(
            key="ENFP",
            version=2,
            status="published",
            payload={"prompt_fragments": ["与 ENFP 风格用户交流时保留自主选择。"]},
        )

    monkeypatch.setattr(persona_service, "get_zodiac_entry", fake_get_zodiac)
    monkeypatch.setattr(persona_service, "get_mbti_entry", fake_get_mbti)

    async def fake_daily_guidance(
        session: AsyncSession, device_id: int, sun_sign: str
    ) -> list[str]:
        return []  # E10 当日内容缺失时不追加引导语，保持既有片段顺序断言

    monkeypatch.setattr(persona_service, "get_daily_guidance", fake_daily_guidance)

    profile = PersonaProfile(
        user_id=1,
        device_id=1,
        sun_sign="scorpio",
        mbti="ENFP",
        follow_latest=True,
        overrides={},
        dossier={},
    )
    pack = await persona_service.compile_profile(cast(AsyncSession, store), profile)
    fragments = pack["system_prompt_fragments"]
    assert fragments[0] == "你的星座是天蝎座，MBTI 是 ENFP；被问到时自然承认，平时不用主动提起。"
    assert fragments[1:] == [
        "与天蝎风格用户交流时减少表面寒暄。",
        "与 ENFP 风格用户交流时保留自主选择。",
    ]


def test_identity_fragment_unknown_sign_falls_back_to_key() -> None:
    from web_api.persona_service import _identity_fragment

    assert _identity_fragment("scorpio", "ENFP").startswith("你的星座是天蝎座")
    assert "unknown-sign" in _identity_fragment("unknown-sign", "INTJ")
