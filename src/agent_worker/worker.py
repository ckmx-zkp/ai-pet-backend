"""worker 主循环：从 agent_tasks 表以 SKIP LOCKED 语义取任务并分发。

出队：单事务内 SELECT ... FOR UPDATE SKIP LOCKED 锁定一行并置 running，
处理成功置 done；失败累计 attempts，超过 max_attempts 置 failed（挂了不丢任务）。
并发=1：单进程单循环，靠 SKIP LOCKED 保证未来多实例安全。
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_worker.llm import LLMUnavailableError
from agent_worker.tasks import TASK_REGISTRY, TaskDeferredError
from pet_common.config import Settings
from pet_common.db import get_session_factory
from pet_common.logging import get_logger
from pet_common.models import AgentTask


async def _claim_next_task(session: AsyncSession) -> AgentTask | None:
    """在调用方事务内锁定一条 pending 任务（SKIP LOCKED），并标记 running。"""
    stmt = (
        select(AgentTask)
        .where(AgentTask.status == "pending", AgentTask.run_at <= func.now())
        .order_by(AgentTask.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    task = (await session.execute(stmt)).scalars().first()
    if task is not None:
        task.status = "running"
        task.attempts += 1
    return task


async def _process_one() -> bool:
    """取并处理一条任务。返回是否取到了任务。"""
    log = get_logger()
    async with get_session_factory()() as session, session.begin():
        task = await _claim_next_task(session)
        if task is None:
            return False
        handler = TASK_REGISTRY.get(task.kind)
        if handler is None:
            task.status = "failed"
            task.last_error = f"no handler registered for kind={task.kind!r}"
            log.warning("task_no_handler", task_id=task.id, kind=task.kind)
            return True
        try:
            await handler(task.payload, session)
        except LLMUnavailableError as exc:
            # API 尚未配置时不消耗重试次数，也不把未来可处理的数据永久标为 failed。
            task.status = "pending"
            task.attempts -= 1
            task.run_at = datetime.now(UTC) + timedelta(minutes=10)
            task.last_error = str(exc)[:2000]
            log.info("task_deferred_llm_unavailable", task_id=task.id, kind=task.kind)
        except TaskDeferredError as exc:
            # 依赖未就绪（如当日 L1 星座运势未生成）：延迟重试，不消耗重试次数。
            task.status = "pending"
            task.attempts -= 1
            task.run_at = datetime.now(UTC) + timedelta(minutes=10)
            task.last_error = str(exc)[:2000]
            log.info("task_deferred_dependency", task_id=task.id, kind=task.kind)
        except Exception as exc:  # noqa: BLE001 — worker 必须兜住所有异常，不能炸循环
            task.status = "failed" if task.attempts >= task.max_attempts else "pending"
            task.last_error = str(exc)[:2000]
            log.error("task_failed", task_id=task.id, kind=task.kind, attempts=task.attempts)
        else:
            task.status = "done"
            log.info("task_done", task_id=task.id, kind=task.kind)
        return True


async def run_worker(settings: Settings) -> None:
    """主循环：有任务连续处理，空队列则按 poll 间隔休眠。"""
    log = get_logger()
    log.info("worker_started", poll_interval=settings.worker_poll_interval_seconds)
    while True:
        got_task = await _process_one()
        if not got_task:
            await asyncio.sleep(settings.worker_poll_interval_seconds)
