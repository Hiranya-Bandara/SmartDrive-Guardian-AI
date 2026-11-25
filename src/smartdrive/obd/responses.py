"""Parsing of raw ELM327 replies (headers off, spaces on) into byte messages.

A reply may contain several messages: one per answering ECU, and CAN multi-frame messages
(ISO 15765-2) appear as a byte-count line followed by ``0:``, ``1:``… frame lines, which are
reassembled here. Status words from the adapter are turned into typed errors.
"""

from __future__ import annotations

import re
from typing import Final

from smartdrive.obd.errors import (
    AdapterReportedError,
    EcuUnavailableError,
    MalformedResponseError,
    NoDataError,
    UnsupportedProtocolError,
)

_IGNORED_PREFIXES: Final = ("SEARCHING", "BUS INIT", "OK")
_ADAPTER_ERRORS: Final = (
    "CAN ERROR",
    "BUS ERROR",
    "BUS BUSY",
    "FB ERROR",
    "DATA ERROR",
    "<DATA ERROR",
    "BUFFER FULL",
    "RX ERROR",
    "STOPPED",
    "LV RESET",
    "ACT ALERT",
    "LP ALERT",
)
_HEX_LINE: Final = re.compile(r"^(?:[0-9A-F]{2})+$")
_FRAME_LINE: Final = re.compile(r"^([0-9A-F]):((?:[0-9A-F]{2})+)$")
_COUNT_LINE: Final = re.compile(r"^[0-9A-F]{3}$")


def clean_lines(raw: str) -> list[str]:
    text = raw.replace(">", "").replace("\n", "\r")
    lines: list[str] = []
    for line in text.split("\r"):
        stripped = line.strip().upper()
        if stripped:
            lines.append(stripped)
    return lines


def check_status(lines: list[str]) -> None:
    """Raise for adapter status words. ``NO DATA`` only counts when nothing else answered."""
    joined = " ".join(lines)
    if "UNABLE TO CONNECT" in joined:
        raise UnsupportedProtocolError(f"Adapter reported UNABLE TO CONNECT: {joined}")
    if "BUS INIT" in joined and "ERROR" in joined:
        raise EcuUnavailableError(f"Adapter bus initialisation failed: {joined}")
    for word in _ADAPTER_ERRORS:
        if word in joined:
            raise AdapterReportedError(f"Adapter reported {word}: {joined}")
    if re.search(r"\bERR\d\d\b", joined):
        raise AdapterReportedError(f"Adapter internal error: {joined}")
    if lines and all(line in ("?",) for line in lines):
        raise MalformedResponseError("Adapter did not recognise the command")


def parse_messages(raw: str, *, echo: str | None = None) -> list[bytes]:
    """Return the data messages in ``raw``; raise :class:`NoDataError` when there are none."""
    lines = [line for line in clean_lines(raw) if not line.startswith(_IGNORED_PREFIXES)]
    if echo is not None:
        lines = [line for line in lines if line.replace(" ", "") != echo]
    check_status(lines)
    data_lines = [line for line in lines if line != "NO DATA"]
    if not data_lines:
        raise NoDataError("Vehicle answered NO DATA")
    messages: list[bytes] = []
    pending: dict[int, bytes] | None = None
    expected = 0
    for line in data_lines:
        compact = line.replace(" ", "")
        if _COUNT_LINE.fullmatch(compact):
            if pending is not None:
                messages.append(_join(pending, expected))
            pending, expected = {}, int(compact, 16)
            continue
        frame = _FRAME_LINE.fullmatch(compact)
        if frame is not None:
            if pending is None:
                raise MalformedResponseError(f"Frame line without a byte count: {line!r}")
            pending[int(frame.group(1), 16)] = bytes.fromhex(frame.group(2))
            continue
        if not _HEX_LINE.fullmatch(compact):
            raise MalformedResponseError(f"Unexpected response line: {line!r}")
        if pending is not None:
            messages.append(_join(pending, expected))
            pending = None
        messages.append(bytes.fromhex(compact))
    if pending is not None:
        messages.append(_join(pending, expected))
    return messages


def _join(frames: dict[int, bytes], expected: int) -> bytes:
    if not frames:
        raise MalformedResponseError("Multi-frame response had no frames")
    # Frame indices wrap from F to 0 after sixteen frames; order of arrival is preserved by keys
    # only up to that point, which covers every response SmartDrive requests.
    data = b"".join(frames[index] for index in sorted(frames))
    if len(data) < expected:
        raise MalformedResponseError(
            f"Multi-frame response truncated: expected {expected} bytes, got {len(data)}"
        )
    return data[:expected]


def payload_for(messages: list[bytes], response_prefix: bytes) -> list[bytes]:
    """Messages that answer the request, i.e. start with ``response_prefix`` (e.g. ``41 0C``)."""
    matching = [m[len(response_prefix) :] for m in messages if m.startswith(response_prefix)]
    if not matching:
        raise MalformedResponseError(
            f"No message starts with {response_prefix.hex(' ').upper()}: "
            f"{[m.hex(' ').upper() for m in messages]}"
        )
    return matching
