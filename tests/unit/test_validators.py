from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from smartdrive.utils.exceptions import DataValidationError
from smartdrive.utils.validators import (
    normalize_dtc,
    normalize_registration,
    normalize_vin,
    validate_export_path,
    validate_model_year,
)


@pytest.mark.parametrize("vin", ["jtdbr32e720123456", " JTDBR32E720123456 "])
def test_vin_is_normalised(vin: str) -> None:
    assert normalize_vin(vin) == "JTDBR32E720123456"


@pytest.mark.parametrize("vin", ["SHORT", "JTDBR32E72012345O", "JTDBR32E7201234567", ""])
def test_invalid_vin_rejected(vin: str) -> None:
    with pytest.raises(DataValidationError):
        normalize_vin(vin)


def test_registration_whitespace_and_case_normalised() -> None:
    assert normalize_registration("  cab   1234 ") == "CAB 1234"


@pytest.mark.parametrize("value", ["", "A", "CAB_1234", "X" * 20])
def test_invalid_registration_rejected(value: str) -> None:
    with pytest.raises(DataValidationError):
        normalize_registration(value)


def test_model_year_bounds() -> None:
    today = date(2026, 6, 1)
    assert validate_model_year(2027, today=today) == 2027
    with pytest.raises(DataValidationError):
        validate_model_year(2028, today=today)
    with pytest.raises(DataValidationError):
        validate_model_year(1800, today=today)


@pytest.mark.parametrize(("raw", "expected"), [("p0217", "P0217"), ("U0100", "U0100")])
def test_dtc_normalised(raw: str, expected: str) -> None:
    assert normalize_dtc(raw) == expected


@pytest.mark.parametrize("code", ["P02", "X0217", "P4217", "P02G7"])
def test_invalid_dtc_rejected(code: str) -> None:
    with pytest.raises(DataValidationError):
        normalize_dtc(code)


class TestExportPath:
    suffixes = frozenset({".pdf", ".csv"})

    def test_accepts_new_file_in_existing_folder(self, tmp_path: Path) -> None:
        target = validate_export_path(tmp_path / "report.PDF", allowed_suffixes=self.suffixes)
        assert target.parent == tmp_path.resolve()

    def test_rejects_wrong_suffix(self, tmp_path: Path) -> None:
        with pytest.raises(DataValidationError):
            validate_export_path(tmp_path / "report.exe", allowed_suffixes=self.suffixes)

    def test_rejects_missing_folder(self, tmp_path: Path) -> None:
        with pytest.raises(DataValidationError):
            validate_export_path(tmp_path / "nope" / "r.csv", allowed_suffixes=self.suffixes)

    def test_rejects_directory_target(self, tmp_path: Path) -> None:
        (tmp_path / "dir.csv").mkdir()
        with pytest.raises(DataValidationError):
            validate_export_path(tmp_path / "dir.csv", allowed_suffixes=self.suffixes)

    def test_rejects_forbidden_root(self, tmp_path: Path) -> None:
        install = tmp_path / "install"
        install.mkdir()
        with pytest.raises(DataValidationError):
            validate_export_path(
                install / "r.csv", allowed_suffixes=self.suffixes, forbidden_roots=(install,)
            )
