"""agent-worker：PG SKIP LOCKED 队列消费者（独立入口，并发=1，禁进实时语音路径）。

产出（docs/05）：analysis_results / memories(candidate) / kb_feedback_candidates 等。
严禁：直接 UPDATE published KB；同步插入实时 TTS 路径。
"""

from agent_worker.worker import run_worker

__all__ = ["run_worker"]
