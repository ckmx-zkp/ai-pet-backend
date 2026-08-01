"""internal 路由测试（FakeSession + dependency_overrides + monkeypatch，同 test_devices 风格）。

覆盖：单条/批量 chat events 写入、脱敏生效（入库即替换）、未知设备 404、
session 自动建行与复用、peripheral 覆盖写、session end 置 ended_at + 入队任务（幂等）、
devices/seen 新建（user_id 为空）与更新、无 token 401。
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
        # chat_sessions.id 由 xiaozhi 侧 session_id 显式指定（如 10、20），避开自增段
        self.next_id += 100
        return self.next_id

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


def internal_headers() -> dict[str, str]:
    return {"X-Internal-Token": get_settings().internal_service_token}


def seed_device(
    store: FakeSession, device_uid: str = DEVICE_UID, user_id: int | None = 1
) -> Device:
    device = Device(user_id=user_id, device_uid=device_uid, capabilities={})
    store.add(device)
    return device


def event(
    session_id: int = 10, content: str = "你好呀", device_uid: str = DEVICE_UID
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

    async def fake_get_chat_session(session: AsyncSession, session_id: int) -> ChatSession | None:
        assert isinstance(session, FakeSession)
        return session.chat_sessions.get(session_id)

    async def fake_get_peripheral_state(
        session: AsyncSession, device_id: int
    ) -> DevicePeripheralState | None:
        assert isinstance(session, FakeSession)
        return session.peripheral_states.get(device_id)

    monkeypatch.setattr(internal_router, "_find_device_by_uid", fake_find_by_uid)
    monkeypatch.setattr(internal_router, "_get_chat_session", fake_get_chat_session)
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

    # 首次见 session_id 自动建行，user_id 跟随设备归属
    chat_session = store.chat_sessions[10]
    assert chat_session.device_id == device.id
    assert chat_session.user_id == 1

    message = store.chat_messages[0]
    assert message.session_id == 10
    assert message.device_id == device.id
    assert message.role == "user"
    assert message.content_redacted == "你好呀"
    assert message.created_at == datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    # 设备活跃镜像更新
    assert device.online_at is not None


def test_chat_events_batch_reuses_session(client: TestClient, store: FakeSession) -> None:
    seed_device(store)
    payload = [
        event(session_id=10, content="第一句"),
        event(session_id=10, content="第二句"),
        event(session_id=20, content="另一个会话"),
    ]
    resp = client.post("/api/internal/chat/events", json=payload, headers=internal_headers())
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 3}

    assert len(store.chat_messages) == 3
    # session 10 只建一次（复用），session 20 自动建行
    assert set(store.chat_sessions) == {10, 20}
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
    store.add(ChatSession(id=10, device_id=other.id, user_id=2))
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
    store.add(ChatSession(id=10, device_id=device.id, user_id=1))

    resp = client.post("/api/internal/chat/sessions/10/end", headers=internal_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["ended"] is True
    assert body["task_id"] is not None

    chat_session = store.chat_sessions[10]
    assert chat_session.ended_at is not None

    assert len(store.agent_tasks) == 1
    task = store.agent_tasks[0]
    assert task.kind == "daily_summary"
    assert task.status == "pending"
    assert task.payload == {"session_id": 10, "device_id": device.id}

    # 幂等：重复 end 不重复入队
    resp = client.post("/api/internal/chat/sessions/10/end", headers=internal_headers())
    assert resp.status_code == 200
    assert resp.json()["ended"] is False
    assert len(store.agent_tasks) == 1


def test_end_session_unknown_404(client: TestClient, store: FakeSession) -> None:
    resp = client.post("/api/internal/chat/sessions/999/end", headers=internal_headers())
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
    assert client.post("/api/internal/chat/sessions/10/end").status_code == 401
    assert (
        client.post("/api/internal/devices/seen", json={"device_uid": DEVICE_UID}).status_code
        == 401
    )
