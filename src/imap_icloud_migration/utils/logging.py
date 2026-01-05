"""Logging helpers for console output."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from imap_icloud_migration.config.settings import LoggingSettings

_RESERVED_LOG_RECORD_KEYS: set[str] = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def _safe_json_value(value: object) -> Any:
    """Coerce a value to something JSON-serializable.

    Args:
        value: Value to serialize.

    Returns:
        The original value if JSON-serializable; otherwise, its string representation.
    """
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


class JsonLogFormatter(logging.Formatter):
    """Formatter that emits JSON payloads to stdout/stderr."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON.

        Args:
            record: Log record to format.

        Returns:
            JSON string representation.
        """
        payload: dict[str, Any] = {
            "ts": datetime.now(tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_KEYS:
                continue
            if key.startswith("_"):
                continue
            payload[key] = _safe_json_value(value)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, settings: LoggingSettings) -> None:
    """Configure stdout/stderr logging for CLI runs.

    Args:
        settings: Logging settings (level and JSON/human output).
    """
    level_name = settings.level.strip().upper() if settings.level else "INFO"
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler()
    handler.setLevel(level)

    if settings.json_logs:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ),
        )

    logging.basicConfig(level=level, handlers=[handler], force=True)

    logging.getLogger("googleapiclient.discovery").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
