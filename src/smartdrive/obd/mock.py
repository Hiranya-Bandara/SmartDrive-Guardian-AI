"""Deterministic mock ELM327 adapter for automated tests and hardware-free demonstrations.

It speaks the ELM327 text protocol at byte level, so the real client, parser and allowlist are
exercised end to end. It is always labelled as a mock: its description, its ``AT@1`` reply and
``is_mock`` say so, and telemetry from it is recorded as *simulated* data, never as live vehicle
data. Nothing it returns has been measured on a vehicle.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from smartdrive.obd.errors import (
    AdapterDisconnectedError,
    CommunicationTimeoutError,
    InvalidPortError,
    OperationCancelledError,
)

MOCK_PORT: Final = "MOCK"
MOCK_DESCRIPTION: Final = "Mock ELM327 adapter (testing only — not a vehicle)"
MOCK_DEVICE_TEXT: Final = "SMARTDRIVE MOCK ADAPTER - NOT REAL HARDWARE"

ValueFunction = Callable[[float], float]


def _drive_rpm(t: float) -> float:
    return 850.0 + 1400.0 * (0.5 + 0.5 * math.sin(t / 9.0))


def _drive_speed(t: float) -> float:
    return max(0.0, 55.0 + 35.0 * math.sin(t / 13.0))


def _warm_coolant(t: float) -> float:
    return min(90.0, 45.0 + t * 0.8)


DEFAULT_VALUES: Final[dict[int, ValueFunction]] = {
    0x04: lambda t: 25.0 + 20.0 * (0.5 + 0.5 * math.sin(t / 9.0)),
    0x05: _warm_coolant,
    0x06: lambda t: 1.6,
    0x07: lambda t: -2.3,
    0x0B: lambda t: 38.0 + 30.0 * (0.5 + 0.5 * math.sin(t / 9.0)),
    0x0C: _drive_rpm,
    0x0D: _drive_speed,
    0x0F: lambda t: 31.0,
    0x10: lambda t: 4.0 + 10.0 * (0.5 + 0.5 * math.sin(t / 9.0)),
    0x11: lambda t: 14.0 + 18.0 * (0.5 + 0.5 * math.sin(t / 9.0)),
    0x1F: lambda t: t,
    0x2F: lambda t: 63.0,
    0x33: lambda t: 100.0,
    0x42: lambda t: 14.1,
    0x46: lambda t: 29.0,
    0x5C: lambda t: min(95.0, 40.0 + t * 0.6),
    0x5E: lambda t: 2.0 + 3.0 * (0.5 + 0.5 * math.sin(t / 9.0)),
}


def _encode(pid: int, value: float) -> bytes:
    """Inverse of the J1979 formulas used by :mod:`smartdrive.obd.pids`."""

    def byte(v: float) -> bytes:
        return bytes([max(0, min(255, round(v)))])

    def word(v: float) -> bytes:
        n = max(0, min(65535, round(v)))
        return bytes([n >> 8, n & 0xFF])

    if pid in (0x04, 0x11, 0x2F):
        return byte(value * 255.0 / 100.0)
    if pid in (0x05, 0x0F, 0x46, 0x5C):
        return byte(value + 40.0)
    if pid in (0x06, 0x07, 0x08, 0x09):
        return byte(value * 128.0 / 100.0 + 128.0)
    if pid in (0x0B, 0x0D, 0x33):
        return byte(value)
    if pid == 0x0C:
        return word(value * 4.0)
    if pid == 0x10:
        return word(value * 100.0)
    if pid == 0x1F:
        return word(value)
    if pid == 0x42:
        return word(value * 1000.0)
    if pid == 0x5E:
        return word(value * 20.0)
    raise KeyError(pid)


def encode_code(code: str) -> bytes:
    letter = "PCBU".index(code[0])
    first = (letter << 6) | (int(code[1]) << 4) | int(code[2], 16)
    return bytes([first, int(code[3:5], 16)])


@dataclass
class MockVehicleProfile:
    name: str = "Healthy mock vehicle"
    protocol: str = "6"
    supported_pids: frozenset[int] = frozenset(
        {0x04, 0x05, 0x06, 0x07, 0x0B, 0x0C, 0x0D, 0x0F, 0x10, 0x11, 0x1F, 0x2F, 0x33, 0x42, 0x46}
    )
    values: dict[int, ValueFunction] = field(default_factory=lambda: dict(DEFAULT_VALUES))
    ecu_responds: bool = True
    adapter_responds: bool = True
    mil_on: bool = False
    stored_codes: tuple[str, ...] = ()
    pending_codes: tuple[str, ...] = ()
    permanent_codes: tuple[str, ...] = ()
    permanent_supported: bool = True
    freeze_frame_code: str | None = None
    freeze_frame: dict[int, float] = field(default_factory=dict)
    malformed_pids: frozenset[int] = frozenset()
    silent_pids: frozenset[int] = frozenset()
    """PIDs whose request never receives a prompt (adapter timeout)."""
    disconnect_after: int | None = None
    """Number of vehicle requests after which the adapter disappears."""
    reconnectable: bool = True
    supply_voltage_v: float = 12.6


PROFILES: Final[dict[str, Callable[[], MockVehicleProfile]]] = {
    "healthy": MockVehicleProfile,
    "stored_codes": lambda: MockVehicleProfile(
        name="Mock vehicle with stored and pending codes",
        mil_on=True,
        stored_codes=("P0301", "P0171"),
        pending_codes=("P0420",),
        permanent_codes=("P0301",),
        freeze_frame_code="P0301",
        freeze_frame={0x04: 41.0, 0x05: 88.0, 0x0C: 2150.0, 0x0D: 64.0},
    ),
    "partial_sensors": lambda: MockVehicleProfile(
        name="Mock vehicle with few supported sensors",
        supported_pids=frozenset({0x05, 0x0C, 0x0D}),
        permanent_supported=False,
    ),
    "no_ecu": lambda: MockVehicleProfile(name="Mock adapter, ignition off", ecu_responds=False),
    "legacy_protocol": lambda: MockVehicleProfile(
        name="Mock ISO 9141-2 vehicle",
        protocol="3",
        mil_on=True,
        stored_codes=("P0133", "P0442", "P0118", "P0507"),
    ),
}


class MockElm327Transport:
    """An in-memory ELM327 emulation. ``requests`` records every command it received."""

    def __init__(
        self,
        profile: MockVehicleProfile | None = None,
        *,
        clock: Callable[[], float] | None = None,
        exists: bool = True,
    ) -> None:
        self.profile = profile or MockVehicleProfile()
        self._clock = clock or time.monotonic
        self._start = self._clock()
        self._exists = exists
        self._open = False
        self._echo = True
        self._headers = False
        self._protocol_selected = False
        self._pending: str | None = None
        self.requests: list[str] = []
        self.vehicle_requests = 0
        self.open_count = 0
        self.disconnected = False

    @property
    def description(self) -> str:
        return MOCK_DESCRIPTION

    @property
    def is_mock(self) -> bool:
        return True

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        if not self._exists:
            raise InvalidPortError("Mock port does not exist")
        if self.disconnected and not self.profile.reconnectable:
            raise AdapterDisconnectedError("Mock adapter is unplugged")
        self.disconnected = False
        self.vehicle_requests = (
            0 if self.profile.disconnect_after is None else self.vehicle_requests
        )
        self._open = True
        self.open_count += 1

    def close(self) -> None:
        self._open = False

    def reset_input(self) -> None:
        self._pending = None

    def unplug(self) -> None:
        """Simulate the adapter being removed."""
        self.disconnected = True

    def write(self, data: bytes) -> None:
        if not self._open or self.disconnected:
            raise AdapterDisconnectedError("Mock adapter is not connected")
        text = data.decode("ascii").strip().upper()
        self.requests.append(text)
        self._pending = text

    def read_until_prompt(self, timeout_s: float, cancel: threading.Event | None = None) -> str:
        if cancel is not None and cancel.is_set():
            raise OperationCancelledError("Read cancelled")
        if not self._open or self.disconnected:
            raise AdapterDisconnectedError("Mock adapter is not connected")
        request, self._pending = self._pending, None
        if request is None:
            raise CommunicationTimeoutError("Nothing was requested")
        if not self.profile.adapter_responds:
            raise CommunicationTimeoutError("Mock device does not answer")
        reply = self._reply(request)
        if reply is None:
            raise CommunicationTimeoutError(f"Mock adapter did not answer {request}")
        echo = f"{request}\r" if self._echo else ""
        return f"{echo}{reply}\r\r>"

    # -- emulation ------------------------------------------------------------------------------

    def _reply(self, request: str) -> str | None:
        if request.startswith("AT"):
            return self._at(request)
        self.vehicle_requests += 1
        limit = self.profile.disconnect_after
        if limit is not None and self.vehicle_requests > limit:
            self.disconnected = True
            raise AdapterDisconnectedError("Mock adapter disconnected")
        if not self.profile.ecu_responds:
            return "SEARCHING...\rUNABLE TO CONNECT"
        prefix = "" if self._protocol_selected else "SEARCHING...\r"
        self._protocol_selected = True
        body = self._obd(request)
        return None if body is None else prefix + body

    def _at(self, request: str) -> str:
        if request in ("ATZ", "ATWS"):
            self._echo = True
            self._protocol_selected = False
            return "\rELM327 v1.5 (MOCK)"
        if request == "ATE0":
            self._echo = False
            return "OK"
        if request in ("ATL0", "ATS1", "ATH0", "ATAT1", "ATSP0", "ATPC"):
            return "OK"
        if request == "ATI":
            return "ELM327 v1.5 (MOCK)"
        if request == "AT@1":
            return MOCK_DEVICE_TEXT
        if request == "ATRV":
            return f"{self.profile.supply_voltage_v:.1f}V"
        if request == "ATDPN":
            return f"A{self.profile.protocol}" if self._protocol_selected else "0"
        return "?"

    def _obd(self, request: str) -> str | None:
        mode, rest = request[:2], request[2:]
        if mode == "01":
            return self._current(int(rest, 16))
        if mode == "02":
            return self._freeze(int(rest[:2], 16))
        if mode in ("03", "07", "0A"):
            return self._codes(mode)
        return "?"

    def _current(self, pid: int) -> str | None:
        profile = self.profile
        if pid in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0):
            return self._bitmap(pid)
        if pid == 0x01:
            count = len(profile.stored_codes)
            return _hex([0x41, 0x01, (0x80 if profile.mil_on else 0) | count, 0x07, 0xE5, 0x00])
        if pid not in profile.supported_pids or pid not in profile.values:
            return "NO DATA"
        if pid in profile.silent_pids:
            return None
        if pid in profile.malformed_pids:
            return "41 ZZ"
        elapsed = self._clock() - self._start
        return _hex([0x41, pid, *_encode(pid, profile.values[pid](elapsed))])

    def _bitmap(self, base: int) -> str:
        bits = 0
        supported = set(self.profile.supported_pids) | {0x01}
        highest = max(supported)
        supported |= {marker for marker in range(0x20, 0xE0, 0x20) if marker < highest}
        for offset in range(32):
            if base + offset + 1 in supported:
                bits |= 1 << (31 - offset)
        if base and base not in supported:
            return "NO DATA"
        return _hex([0x41, base, *bits.to_bytes(4, "big")])

    def _freeze(self, pid: int) -> str:
        profile = self.profile
        if profile.freeze_frame_code is None:
            return "NO DATA"
        if pid == 0x02:
            return _hex([0x42, 0x02, 0x00, *encode_code(profile.freeze_frame_code)])
        if pid == 0x00:
            bits = 0
            for p in (*profile.freeze_frame, 0x02):
                if 1 <= p <= 32:
                    bits |= 1 << (32 - p)
            return _hex([0x42, 0x00, 0x00, *bits.to_bytes(4, "big")])
        if pid not in profile.freeze_frame:
            return "NO DATA"
        return _hex([0x42, pid, 0x00, *_encode(pid, profile.freeze_frame[pid])])

    def _codes(self, mode: str) -> str:
        profile = self.profile
        codes = {
            "03": profile.stored_codes,
            "07": profile.pending_codes,
            "0A": profile.permanent_codes,
        }[mode]
        if mode == "0A" and not profile.permanent_supported:
            return "NO DATA"
        response = int(mode, 16) + 0x40
        payload = b"".join(encode_code(c) for c in codes)
        if profile.protocol in "6789ABC":
            data = bytes([response, len(codes)]) + payload
            if len(data) <= 7:
                return _hex(list(data))
            lines = [f"{len(data):03X}"]
            first, rest = data[:6], data[6:]
            lines.append(f"0: {_hex(list(first))}")
            index = 1
            while rest:
                lines.append(f"{index:X}: {_hex(list(rest[:7]))}")
                rest, index = rest[7:], index + 1
            return "\r".join(lines)
        if not codes:
            return _hex([response, 0, 0, 0, 0, 0, 0])
        lines = []
        for start in range(0, len(payload), 6):
            chunk = payload[start : start + 6].ljust(6, b"\x00")
            lines.append(_hex([response, *chunk]))
        return "\r".join(lines)


def _hex(values: list[int]) -> str:
    return " ".join(f"{v:02X}" for v in values)


def create_mock_transport(profile_name: str = "healthy") -> MockElm327Transport:
    factory = PROFILES.get(profile_name)
    if factory is None:
        raise ValueError(f"Unknown mock profile {profile_name!r}")
    return MockElm327Transport(factory())
