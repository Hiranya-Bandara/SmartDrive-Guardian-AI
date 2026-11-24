"""Centralised logging: JSON-lines rotating file plus readable console output.

Vehicle identifiers are masked before any record is written when redaction is enabled.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Final

from smartdrive.config.constants import LOG_BACKUP_COUNT, LOG_MAX_BYTES

ROOT_LOGGER_NAME: Final = "smartdrive"
_HANDLER_MARKER: Final = "_smartdrive_handler"

# Attributes present on every LogRecord; anything else came from ``extra=``.
_STANDARD_ATTRS: Final = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)

_VIN_PATTERN: Final = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
SENSITIVE_KEYS: Final = frozenset(
    {"vin", "registration_number", "registration", "licence_plate", "license_plate"}
)
REDACTED: Final = "[REDACTED]"


def redact_text(text: str) -> str:
    return _VIN_PATTERN.sub(REDACTED, text)


class RedactionFilter(logging.Filter):
    """Masks VIN-shaped tokens in messages and values of sensitive ``extra`` keys."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.msg = record.getMessage()
            record.args = None
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        for key in list(vars(record)):
            if key in _STANDARD_ATTRS:
                continue
            value = getattr(record, key)
            if key.lower() in SENSITIVE_KEYS and value is not None:
                setattr(record, key, REDACTED)
            elif isinstance(value, str):
                setattr(record, key, redact_text(value))
        return True


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        context = {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}
        if context:
            entry["ctx"] = context
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}
        if context:
            base += " " + " ".join(f"{k}={v}" for k, v in sorted(context.items()))
        return base


def configure_logging(
    log_file: Path,
    *,
    level: str = "INFO",
    redact: bool = True,
    console: bool = True,
) -> logging.Logger:
    """Install application handlers. Safe to call repeatedly; previous handlers are replaced."""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)
            handler.close()
    root.filters = [f for f in root.filters if not isinstance(f, RedactionFilter)]

    root.setLevel(level)
    root.propagate = False

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(JsonLinesFormatter())
    handlers: list[logging.Handler] = [file_handler]

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(ConsoleFormatter())
        console_handler.setLevel(max(logging.getLevelNamesMapping()[level], logging.WARNING))
        handlers.append(console_handler)

    for handler in handlers:
        setattr(handler, _HANDLER_MARKER, True)
        if redact:
            handler.addFilter(RedactionFilter())
        root.addHandler(handler)
    return root


def shutdown_logging() -> None:
    root = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            handler.flush()
            root.removeHandler(handler)
            handler.close()
