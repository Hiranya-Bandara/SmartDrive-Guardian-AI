"""Serial adapter discovery. Listing ports never opens them; connecting needs the user's choice."""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from typing import Final

from smartdrive.obd.mock import MOCK_DESCRIPTION, MOCK_PORT

logger = logging.getLogger(__name__)

_WINDOWS_PORT: Final = re.compile(r"^COM([1-9]\d{0,2})$", re.IGNORECASE)
_POSIX_PORT: Final = re.compile(r"^/dev/(tty|cu|rfcomm)[A-Za-z0-9._-]{0,32}$")
COMMON_BAUD_RATES: Final = (38400, 9600, 115200, 57600, 230400, 500000)
_BLUETOOTH_HINTS: Final = ("bluetooth", "bthenum", "rfcomm", "standard serial over bluetooth")
_USB_HINTS: Final = ("usb", "ch340", "ch341", "ftdi", "ft232", "cp210", "pl2303", "elm")


@dataclass(frozen=True, slots=True)
class SerialPortInfo:
    port: str
    description: str
    manufacturer: str | None = None
    hardware_id: str | None = None
    is_mock: bool = False

    @property
    def connection_method(self) -> str:
        if self.is_mock:
            return "Mock (no hardware)"
        text = f"{self.description} {self.hardware_id or ''} {self.port}".lower()
        if any(hint in text for hint in _BLUETOOTH_HINTS):
            return "Bluetooth Classic (serial port)"
        if any(hint in text for hint in _USB_HINTS):
            return "USB serial"
        return "Serial port"

    @property
    def label(self) -> str:
        return f"{self.port} — {self.description}" if self.description else self.port


def mock_port_info() -> SerialPortInfo:
    return SerialPortInfo(MOCK_PORT, MOCK_DESCRIPTION, is_mock=True)


def list_serial_ports(*, include_mock: bool = False) -> list[SerialPortInfo]:
    """Ports reported by the operating system. Returns an empty list if PySerial is missing."""
    ports: list[SerialPortInfo] = []
    try:
        from serial.tools import list_ports
    except ImportError:
        logger.warning("PySerial is not installed; serial adapters cannot be listed")
    else:
        try:
            found = list_ports.comports()
        except OSError:
            logger.warning("Serial port enumeration failed", exc_info=True)
            found = []
        for item in sorted(found, key=lambda p: _port_sort_key(p.device)):
            description = item.description if item.description not in (None, "n/a") else ""
            ports.append(
                SerialPortInfo(
                    port=item.device,
                    description=description or "",
                    manufacturer=item.manufacturer,
                    hardware_id=item.hwid if item.hwid not in (None, "n/a") else None,
                )
            )
    if include_mock:
        ports.append(mock_port_info())
    return ports


def validate_port_name(port: str) -> str:
    """Return a normalised port name or raise ``ValueError`` for anything that is not a port."""
    name = port.strip()
    if name.upper() == MOCK_PORT:
        return MOCK_PORT
    if _WINDOWS_PORT.fullmatch(name):
        return name.upper()
    if sys.platform != "win32" and _POSIX_PORT.fullmatch(name):
        return name
    raise ValueError(
        "Enter a serial port such as COM3 (Windows) or /dev/ttyUSB0 (Linux); "
        f"{port!r} is not a serial port name."
    )


def _port_sort_key(device: str) -> tuple[int, str]:
    match = _WINDOWS_PORT.fullmatch(device)
    return (int(match.group(1)), device) if match else (10_000, device)
