"""Automotive safety: nothing but the documented read-only requests can reach an adapter.

The allowlist is enforced twice: in :class:`Elm327Client` (the only writer) and again at the
transport boundary on the raw bytes. These tests try to get prohibited requests past each layer
and check the source tree for other paths to a serial port.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from smartdrive.obd import commands
from smartdrive.obd.commands import ALLOWED_COMMANDS, CommandKind, ensure_allowed_frame, validate
from smartdrive.obd.elm327 import Elm327Client
from smartdrive.obd.errors import ProhibitedCommandError
from smartdrive.obd.mock import PROFILES, MockElm327Transport
from smartdrive.obd.transport import SerialTransport

SRC = Path(__file__).resolve().parents[2] / "src" / "smartdrive"

# Each entry: (request, what it would do on a vehicle or adapter).
PROHIBITED: tuple[tuple[str, str], ...] = (
    ("04", "clear trouble codes and freeze frame (mode 04)"),
    ("0 4", "mode 04 with spacing"),
    ("08", "on-board system control (mode 08)"),
    ("0800", "mode 08 test request"),
    ("0902", "read VIN (mode 09, excluded for privacy)"),
    ("0904", "calibration identifiers (mode 09)"),
    ("0600", "on-board monitoring results outside the allowlist (mode 06)"),
    ("1003", "UDS diagnostic session control"),
    ("1101", "UDS ECU reset"),
    ("14FFFFFF", "UDS clear diagnostic information"),
    ("2701", "UDS security access (seed request)"),
    ("2702AABBCCDD", "UDS security access (key)"),
    ("2EF190", "UDS write data by identifier"),
    ("2F", "UDS input/output control (actuators)"),
    ("3101FF00", "UDS routine control"),
    ("34", "UDS request download (flashing)"),
    ("36", "UDS transfer data (flashing)"),
    ("3E00", "UDS tester present"),
    ("85", "UDS control DTC setting"),
    ("ATSH7E0", "set CAN header (arbitrary addressing)"),
    ("AT SH 7DF", "set CAN header with spaces"),
    ("ATMA", "monitor all CAN traffic"),
    ("ATCRA7E8", "CAN receive address filter"),
    ("ATCAF0", "raw CAN frames without formatting"),
    ("ATBI", "bypass initialisation"),
    ("ATPP0CSV01", "write adapter programmable parameter"),
    ("STP33", "STN chip protocol command"),
    ("010C;04", "command chaining"),
    ("010C\r04", "second command after a carriage return"),
    ("010C\n04", "second command after a line feed"),
    ("０１００", "full-width digits"),
    ("", "empty request"),
)


@pytest.mark.parametrize(("request_text", "meaning"), PROHIBITED)
def test_prohibited_requests_are_rejected(request_text: str, meaning: str) -> None:
    with pytest.raises(ProhibitedCommandError):
        validate(request_text)
    assert not commands.is_allowed(request_text), meaning


def test_allowlist_is_closed_and_read_only() -> None:
    assert len(ALLOWED_COMMANDS) == 65
    for key, command in ALLOWED_COMMANDS.items():
        assert key == command.request
        if command.kind is CommandKind.CURRENT_DATA:
            assert key.startswith("01")
        elif command.kind is CommandKind.FREEZE_FRAME:
            assert key.startswith("02") and key.endswith("00")  # frame 0 only
        elif command.kind is CommandKind.TROUBLE_CODES:
            assert key in {"03", "07", "0A"}
        else:
            assert key.startswith("AT")
            assert not re.match(r"AT(SH|MA|CRA|CAF|BI|PP|CF|CM|FC)", key)


@pytest.mark.parametrize(
    "frame",
    [
        b"04\r",
        b"0100",  # no terminator
        b"0100\r\r",
        b"0100\r04\r",  # two commands in one write
        b"0100\n",
        b"0100\r\n",
        b"01 00\r",  # not canonical
        b"0100 \r",
        b"\x04\r",
        b"0100\x00\r",
        "0100\r".encode("utf-16-le"),
    ],
)
def test_transport_boundary_rejects_frames(frame: bytes) -> None:
    with pytest.raises(ProhibitedCommandError):
        ensure_allowed_frame(frame)


def test_transport_boundary_accepts_exactly_the_allowlisted_frames() -> None:
    for request in ALLOWED_COMMANDS:
        assert ensure_allowed_frame(request.encode("ascii") + b"\r").request == request
    with pytest.raises(ProhibitedCommandError):
        ensure_allowed_frame("0100\r")  # type: ignore[arg-type]


class _RecordingHandle:
    is_open = True

    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def flush(self) -> None:
        pass


def test_serial_transport_never_writes_prohibited_bytes() -> None:
    transport = SerialTransport("COM_TEST", 38400)
    handle = _RecordingHandle()
    transport._serial = handle  # an "open" port without hardware
    for frame in (b"04\r", b"0100\r04\r", b"ATSH7E0\r", b"2701\r"):
        with pytest.raises(ProhibitedCommandError):
            transport.write(frame)
    assert handle.written == []
    transport.write(b"010C\r")
    assert handle.written == [b"010C\r"]


class _CountingTransport(MockElm327Transport):
    def __init__(self) -> None:
        super().__init__(PROFILES["healthy"]())
        self.writes = 0

    def write(self, data: bytes) -> None:
        self.writes += 1
        super().write(data)


@pytest.mark.parametrize(("request_text", "meaning"), PROHIBITED[:20])
def test_client_rejects_before_touching_the_transport(request_text: str, meaning: str) -> None:
    transport = _CountingTransport()
    transport.open()
    client = Elm327Client(transport)
    with pytest.raises(ProhibitedCommandError):
        client.send(request_text)
    assert transport.writes == 0, meaning


def test_mock_adapter_enforces_the_same_boundary() -> None:
    transport = MockElm327Transport(PROFILES["stored_codes"]())
    transport.open()
    with pytest.raises(ProhibitedCommandError):
        transport.write(b"04\r")
    assert "04" not in transport.requests


def _python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "migrations" not in p.parts)


def test_only_the_transport_module_opens_serial_ports() -> None:
    openers = []
    for path in _python_files():
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"Serial", "serial_for_url"}
            ):
                openers.append(path.relative_to(SRC).as_posix())
    assert openers == ["obd/transport.py"]


def test_only_the_client_writes_to_a_transport() -> None:
    """Outside obd/, nothing calls .write() on a transport; inside obd/, only elm327 does."""
    writers = set()
    for path in _python_files():
        if path.parent.name != "obd":
            continue
        text = path.read_text("utf-8")
        if re.search(r"_transport\.write\(", text):
            writers.add(path.name)
    assert writers == {"elm327.py"}


def test_no_code_path_offers_to_clear_codes() -> None:
    """Buttons and actions of every page are checked in tests/e2e (the running application)."""
    source = "\n".join(p.read_text("utf-8") for p in _python_files())
    assert not re.search(r"def\s+\w*(clear|erase|reset)_(trouble_)?codes", source)
