"""Byte transports to an ELM327 adapter.

:class:`SerialTransport` covers USB serial adapters and Bluetooth Classic adapters that the
operating system exposes as a serial (COM) port. Bluetooth Low Energy, Wi-Fi and proprietary
adapters are not supported. Reads are made in short slices so a pending operation can be
cancelled promptly (for example during application shutdown).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Final, Protocol, runtime_checkable

from smartdrive.obd.commands import ensure_allowed_frame
from smartdrive.obd.errors import (
    AdapterDisconnectedError,
    CommunicationTimeoutError,
    InvalidPortError,
    ObdError,
    OperationCancelledError,
    PortInUseError,
)

logger = logging.getLogger(__name__)

PROMPT: Final = b">"
READ_SLICE_S: Final = 0.05
MAX_RESPONSE_BYTES: Final = 64 * 1024


@runtime_checkable
class Transport(Protocol):
    """Raw byte channel. Only :class:`~smartdrive.obd.elm327.Elm327Client` writes to it."""

    @property
    def description(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    @property
    def is_open(self) -> bool: ...

    def open(self) -> None: ...

    def write(self, data: bytes) -> None: ...

    def read_until_prompt(self, timeout_s: float, cancel: threading.Event | None = None) -> str: ...

    def reset_input(self) -> None: ...

    def close(self) -> None: ...


class SerialTransport:
    """PySerial-backed transport. PySerial is imported lazily so the app starts without it."""

    def __init__(self, port: str, baudrate: int, *, write_timeout_s: float = 2.0) -> None:
        self._port = port
        self._baudrate = baudrate
        self._write_timeout_s = write_timeout_s
        self._serial: object | None = None

    @property
    def description(self) -> str:
        return f"{self._port} at {self._baudrate} baud"

    @property
    def is_mock(self) -> bool:
        return False

    @property
    def port(self) -> str:
        return self._port

    @property
    def baudrate(self) -> int:
        return self._baudrate

    @property
    def is_open(self) -> bool:
        return self._serial is not None and bool(getattr(self._serial, "is_open", False))

    def open(self) -> None:
        import serial

        try:
            self._serial = serial.Serial(
                self._port,
                self._baudrate,
                timeout=READ_SLICE_S,
                write_timeout=self._write_timeout_s,
            )
        except serial.SerialException as exc:
            raise classify_serial_error(self._port, exc) from exc
        except (OSError, ValueError) as exc:
            raise InvalidPortError(f"Cannot open {self._port}: {exc}") from exc

    def write(self, data: bytes) -> None:
        ensure_allowed_frame(data)  # read-only allowlist, checked again at the serial boundary
        handle = self._require()
        import serial

        try:
            handle.write(data)  # type: ignore[attr-defined]
            handle.flush()  # type: ignore[attr-defined]
        except serial.SerialTimeoutException as exc:
            raise CommunicationTimeoutError(f"Write to {self._port} timed out") from exc
        except (serial.SerialException, OSError) as exc:
            raise AdapterDisconnectedError(f"Write to {self._port} failed: {exc}") from exc

    def read_until_prompt(self, timeout_s: float, cancel: threading.Event | None = None) -> str:
        handle = self._require()
        import serial

        buffer = bytearray()
        deadline = time.monotonic() + timeout_s
        while True:
            if cancel is not None and cancel.is_set():
                raise OperationCancelledError("Read cancelled")
            try:
                chunk = handle.read(256)  # type: ignore[attr-defined]
            except (serial.SerialException, OSError) as exc:
                raise AdapterDisconnectedError(f"Read from {self._port} failed: {exc}") from exc
            if chunk:
                buffer.extend(chunk)
                if PROMPT in chunk:
                    break
                if len(buffer) > MAX_RESPONSE_BYTES:
                    raise CommunicationTimeoutError("Adapter response exceeded the size limit")
            elif time.monotonic() >= deadline:
                raise CommunicationTimeoutError(
                    f"No prompt from {self._port} within {timeout_s:.1f} s"
                )
        return buffer.decode("ascii", errors="replace")

    def reset_input(self) -> None:
        handle = self._require()
        try:
            handle.reset_input_buffer()  # type: ignore[attr-defined]
        except Exception as exc:
            raise AdapterDisconnectedError(f"Could not reset {self._port}: {exc}") from exc

    def close(self) -> None:
        handle, self._serial = self._serial, None
        if handle is None:
            return
        try:
            handle.close()  # type: ignore[attr-defined]
        except Exception:
            logger.warning("Serial port did not close cleanly", exc_info=True)

    def _require(self) -> object:
        if self._serial is None:
            raise AdapterDisconnectedError(f"{self._port} is not open")
        return self._serial


def classify_serial_error(port: str, exc: Exception) -> ObdError:
    """Map PySerial's open errors (which differ between Windows and Linux) to typed errors."""
    text = str(exc).lower()
    if any(
        marker in text
        for marker in ("access is denied", "permission", "busy", "errno 13", "errno 16", "in use")
    ):
        return PortInUseError(f"{port} is in use or not accessible: {exc}")
    if any(
        marker in text
        for marker in (
            "could not find",
            "cannot find",
            "no such file",
            "filenotfounderror",
            "the system cannot find",
            "does not exist",
        )
    ):
        return InvalidPortError(f"{port} does not exist: {exc}")
    return AdapterDisconnectedError(f"{port} could not be opened: {exc}")
