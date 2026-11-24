"""Reusable input validators. Each returns a normalised value or raises
:class:`~smartdrive.utils.exceptions.DataValidationError`."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Final

from smartdrive.utils.exceptions import DataValidationError

EARLIEST_MODEL_YEAR: Final = 1886
_VIN_RE: Final = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_REGISTRATION_RE: Final = re.compile(r"^[A-Z0-9][A-Z0-9 \-]{0,14}[A-Z0-9]$")
_DTC_RE: Final = re.compile(r"^[PCBU][0-3][0-9A-F]{3}$")


def normalize_vin(value: str) -> str:
    """Check ISO 3779 VIN form: 17 characters, no I, O or Q. The check digit is not
    enforced because it is only mandatory in some markets."""
    vin = value.strip().upper()
    if not _VIN_RE.fullmatch(vin):
        raise DataValidationError(
            "VIN must be 17 characters (letters and digits, excluding I, O and Q).",
            user_message="The VIN must contain 17 letters and digits (no I, O or Q).",
        )
    return vin


def normalize_registration(value: str) -> str:
    registration = " ".join(value.strip().upper().split())
    if not _REGISTRATION_RE.fullmatch(registration):
        raise DataValidationError(
            "Registration number must be 2-16 letters, digits, spaces or hyphens.",
            user_message="Enter a registration number using letters, digits, spaces or hyphens.",
        )
    return registration


def validate_model_year(year: int, *, today: date | None = None) -> int:
    latest = (today or date.today()).year + 1
    if not EARLIEST_MODEL_YEAR <= year <= latest:
        raise DataValidationError(
            f"Manufacturing year must be between {EARLIEST_MODEL_YEAR} and {latest}.",
            user_message=f"Enter a year between {EARLIEST_MODEL_YEAR} and {latest}.",
        )
    return year


def normalize_dtc(code: str) -> str:
    """Validate an SAE J2012 diagnostic trouble code such as ``P0217``."""
    normalized = code.strip().upper()
    if not _DTC_RE.fullmatch(normalized):
        raise DataValidationError(f"'{code}' is not a valid diagnostic trouble code.")
    return normalized


def validate_export_path(
    path: Path, *, allowed_suffixes: frozenset[str], forbidden_roots: tuple[Path, ...] = ()
) -> Path:
    """Resolve a user-selected export destination and reject unsafe targets."""
    resolved = path.expanduser().resolve()
    if resolved.suffix.lower() not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise DataValidationError(f"Export file must end with one of: {allowed}.")
    if not resolved.parent.is_dir():
        raise DataValidationError(f"Export folder does not exist: {resolved.parent}")
    if resolved.exists() and not resolved.is_file():
        raise DataValidationError(f"Export target is not a regular file: {resolved}")
    for root in forbidden_roots:
        if resolved.is_relative_to(root.resolve()):
            raise DataValidationError(f"Exports cannot be written inside {root}.")
    return resolved
