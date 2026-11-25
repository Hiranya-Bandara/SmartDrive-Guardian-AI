"""Minimal read-only ELM327 client.

This is the only code that writes to a transport, and every request first passes the allowlist
in :mod:`smartdrive.obd.commands`. The client tracks response latency and failures so the user
interface can show a connection quality based on measured data.
"""

from __future__ import annotations

import logging
import re
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Final

from smartdrive.config.constants import DtcStatus
from smartdrive.obd.commands import validate
from smartdrive.obd.dtc import MODE_FOR_STATUS, RESPONSE_BYTE, decode_dtc, parse_codes
from smartdrive.obd.errors import (
    AdapterNotRespondingError,
    CommunicationTimeoutError,
    MalformedResponseError,
    NoDataError,
    ObdError,
)
from smartdrive.obd.pids import (
    FREEZE_FRAME_DTC_PID,
    MONITOR_STATUS_PID,
    SUPPORT_PIDS,
    MonitorStatus,
    PidSpec,
    decode,
    decode_monitor_status,
)
from smartdrive.obd.responses import clean_lines, parse_messages, payload_for
from smartdrive.obd.transport import Transport

logger = logging.getLogger(__name__)

PROTOCOLS: Final = {
    "1": "SAE J1850 PWM",
    "2": "SAE J1850 VPW",
    "3": "ISO 9141-2",
    "4": "ISO 14230-4 KWP (5-baud init)",
    "5": "ISO 14230-4 KWP (fast init)",
    "6": "ISO 15765-4 CAN (11-bit, 500 kbaud)",
    "7": "ISO 15765-4 CAN (29-bit, 500 kbaud)",
    "8": "ISO 15765-4 CAN (11-bit, 250 kbaud)",
    "9": "ISO 15765-4 CAN (29-bit, 250 kbaud)",
    "A": "SAE J1939 CAN",
    "B": "User CAN 1",
    "C": "User CAN 2",
}
CAN_PROTOCOLS: Final = frozenset("6789ABC")
INIT_COMMANDS: Final = ("ATE0", "ATL0", "ATS1", "ATH0", "ATAT1", "ATSP0")
_VOLTAGE: Final = re.compile(r"(\d{1,2}(?:\.\d{1,2})?)\s*V")
LATENCY_WINDOW: Final = 50


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    version: str
    device_description: str | None
    supply_voltage_v: float | None


@dataclass(frozen=True, slots=True)
class LinkQuality:
    """Measured from the most recent requests; never estimated."""

    requests: int
    failures: int
    timeouts: int
    median_latency_ms: float | None
    max_latency_ms: float | None

    @property
    def success_ratio(self) -> float | None:
        if self.requests == 0:
            return None
        return (self.requests - self.failures) / self.requests


