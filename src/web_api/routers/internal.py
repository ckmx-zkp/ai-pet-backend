"""/internal/* 服务间接口（docs/06 §内部接口，xiaozhi-server 调用）。

鉴权：X-Internal-Token 服务间 token。worker 禁进实时路径——这些接口只做快查/入队。
"""

from fastapi import APIRouter

from web_api.routers._common import not_implemented

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/devices/{device_uid}/persona_pack")
async def get_persona_pack(device_uid: str) -> None:
    """编译或读缓存的 persona_pack（key=device_id+kb_version+daily_date）。

    响应 schema 钉死 7 字段（docs/06）：kb_version / system_prompt_fragments /
    style_constraints / taboo / default_emotion / blink_profile / retrieval_hints。
    """
    not_implemented()


@router.post("/chat/events")
async def ingest_chat_events() -> None:
    """旁路消息：脱敏后写 chat_messages（只存 content_redacted）。

    请求 schema 钉死 5 字段（docs/06）：device_id/session_id/role/content/ts；
    脱敏由 backend 落库前执行，原文不落库。
    """
    not_implemented()


@router.post("/peripheral/events")
async def ingest_peripheral_events() -> None:
    """外设事件：覆盖写 device_peripheral_state。"""
    not_implemented()


@router.post("/chat/sessions/{session_id}/end")
async def end_chat_session(session_id: int) -> None:
    """会话结束：触发摘要任务入队（agent_tasks）。"""
    not_implemented()
