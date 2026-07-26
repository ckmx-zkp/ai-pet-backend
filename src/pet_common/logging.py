"""structlog JSON 日志配置。

固定字段（docs/08 §4）：ts / level / service / trace_id / device_id / session_id / kb_version。
- ts/level/service 由 processors 注入；
- trace_id/device_id/session_id/kb_version 通过 contextvars 由中间件或调用方绑定。

红线：日志不落对话原文，只记元数据（hash/长度）。
"""

import logging

import structlog
from structlog.typing import EventDict, Processor


def _add_service(service: str) -> Processor:
    def processor(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
        event_dict["service"] = service
        return event_dict

    return processor


def configure_logging(service: str, level: str = "INFO") -> None:
    """配置 structlog JSON 输出到 stdout。每个进程入口启动时调用一次。"""
    logging.basicConfig(format="%(message)s", level=level.upper())
    structlog.configure(
        processors=[
            # trace_id / device_id / session_id / kb_version 来自 contextvars
            structlog.contextvars.merge_contextvars,
            _add_service(service),
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="ts"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger()
    return logger
