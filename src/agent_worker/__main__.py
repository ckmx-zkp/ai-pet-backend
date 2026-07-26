"""agent-worker 入口：python -m agent_worker。"""

import asyncio

from agent_worker.worker import run_worker
from pet_common.config import get_settings
from pet_common.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(service="agent-worker", level=settings.log_level)
    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
