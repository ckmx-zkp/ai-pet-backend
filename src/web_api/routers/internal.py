"""/internal/* 服务间接口（docs/06 §内部接口，xiaozhi-server 调用）。

鉴权：X-Internal-Token 服务间 token。worker 禁进实时路径——这些接口只做快查/入队。
红线 1：对话只存 content_redacted，原文不落库不落日志（脱敏见 pet_common.redaction）。

设备标识统一为 device_uid（MAC）：小智侧只持有 MAC，不知道 backend 自增 id。
会话标识统一为 external_session_id（字符串，xiaozhi 侧分配、全局唯一）：
chat_sessions 内部自增 id 不暴露给小智，仅作 chat_messages.session_id 的外键。
chat_messages 无 ts 列，事件的 ts 写入 created_at（历史查询索引列即事件时间）。
devices 无 last_seen_at 列，online_at 兼作最后活跃镜像（docs/06 §设备在线状态）。
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.db import get_session
from pet_common.models import (
    AgentTask,
    ChatMessage,
    ChatSession,
    Device,
    DevicePeripheralState,
)
from pet_common.redaction import redact_text
from web_api.routers._common import not_implemented

router = APIRouter(prefix="/internal", tags=["internal"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DeviceUid = Annotated[str, StringConstraints(min_length=4, max_length=64, strip_whitespace=True)]


class ChatEventIn(BaseModel):
    """旁路消息：契约 5 字段（docs/06）；session_id 为 xiaozhi 侧字符串会话号，首次见自动建行。"""

    device_uid: DeviceUid
    session_id: Annotated[
        str, StringConstraints(min_length=1, max_length=128, strip_whitespace=True)
    ]
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1)
    ts: datetime


class ChatEventsAccepted(BaseModel):
    accepted: int


class PeripheralEventIn(BaseModel):
    """外设快照：一设备一行，每次全量覆盖写四个字段。"""

    device_uid: DeviceUid
    emotion: Annotated[str | None, StringConstraints(max_length=32)] = None
    gaze: Annotated[str | None, StringConstraints(max_length=32)] = None
    closed: bool | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DeviceSeenIn(BaseModel):
    """设备首见登记：device_uid 不存在则建行（user_id=NULL 待认领，E1 重绑兼容）。"""

    device_uid: DeviceUid
    firmware_version: Annotated[str | None, StringConstraints(max_length=64)] = None
    capabilities: dict[str, Any] | None = None


class DeviceSeenResponse(BaseModel):
    id: int
    device_uid: str
    created: bool


class SessionEndResponse(BaseModel):
    session_id: str  # 回显 xiaozhi 侧字符串会话号（external_session_id）
    ended: bool  # 本次调用是否新置 ended_at（重复 end 幂等，不重复入队）
    task_id: int | None


async def _find_device_by_uid(session: AsyncSession, device_uid: str) -> Device | None:
    result = await session.execute(select(Device).where(Device.device_uid == device_uid))
    return result.scalar_one_or_none()


async def _find_chat_session_by_external_id(
    session: AsyncSession, external_session_id: str
) -> ChatSession | None:
    result = await session.execute(
        select(ChatSession).where(ChatSession.external_session_id == external_session_id)
    )
    return result.scalar_one_or_none()


async def _get_peripheral_state(
    session: AsyncSession, device_id: int
) -> DevicePeripheralState | None:
    result = await session.execute(
        select(DevicePeripheralState).where(DevicePeripheralState.device_id == device_id)
    )
    return result.scalar_one_or_none()


def _utcnow() -> datetime:
    return datetime.now(UTC)


@router.get("/devices/{device_uid}/persona_pack")
async def get_persona_pack(device_uid: str) -> None:
    """编译或读缓存的 persona_pack（E2 实现，7 字段 schema 见 docs/06）。"""
    not_implemented()


@router.post("/chat/events", response_model=ChatEventsAccepted)
async def ingest_chat_events(
    payload: ChatEventIn | list[ChatEventIn], session: SessionDep
) -> ChatEventsAccepted:
    """旁路消息：脱敏后写 chat_messages（只存 content_redacted），body 支持单条或数组。

    按 device_uid 解析设备，任一未知设备整体 404（不部分落库）；
    session_id（external_session_id，字符串）首次见自动建行，
    已存在但属于其他设备 → 404；每批镜像 devices.online_at。
    """
    events = payload if isinstance(payload, list) else [payload]
    devices: dict[str, Device] = {}
    for event in events:
        if event.device_uid in devices:
            continue
        device = await _find_device_by_uid(session, event.device_uid)
        if device is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="device not found")
        devices[event.device_uid] = device

    now = _utcnow()
    sessions: dict[str, ChatSession] = {}
    for event in events:
        device = devices[event.device_uid]
        chat_session = sessions.get(event.session_id)
        if chat_session is None:
            chat_session = await _find_chat_session_by_external_id(session, event.session_id)
            if chat_session is None:
                chat_session = ChatSession(
                    external_session_id=event.session_id,
                    device_id=device.id,
                    user_id=device.user_id,
                )
                session.add(chat_session)
                await session.flush()  # 取内部自增 id，供 chat_messages 外键引用
            elif chat_session.device_id != device.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="session not found")
            sessions[event.session_id] = chat_session
        session.add(
            ChatMessage(
                session_id=chat_session.id,
                device_id=device.id,
                role=event.role,
                content_redacted=redact_text(event.content),
                created_at=event.ts,
            )
        )
        device.online_at = now
    await session.commit()
    return ChatEventsAccepted(accepted=len(events))


@router.post("/peripheral/events", status_code=status.HTTP_204_NO_CONTENT)
async def ingest_peripheral_events(payload: PeripheralEventIn, session: SessionDep) -> None:
    """外设事件：device_peripheral_state 一设备一行覆盖写；设备不存在 404。"""
    device = await _find_device_by_uid(session, payload.device_uid)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="device not found")
    state = await _get_peripheral_state(session, device.id)
    if state is None:
        state = DevicePeripheralState(device_id=device.id, extra={})
        session.add(state)
    state.eye_emotion = payload.emotion
    state.eye_gaze = payload.gaze
    state.eye_closed = payload.closed
    state.extra = payload.extra
    await session.commit()


@router.post("/chat/sessions/{session_id}/end", response_model=SessionEndResponse)
async def end_chat_session(session_id: str, session: SessionDep) -> SessionEndResponse:
    """会话结束：ended_at 落库 + daily_summary 任务入队 agent_tasks（status=pending）。

    session_id 为 xiaozhi 侧字符串会话号（external_session_id）；
    任务 payload 同时带外部会话号与内部 id，worker 两侧都可定位。
    幂等：已结束的会话重复 end 直接返回，不重复入队。
    """
    chat_session = await _find_chat_session_by_external_id(session, session_id)
    if chat_session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="session not found")
    if chat_session.ended_at is not None:
        return SessionEndResponse(session_id=session_id, ended=False, task_id=None)
    chat_session.ended_at = _utcnow()
    task = AgentTask(
        kind="daily_summary",
        payload={
            "session_id": chat_session.id,
            "external_session_id": session_id,
            "device_id": chat_session.device_id,
        },
        status="pending",
    )
    session.add(task)
    await session.flush()  # 取 task 自增 id
    await session.commit()
    return SessionEndResponse(session_id=session_id, ended=True, task_id=task.id)


@router.post("/devices/seen", response_model=DeviceSeenResponse)
async def device_seen(payload: DeviceSeenIn, session: SessionDep) -> DeviceSeenResponse:
    """设备首见登记/活跃上报：不存在则建行（user_id=NULL 待认领）；存在则更新活跃镜像。

    与 E1 重绑逻辑兼容：user_id 为 NULL 的设备在 POST /devices/bind 时 UPDATE 回原行，
    保留设备 id 与全部历史。
    """
    now = _utcnow()
    device = await _find_device_by_uid(session, payload.device_uid)
    if device is None:
        device = Device(
            user_id=None,
            device_uid=payload.device_uid,
            capabilities=payload.capabilities or {},
            firmware_version=payload.firmware_version,
            online_at=now,
        )
        session.add(device)
        await session.flush()  # 取自增 id
        await session.commit()
        return DeviceSeenResponse(id=device.id, device_uid=device.device_uid, created=True)
    device.online_at = now
    if payload.firmware_version is not None:
        device.firmware_version = payload.firmware_version
    if payload.capabilities is not None:
        device.capabilities = payload.capabilities
    await session.commit()
    return DeviceSeenResponse(id=device.id, device_uid=device.device_uid, created=False)
