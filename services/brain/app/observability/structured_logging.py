from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from ..security.redaction import redact_mapping, redact_value
from . import correlation

FIELDS = ("service", "event", "request_id", "task_id", "agent_id", "tool", "provider", "node_id", "duration_ms", "status")


class RedactingJsonFormatter(logging.Formatter):
    """One structured JSON line per record, redacted BEFORE persistence.
    Never logs hidden chain-of-thought (never captured) or secrets."""

    def __init__(self, service: str = "vyom-brain"):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
        }
        context = correlation.current()
        payload["request_id"] = context.request_id
        payload["trace_id"] = context.trace_id
        if context.task_id:
            payload["task_id"] = context.task_id
        message = record.getMessage()
        if isinstance(record.msg, dict):
            payload["event"] = str(message.get("event", "log"))
            for key in FIELDS:
                if key in message:
                    payload[key] = message[key]
            extra = {k: v for k, v in message.items() if k != "event" and k not in FIELDS}
            if extra:
                payload["details"] = redact_mapping(extra)
        else:
            payload["event"] = "log"
            payload["message"] = redact_value(message)
        if record.exc_info and record.exc_info[0] is not None:
            payload["error"] = redact_value(str(record.exc_info[1]))
        return json.dumps(payload, ensure_ascii=False, default=str)


class StructuredLogging:
    """Configures JSON structured logging with size-based rotation and
    retention. Audit-grade security events go to their own file (see
    security_events.py); debug logs rotate faster and never grow
    forever."""

    def __init__(self, log_dir: Path, *, level: str = "INFO", max_bytes: int = 5_000_000, backups: int = 5):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.max_bytes = max_bytes
        self.backups = backups
        self._applied = False

    def apply(self, service: str = "vyom-brain") -> Path:
        if self._applied:
            return self.log_dir / "brain.log"
        formatter = RedactingJsonFormatter(service)
        root = logging.getLogger()
        root.setLevel(self.level)
        for handler in list(root.handlers):
            root.removeHandler(handler)
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "brain.log", maxBytes=self.max_bytes, backupCount=self.backups, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(self.level)
        root.addHandler(file_handler)
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(self.level)
        root.addHandler(console)
        self._applied = True
        return self.log_dir / "brain.log"
