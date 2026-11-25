"""The read-only command allowlist. Every byte sent to an adapter passes :func:`validate`.

The allowlist is a closed set of exact request strings, built once at import time:

- adapter set-up commands that only change how the ELM327 itself formats replies (echo, line
  feeds, headers, automatic protocol search, version and voltage queries);
- mode 01 current data for the PIDs in :mod:`smartdrive.obd.pids`, plus the supported-PID and
  monitor-status queries;
- mode 02 freeze-frame data for the same PIDs (frame 0);
- modes 03, 07 and 0A: stored, pending and permanent trouble codes.

Everything else is rejected before it reaches the transport — in particular mode 04 (clear
codes), mode 08 (on-board control), mode 09 (vehicle identification, excluded for privacy),
every UDS/KWP service (sessions, security access, routines, writes), and adapter commands that
would allow arbitrary CAN traffic (``AT SH``, ``AT MA``, ``AT CRA``, raw frames). The application
offers no way to type a command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from smartdrive.obd.errors import ProhibitedCommandError
from smartdrive.obd.pids import (
    DATA_PIDS,
    FREEZE_FRAME_DTC_PID,
    MONITOR_STATUS_PID,
    SUPPORT_PIDS,
)


class CommandKind(StrEnum):
    ADAPTER = "adapter"
    CURRENT_DATA = "current_data"
    FREEZE_FRAME = "freeze_frame"
    TROUBLE_CODES = "trouble_codes"


@dataclass(frozen=True, slots=True)
class AllowedCommand:
    request: str
    kind: CommandKind
    description: str


_ADAPTER: Final = {
    "ATZ": "Reset the adapter (adapter only; nothing is sent to the vehicle)",
    "ATWS": "Warm-start the adapter",
    "ATE0": "Turn command echo off",
    "ATL0": "Turn line feeds off",
    "ATS1": "Print spaces between bytes",
    "ATH0": "Hide CAN/ISO headers",
    "ATAT1": "Adaptive response timing",
    "ATSP0": "Automatic protocol search",
    "ATDPN": "Report the active protocol number",
    "ATDP": "Describe the active protocol",
    "ATI": "Adapter version",
    "AT@1": "Adapter device description",
    "ATRV": "Voltage at the adapter's supply pin",
    "ATPC": "Close the protocol",
}

PROHIBITED_EXAMPLES: Final = (
    "04",  # clear trouble codes and freeze frame
    "14FF00",  # UDS clear diagnostic information
    "08",  # on-board system control
    "0902",  # vehicle identification number (privacy)
    "1003",  # UDS diagnostic session control
    "2701",  # UDS security access
    "2EF190",  # UDS write data by identifier
    "2F",  # UDS input/output control (actuators)
    "3101",  # UDS routine control
    "3E00",  # tester present
    "ATSH7E0",  # set header: enables arbitrary CAN frames
    "ATMA",  # monitor all bus traffic
    "ATCRA7E8",  # CAN receive filter
    "STPX",  # STN raw transmission
)

_SAFE_TEXT: Final = re.compile(r"^[0-9A-Z@]{1,12}$")


def _build() -> dict[str, AllowedCommand]:
    table: dict[str, AllowedCommand] = {}
    for request, description in _ADAPTER.items():
        table[request] = AllowedCommand(request, CommandKind.ADAPTER, description)
    for pid in SUPPORT_PIDS:
        table[f"01{pid:02X}"] = AllowedCommand(
            f"01{pid:02X}", CommandKind.CURRENT_DATA, f"Supported PIDs {pid + 1:02X}-{pid + 32:02X}"
        )
    table[f"01{MONITOR_STATUS_PID:02X}"] = AllowedCommand(
        "0101", CommandKind.CURRENT_DATA, "Monitor status (MIL and trouble-code count)"
    )
    for spec in DATA_PIDS:
        table[spec.request] = AllowedCommand(spec.request, CommandKind.CURRENT_DATA, spec.label)
        freeze = f"02{spec.pid:02X}00"
        table[freeze] = AllowedCommand(
            freeze, CommandKind.FREEZE_FRAME, f"Freeze frame: {spec.label}"
        )
    table["020000"] = AllowedCommand(
        "020000", CommandKind.FREEZE_FRAME, "Freeze-frame supported PIDs"
    )
    table[f"02{FREEZE_FRAME_DTC_PID:02X}00"] = AllowedCommand(
        "020200", CommandKind.FREEZE_FRAME, "Trouble code that stored the freeze frame"
    )
    table["03"] = AllowedCommand("03", CommandKind.TROUBLE_CODES, "Stored trouble codes")
    table["07"] = AllowedCommand("07", CommandKind.TROUBLE_CODES, "Pending trouble codes")
    table["0A"] = AllowedCommand("0A", CommandKind.TROUBLE_CODES, "Permanent trouble codes")
    return table


ALLOWED_COMMANDS: Final[dict[str, AllowedCommand]] = _build()


def normalise(request: str) -> str:
    """Upper-case and remove spaces. Anything that is not plain command text is rejected."""
    if not isinstance(request, str):
        raise ProhibitedCommandError(f"Command must be text, got {type(request).__name__}")
    compact = request.replace(" ", "").upper()
    if not _SAFE_TEXT.fullmatch(compact):
        raise ProhibitedCommandError(f"Command contains unsupported characters: {request!r}")
    return compact


def validate(request: str) -> AllowedCommand:
    """Return the allowlisted command or raise :class:`ProhibitedCommandError`."""
    compact = normalise(request)
    command = ALLOWED_COMMANDS.get(compact)
    if command is None:
        raise ProhibitedCommandError(f"Command {compact!r} is not on the read-only allowlist")
    return command


def is_allowed(request: str) -> bool:
    try:
        validate(request)
    except ProhibitedCommandError:
        return False
    return True
