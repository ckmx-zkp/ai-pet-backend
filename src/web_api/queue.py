"""入队辅助：web-api 只写 agent_tasks，不执行任务。"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pet_common.models import AgentTask


async def enqueue_memory_profile(session: AsyncSession, device_id: int, reason: str) -> None:
    """同一设备已有 pending 画像任务则跳过，避免连点重复入队。"""
    pending = (
        (
            await session.execute(
                select(AgentTask)
                .where(AgentTask.kind == "memory_profile", AgentTask.status == "pending")
                .order_by(AgentTask.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    if any(task.payload.get("device_id") == device_id for task in pending):
        return
    session.add(
        AgentTask(
            kind="memory_profile",
            payload={"device_id": device_id, "reason": reason},
            status="pending",
        )
    )


def new_task(kind: str, payload: dict[str, Any]) -> AgentTask:
    return AgentTask(kind=kind, payload=payload, status="pending")