class Elm327Client:
    def __init__(
        self,
        transport: Transport,
        *,
        command_timeout_s: float = 1.5,
        init_timeout_s: float = 5.0,
        cancel: threading.Event | None = None,
    ) -> None:
        self._transport = transport
        self.command_timeout_s = command_timeout_s
        self.init_timeout_s = init_timeout_s
        self._cancel = cancel
        self._latencies: deque[float] = deque(maxlen=LATENCY_WINDOW)
        self._outcomes: deque[str] = deque(maxlen=LATENCY_WINDOW)
        self.protocol_number: str | None = None

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    def is_can(self) -> bool:
        return self.protocol_number is not None and self.protocol_number in CAN_PROTOCOLS

    @property
    def protocol_name(self) -> str | None:
        if self.protocol_number is None:
            return None
        return PROTOCOLS.get(self.protocol_number, f"Protocol {self.protocol_number}")

    # -- raw exchange ---------------------------------------------------------------------------

    def send(self, request: str, *, timeout_s: float | None = None) -> str:
        """Send one allowlisted command and return the raw reply text (without the prompt)."""
        command = validate(request)
        started = time.monotonic()
        try:
            self._transport.write(command.request.encode("ascii") + b"\r")
            reply = self._transport.read_until_prompt(
                self.command_timeout_s if timeout_s is None else timeout_s, self._cancel
            )
        except CommunicationTimeoutError:
            self._record("timeout", started)
            raise
        except ObdError:
            self._record("failure", started)
            raise
        self._record("ok", started)
        return reply

    def _record(self, outcome: str, started: float) -> None:
        self._outcomes.append(outcome)
        if outcome == "ok":
            self._latencies.append((time.monotonic() - started) * 1000.0)

    def quality(self) -> LinkQuality:
        latencies = list(self._latencies)
        outcomes = list(self._outcomes)
        return LinkQuality(
            requests=len(outcomes),
            failures=sum(1 for o in outcomes if o != "ok"),
            timeouts=sum(1 for o in outcomes if o == "timeout"),
            median_latency_ms=round(statistics.median(latencies), 1) if latencies else None,
            max_latency_ms=round(max(latencies), 1) if latencies else None,
        )

    def note_failure(self) -> None:
        """Count a decoded-but-unusable reply (malformed) against link quality."""
        self._outcomes.append("failure")

    # -- adapter set-up -------------------------------------------------------------------------

    def initialize(self) -> AdapterInfo:
        try:
            reply = self.send("ATZ", timeout_s=self.init_timeout_s)
        except CommunicationTimeoutError as exc:
            raise AdapterNotRespondingError(f"No reply to ATZ: {exc}") from exc
        version = _version_from(reply)
        if version is None:
            raise AdapterNotRespondingError(f"Device did not identify as an ELM327: {reply!r}")
        for request in INIT_COMMANDS:
            reply = self.send(request, timeout_s=self.init_timeout_s)
            if "OK" not in clean_lines(reply):
                raise AdapterNotRespondingError(f"{request} was not accepted: {reply!r}")
        description = self._optional_text("AT@1")
        voltage = self.supply_voltage()
        return AdapterInfo(
            version=version, device_description=description, supply_voltage_v=voltage
        )

    def supply_voltage(self) -> float | None:
        """Voltage at the adapter's OBD pin 16 (the vehicle battery), as measured by the adapter."""
        text = self._optional_text("ATRV")
        match = _VOLTAGE.search(text or "")
        return float(match.group(1)) if match else None

    def _optional_text(self, request: str) -> str | None:
        try:
            lines = [line for line in clean_lines(self.send(request)) if line != request]
        except (CommunicationTimeoutError, MalformedResponseError):
            return None
        if not lines or lines[0] == "?":
            return None
        return " ".join(lines)[:120]

    def detect_protocol(self) -> str | None:
        text = self._optional_text("ATDPN")
        if not text:
            return None
        number = text.strip().removeprefix("A")[:1]
        self.protocol_number = number if number in PROTOCOLS else None
        return self.protocol_number

    # -- vehicle queries ------------------------------------------------------------------------

    def messages(self, request: str, *, timeout_s: float | None = None) -> list[bytes]:
        command = validate(request)
        reply = self.send(command.request, timeout_s=timeout_s)
        try:
            return parse_messages(reply, echo=command.request)
        except MalformedResponseError:
            self.note_failure()
            raise

    def supported_pids(self, *, timeout_s: float | None = None) -> set[int]:
        """Mode 01 PIDs the vehicle reports as supported (union over all answering ECUs)."""
        supported: set[int] = set()
        for base in SUPPORT_PIDS:
            if base and (base not in supported):
                break
            try:
                payloads = payload_for(
                    self.messages(f"01{base:02X}", timeout_s=timeout_s), bytes([0x41, base])
                )
            except NoDataError:
                break
            for payload in payloads:
                if len(payload) < 4:
                    raise MalformedResponseError(f"Supported-PID bitmap too short: {payload!r}")
                bits = int.from_bytes(payload[:4], "big")
                for offset in range(32):
                    if bits & (1 << (31 - offset)):
                        supported.add(base + offset + 1)
        return supported

    def read_pid(self, spec: PidSpec) -> float:
        payloads = payload_for(self.messages(spec.request), bytes([0x41, spec.pid]))
        try:
            return decode(spec, payloads[0])
        except ValueError as exc:
            self.note_failure()
            raise MalformedResponseError(str(exc)) from exc

    def monitor_status(self) -> MonitorStatus:
        payloads = payload_for(self.messages("0101"), bytes([0x41, MONITOR_STATUS_PID]))
        try:
            statuses = [decode_monitor_status(p) for p in payloads]
        except ValueError as exc:
            raise MalformedResponseError(str(exc)) from exc
        return MonitorStatus(
            mil_on=any(s.mil_on for s in statuses), dtc_count=sum(s.dtc_count for s in statuses)
        )

    def trouble_codes(self, status: DtcStatus) -> list[str]:
        """Codes for one status. An empty list means the vehicle reported none."""
        request = MODE_FOR_STATUS[status]
        try:
            messages = self.messages(request, timeout_s=max(self.command_timeout_s, 3.0))
        except NoDataError:
            return []
        payloads = payload_for(messages, bytes([RESPONSE_BYTE[status]]))
        return parse_codes(payloads, is_can=self.is_can)

    def freeze_frame_code(self) -> str | None:
        payloads = payload_for(
            self.messages(f"02{FREEZE_FRAME_DTC_PID:02X}00"), bytes([0x42, FREEZE_FRAME_DTC_PID])
        )
        data = payloads[0]
        if len(data) >= 3:  # frame number then two code bytes
            data = data[1:]
        if len(data) < 2 or (data[0] == 0 and data[1] == 0):
            return None
        return decode_dtc(data[0], data[1])

    def freeze_frame_value(self, spec: PidSpec) -> float:
        payloads = payload_for(self.messages(f"02{spec.pid:02X}00"), bytes([0x42, spec.pid]))
        data = payloads[0]
        try:
            return decode(spec, data[1:] if len(data) > spec.length else data)
        except ValueError as exc:
            raise MalformedResponseError(str(exc)) from exc

    def close_protocol(self) -> None:
        try:
            self.send("ATPC", timeout_s=1.0)
        except ObdError:
            logger.debug("ATPC was not acknowledged while closing", exc_info=True)


def _version_from(reply: str) -> str | None:
    for line in clean_lines(reply):
        if "ELM327" in line or ("ELM" in line and "V" in line):
            return line[:60]
    return None
