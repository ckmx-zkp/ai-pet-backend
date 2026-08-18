"""internal 路由测试（FakeSession + dependency_overrides + monkeypatch，同 test_devices 风格）。

覆盖：单条/批量 chat events 写入、脱敏生效（入库即替换）、未知设备 404、
session 按 external_session_id（字符串）自动建行与复用、peripheral 覆盖写、
session end 置 ended_at + 入队任务（幂等）、devices/seen 新建（user_id 为空）与更新、
无 token 401。
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.config import get_settings
from pet_common.db import get_session
from pet_common.models import (
    AgentTask,
    ChatMessage,
    ChatSession,
    Device,
    DevicePeripheralState,
)
from web_api.main import create_app
from web_api.routers import internal as internal_router

DEVICE_UID = "aa:bb:cc:dd:ee:ff"
SESSION_ID = "sess-e3-test-001"
TS = "2026-08-01T12:00:00+00:00"


class FakeSession:
    """内存版 AsyncSession：只实现 internal 流程用到的 add/flush/commit。"""

    def __init__(self) -> None:
        self.devices: dict[int, Device] = {}
        self.chat_sessions: dict[int, ChatSession] = {}
        self.chat_messages: list[ChatMessage] = []
        self.peripheral_states: dict[int, DevicePeripheralState] = {}
        self.agent_tasks: list[AgentTask] = []
        self.next_id = 1

    def add(self, obj: object) -> None:
        if isinstance(obj, Device):
            if obj.id is None:
                obj.id = self._alloc()
            self.devices[obj.id] = obj
        elif isinstance(obj, ChatSession):
            if obj.id is None:
                obj.id = self._alloc()
            self.chat_sessions[obj.id] = obj
        elif isinstance(obj, ChatMessage):
            obj.id = self._alloc()
            self.chat_messages.append(obj)
        elif isinstance(obj, DevicePeripheralState):
            self.peripheral_states[obj.device_id] = obj
        elif isinstance(obj, AgentTask):
            obj.id = self._alloc()
            self.agent_tasks.append(obj)

    def _alloc(self) -> int:
        self.next_id += 100
        return self.next_id

    def find_session_by_external_id(self, external_session_id: str) -> ChatSession | None:
        return next(
            (
                s
                for s in self.chat_sessions.values()
                if s.external_session_id == external_session_id
            ),
            None,
        )

    async def execute(self, statement: object) -> "_EmptyResult":
        # E10 懒生成触发（seen / session end）会查 persona 与当日内容；
        # 本 FakeSession 不支撑真实查询，统一返回空 → 视为无人设、不入队。
        return _EmptyResult()

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


class _EmptyResult:
    def scalar_one_or_none(self) -> None:
        return None

    def scalars(self) -> "_EmptyResult":
        return self

    def all(self) -> list[object]:
        return []


def internal_headers() -> dict[str, str]:
    return {"X-Internal-Token": get_settings().internal_service_token}


def seed_device(
    store: FakeSession, device_uid: str = DEVICE_UID, user_id: int | None = 1
) -> Device:
    device = Device(
        user_id=user_id,
        device_uid=device_uid,
        binding_id="binding-aabbccddeeff001122334455",
        capabilities={},
    )
    store.add(device)
    return device


def event(
    session_id: str = SESSION_ID, content: str = "你好呀", device_uid: str = DEVICE_UID
) -> dict[str, object]:
    return {
        "device_uid": device_uid,
        "session_id": session_id,
        "role": "user",
        "content": content,
        "ts": TS,
    }


@pytest.fixture
def store() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(store: FakeSession, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_find_by_uid(session: AsyncSession, device_uid: str) -> Device | None:
        assert isinstance(session, FakeSession)
        return next((d for d in session.devices.values() if d.device_uid == device_uid), None)

    async def fake_find_session_by_external_id(
        session: AsyncSession, external_session_id: str
    ) -> ChatSession | None:
        assert isinstance(session, FakeSession)
        return session.find_session_by_external_id(external_session_id)

    async def fake_get_peripheral_state(
        session: AsyncSession, device_id: int
    ) -> DevicePeripheralState | None:
        assert isinstance(session, FakeSession)
        return session.peripheral_states.get(device_id)

    monkeypatch.setattr(internal_router, "_find_device_by_uid", fake_find_by_uid)
    monkeypatch.setattr(
        internal_router, "_find_chat_session_by_external_id", fake_find_session_by_external_id
    )
    monkeypatch.setattr(internal_router, "_get_peripheral_state", fake_get_peripheral_state)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, store)

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


# ---------- POST /internal/chat/events ----------


def test_chat_event_single_creates_session_and_message(
    client: TestClient, store: FakeSession
) -> None:
    device = seed_device(store)
    resp = client.post("/api/internal/chat/events", json=event(), headers=internal_headers())
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 1}

    # 首次见字符串 session_id 自动建行：external_session_id 落库，user_id 跟随设备归属
    chat_session = store.find_session_by_external_id(SESSION_ID)
    assert chat_session is not None
    assert chat_session.device_id == device.id
    assert chat_session.user_id == 1

    # 消息外键引用内部自增 id（不暴露给小智）
    message = store.chat_messages[0]
    assert message.session_id == chat_session.id
    assert message.device_id == device.id
    assert message.role == "user"
    assert message.content_redacted == "你好呀"
    assert message.created_at == datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    # 设备活跃镜像更新
    assert device.online_at is not None


def test_chat_events_batch_reuses_session(client: TestClient, store: FakeSession) -> None:
    seed_device(store)
    payload = [
        event(session_id="sess-001", content="第一句"),
        event(session_id="sess-001", content="第二句"),
        event(session_id="sess-002", content="另一个会话"),
    ]
    resp = client.post("/api/internal/chat/events", json=payload, headers=internal_headers())
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 3}

    assert len(store.chat_messages) == 3
    # sess-001 只建一次（复用），sess-002 自动建行
    assert {s.external_session_id for s in store.chat_sessions.values()} == {
        "sess-001",
        "sess-002",
    }
    assert [m.content_redacted for m in store.chat_messages] == [
        "第一句",
        "第二句",
        "另一个会话",
    ]


def test_chat_event_redaction_applied_before_store(client: TestClient, store: FakeSession) -> None:
    seed_device(store)
    resp = client.post(
        "/api/internal/chat/events",
        json=event(content="我的手机号是13912345678，邮箱me@example.com"),
        headers=internal_headers(),
    )
    assert resp.status_code == 200
    stored = store.chat_messages[0].content_redacted
    assert stored == "我的手机号是[已脱敏:手机号]，邮箱[已脱敏:邮箱]"
    assert "13912345678" not in stored  # 原文不落库


def test_chat_event_unknown_device_404(client: TestClient, store: FakeSession) -> None:
    resp = client.post(
        "/api/internal/chat/events",
        json=event(device_uid="00:00:00:00:00:00"),
        headers=internal_headers(),
    )
    assert resp.status_code == 404
    assert store.chat_messages == []  # 不部分落库


def test_chat_event_session_of_other_device_404(client: TestClient, store: FakeSession) -> None:
    seed_device(store)
    other = seed_device(store, device_uid="11:22:33:44:55:66")
    store.add(ChatSession(external_session_id=SESSION_ID, device_id=other.id, user_id=2))
    resp = client.post("/api/internal/chat/events", json=event(), headers=internal_headers())
    assert resp.status_code == 404
    assert store.chat_messages == []


# ---------- POST /internal/peripheral/events ----------


def test_peripheral_event_upsert_and_overwrite(client: TestClient, store: FakeSession) -> None:
    device = seed_device(store)
    body = {
        "device_uid": DEVICE_UID,
        "emotion": "happy",
        "gaze": "center",
        "closed": False,
        "extra": {"battery": 87},
    }
    resp = client.post("/api/internal/peripheral/events", json=body, headers=internal_headers())
    assert resp.status_code == 204

    state = store.peripheral_states[device.id]
    assert state.eye_emotion == "happy"
    assert state.eye_gaze == "center"
    assert state.eye_closed is False
    assert state.extra == {"battery": 87}

    # 一设备一行：覆盖写而非新增
    resp = client.post(
        "/api/internal/peripheral/events",
        json={"device_uid": DEVICE_UID, "emotion": "sleepy", "closed": True},
        headers=internal_headers(),
    )
    assert resp.status_code == 204
    assert len(store.peripheral_states) == 1
    assert state.eye_emotion == "sleepy"
    assert state.eye_gaze is None  # 全量覆盖：未提供的字段清掉
    assert state.eye_closed is True
    assert state.extra == {}


def test_peripheral_event_unknown_device_404(client: TestClient, store: FakeSession) -> None:
    resp = client.post(
        "/api/internal/peripheral/events",
        json={"device_uid": DEVICE_UID, "emotion": "happy"},
        headers=internal_headers(),
    )
    assert resp.status_code == 404
    assert store.peripheral_states == {}


# ---------- POST /internal/chat/sessions/{id}/end ----------


def test_end_session_sets_ended_at_and_enqueues_task(
    client: TestClient, store: FakeSession
) -> None:
    device = seed_device(store)
    chat_session = ChatSession(external_session_id=SESSION_ID, device_id=device.id, user_id=1)
    store.add(chat_session)

    resp = client.post(f"/api/internal/chat/sessions/{SESSION_ID}/end", headers=internal_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == SESSION_ID
    assert body["ended"] is True
    assert body["task_id"] is not None

    assert chat_session.ended_at is not None

    assert len(store.agent_tasks) == 1
    task = store.agent_tasks[0]
    assert task.kind == "daily_summary"
    assert task.status == "pending"
    assert task.payload == {
        "session_id": chat_session.id,  # 内部自增 id
        "external_session_id": SESSION_ID,  # xiaozhi 侧字符串会话号
        "device_id": device.id,
    }

    # 幂等：重复 end 不重复入队
    resp = client.post(f"/api/internal/chat/sessions/{SESSION_ID}/end", headers=internal_headers())
    assert resp.status_code == 200
    assert resp.json()["ended"] is False
    assert len(store.agent_tasks) == 1


def test_end_session_unknown_404(client: TestClient, store: FakeSession) -> None:
    resp = client.post("/api/internal/chat/sessions/sess-unknown/end", headers=internal_headers())
    assert resp.status_code == 404


# ---------- POST /internal/devices/seen ----------


def test_device_seen_creates_unclaimed_row(client: TestClient, store: FakeSession) -> None:
    resp = client.post(
        "/api/internal/devices/seen",
        json={
            "device_uid": DEVICE_UID,
            "firmware_version": "1.2.3",
            "capabilities": {"screen": True},
        },
        headers=internal_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    assert body["device_uid"] == DEVICE_UID
    assert len(body["binding_id"]) == 32

    device = store.devices[body["id"]]
    assert device.user_id is None  # 待认领，E1 bind 重绑兼容
    assert device.firmware_version == "1.2.3"
    assert device.capabilities == {"screen": True}
    assert device.online_at is not None


def test_device_seen_updates_existing(client: TestClient, store: FakeSession) -> None:
    device = seed_device(store)
    assert device.online_at is None

    resp = client.post(
        "/api/internal/devices/seen",
        json={"device_uid": DEVICE_UID, "firmware_version": "2.0.0"},
        headers=internal_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is False
    assert body["id"] == device.id
    assert body["binding_id"] == device.binding_id
    assert len(store.devices) == 1  # 不新增行

    assert device.online_at is not None
    assert device.firmware_version == "2.0.0"
    assert device.user_id == 1  # 已认领设备归属不变


def test_device_seen_minimal_body(client: TestClient, store: FakeSession) -> None:
    resp = client.post(
        "/api/internal/devices/seen", json={"device_uid": DEVICE_UID}, headers=internal_headers()
    )
    assert resp.status_code == 200
    device = store.devices[resp.json()["id"]]
    assert device.capabilities == {}
    assert device.firmware_version is None


# ---------- 鉴权 ----------


def test_internal_endpoints_require_token(client: TestClient) -> None:
    assert client.post("/api/internal/chat/events", json=event()).status_code == 401
    assert (
        client.post("/api/internal/peripheral/events", json={"device_uid": DEVICE_UID}).status_code
        == 401
    )
    assert client.post(f"/api/internal/chat/sessions/{SESSION_ID}/end").status_code == 401
    assert (
        client.post("/api/internal/devices/seen", json={"device_uid": DEVICE_UID}).status_code
        == 401
    )


def test_persona_pack_returns_contract_shape(
    client: TestClient, store: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = seed_device(store)
    profile = object()

    async def fake_get_profile(session: AsyncSession, device_id: int) -> object | None:
        assert cast(object, session) is store
        assert device_id == device.id
        return profile

    async def fake_compile_profile(session: AsyncSession, value: object) -> dict[str, object]:
        assert cast(object, session) is store
        assert value is profile
        return {
            "kb_version": 1,
            "system_prompt_fragments": ["温柔陪伴"],
            "style_constraints": ["先共情"],
            "taboo": ["冷暴力"],
            "default_emotion": "calm",
            "blink_profile": {"interval_ms": 3200, "duration_ms": 180},
            "retrieval_hints": ["element_water", "sign_pisces"],
        }

    monkeypatch.setattr(internal_router, "get_profile", fake_get_profile)
    monkeypatch.setattr(internal_router, "compile_profile", fake_compile_profile)
    response = client.get(
        f"/api/internal/devices/{DEVICE_UID}/persona_pack", headers=internal_headers()
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "kb_version",
        "system_prompt_fragments",
        "style_constraints",
        "taboo",
        "default_emotion",
        "blink_profile",
        "retrieval_hints",
    }
