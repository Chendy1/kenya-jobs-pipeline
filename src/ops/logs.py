"""Structured logging: JSON lines in a rotating file (and optionally a readable console)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}
_configured = False


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Anything passed via extra={...} becomes a field."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(console: bool = True, level: str | None = None, log_dir: str | None = None) -> None:
    """Idempotent. Flows pass console=False because Prefect already prints to the console."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level or os.getenv("LOG_LEVEL", "INFO"))
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    directory = Path(log_dir or os.getenv("LOG_DIR", "logs"))
    directory.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(directory / "pipeline.jsonl", maxBytes=5_000_000,
                                       backupCount=5, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(stream)
    _configured = True