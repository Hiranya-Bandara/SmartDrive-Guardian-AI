from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from smartdrive.utils.logger import REDACTED, ROOT_LOGGER_NAME, configure_logging, shutdown_logging

VIN = "JTDBR32E720123456"


def _records(log_file: Path) -> list[dict[str, object]]:
    shutdown_logging()
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]


def test_writes_structured_json_lines_with_context(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    configure_logging(log_file, console=False)
    logging.getLogger("smartdrive.test").info("Connected", extra={"port": "COM3"})
    (record,) = _records(log_file)
    assert record["level"] == "INFO"
    assert record["logger"] == "smartdrive.test"
    assert record["msg"] == "Connected"
    assert record["ctx"] == {"port": "COM3"}


def test_uses_rotating_file_handler(tmp_path: Path) -> None:
    root = configure_logging(tmp_path / "app.log", console=False)
    assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)


def test_redacts_vin_in_message_arguments_and_sensitive_fields(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    configure_logging(log_file, console=False, redact=True)
    log = logging.getLogger("smartdrive.test")
    log.info("Vehicle %s added", VIN, extra={"vin": VIN, "registration_number": "CAB-1234"})
    (record,) = _records(log_file)
    text = json.dumps(record)
    assert VIN not in text
    assert "CAB-1234" not in text
    assert record["msg"] == f"Vehicle {REDACTED} added"


def test_redaction_can_be_disabled(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    configure_logging(log_file, console=False, redact=False)
    logging.getLogger("smartdrive.test").info("Vehicle %s", VIN)
    (record,) = _records(log_file)
    assert record["msg"] == f"Vehicle {VIN}"


def test_reconfiguration_does_not_duplicate_handlers(tmp_path: Path) -> None:
    configure_logging(tmp_path / "a.log", console=True)
    root = configure_logging(tmp_path / "b.log", console=True)
    ours = [h for h in root.handlers if getattr(h, "_smartdrive_handler", False)]
    assert len(ours) == 2


def test_exceptions_are_serialised(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    configure_logging(log_file, console=False)
    try:
        raise RuntimeError("adapter fault")
    except RuntimeError:
        logging.getLogger(ROOT_LOGGER_NAME).exception("Adapter failed")
    (record,) = _records(log_file)
    assert "RuntimeError: adapter fault" in str(record["exc"])
