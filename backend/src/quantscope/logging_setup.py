"""Structured (JSON-line) logging for CLI jobs.

One line per event: ``{"ts", "level", "logger", "msg", ...extras}``. Any keyword
passed via ``logger.info(msg, extra={...})`` is merged into the object, so seed
events carry their counts as real fields rather than interpolated text.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Any

_RESERVED = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _dt.datetime.fromtimestamp(record.created, tz=_dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_json_logging(level: int = logging.INFO) -> None:
    """Install a single stderr handler emitting JSON lines. Idempotent."""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        if getattr(handler, "_quantscope_json", False):
            return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLineFormatter())
    handler._quantscope_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
