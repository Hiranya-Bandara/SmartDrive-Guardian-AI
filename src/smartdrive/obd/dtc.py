"""Decoding of diagnostic trouble codes from mode 03, 07 and 0A replies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from smartdrive.config.constants import DtcStatus
from smartdrive.obd.errors import MalformedResponseError

_LETTERS: Final = "PCBU"
CODE_PATTERN: Final = re.compile(r"^[PCBU][0-3][0-9A-F]{3}$")

MODE_FOR_STATUS: Final = {
    DtcStatus.STORED: "03",
    DtcStatus.PENDING: "07",
    DtcStatus.PERMANENT: "0A",
}
RESPONSE_BYTE: Final = {DtcStatus.STORED: 0x43, DtcStatus.PENDING: 0x47, DtcStatus.PERMANENT: 0x4A}


class CodeCategory(StrEnum):
    POWERTRAIN = "P"
    CHASSIS = "C"
    BODY = "B"
    NETWORK = "U"

    @property
    def label(self) -> str:
        return {"P": "Powertrain", "C": "Chassis", "B": "Body", "U": "Network communication"}[
            self.value
        ]


def decode_dtc(first: int, second: int) -> str:
    """Two raw bytes → code text, e.g. ``0x01 0x33`` → ``P0133``."""
    letter = _LETTERS[(first >> 6) & 0x03]
    digit = (first >> 4) & 0x03
    return f"{letter}{digit}{first & 0x0F:X}{second >> 4:X}{second & 0x0F:X}"


def category_of(code: str) -> CodeCategory:
    return CodeCategory(code[0])


def is_valid_code(code: str) -> bool:
    return bool(CODE_PATTERN.fullmatch(code))


def parse_codes(payloads: list[bytes], *, is_can: bool) -> list[str]:
    """Codes from response payloads (the bytes after the 43/47/4A response byte).

    CAN replies start with a count byte; older protocols send fixed groups of three code slots
    padded with ``00 00``. Duplicates from several ECUs are merged, order preserved.
    """
    codes: list[str] = []
    for payload in payloads:
        body = payload
        if is_can:
            if not body:
                raise MalformedResponseError("CAN trouble-code reply had no count byte")
            count, body = body[0], body[1:]
            if len(body) < count * 2:
                raise MalformedResponseError(
                    f"Trouble-code reply announced {count} codes but carried {len(body) // 2}"
                )
            body = body[: count * 2]
        if len(body) % 2:
            raise MalformedResponseError("Trouble-code reply had an odd number of bytes")
        for index in range(0, len(body), 2):
            first, second = body[index], body[index + 1]
            if first == 0 and second == 0:
                continue
            code = decode_dtc(first, second)
            if code not in codes:
                codes.append(code)
    return codes


@dataclass(frozen=True, slots=True)
class TroubleCodeReading:
    code: str
    status: DtcStatus

    @property
    def category(self) -> CodeCategory:
        return category_of(self.code)
