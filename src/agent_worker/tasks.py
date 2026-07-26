"""任务处理器注册表。

key 对应 agent_tasks.kind；handler 签名为 async (payload, session) -> None。
首版留空——新任务类型在 Epic A 后续迭代中注册，例如：
- daily_summary      → analysis_results
- memory_suggest     → memories(candidate)
- kb_feedback        → kb_feedback_candidates
- daily_horoscope    → analysis_results / persona_daily_context
"""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

TaskHandler = Callable[[dict[str, Any], AsyncSession], Awaitable[None]]

TASK_REGISTRY: dict[str, TaskHandler] = {}
