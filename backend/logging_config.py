

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any, Dict

from .config import get_settings

# ContextVar so async background tasks inherit the request id
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """Minimal structured formatter. Includes request_id when present."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        # Merge extra={} fields
        for key, val in record.__dict__.items():
            if key in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "message", "module",
                "msecs", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
            ):
                continue
            try:
                json.dumps({key: val})
                payload[key] = val
            except Exception:
                payload[key] = repr(val)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable formatter with the request id inlined."""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id_ctx.get()
        base = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        return logging.Formatter(base, datefmt="%H:%M:%S").format(record)


_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    s = get_settings()

    root = logging.getLogger()
    root.setLevel(s.LOG_LEVEL)

    # Clear any pre-existing handlers (e.g. uvicorn's) to avoid duplicate lines
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if s.LOG_JSON else TextFormatter())
    root.addHandler(handler)

    # Tame the chatty libraries
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
