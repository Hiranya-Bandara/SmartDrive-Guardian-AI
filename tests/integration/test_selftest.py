"""The installation self-test used by the packaged-application smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smartdrive import selftest
from smartdrive.cli import main

pytestmark = pytest.mark.integration


def test_self_test_passes_and_leaves_no_data_behind(tmp_path: Path, qapp: object) -> None:
    report = selftest.run_self_test(include_qt=True)
    names = [check.name for check in report.checks]
    assert names[:6] == [
        "data folders",
        "settings",
        "database",
        "bundled resources",
        "model artifacts",
        "simulation and diagnostics",
    ]
    assert report.passed, [c for c in report.checks if not c.ok]
    assert not report.frozen
    assert not Path(report.data_folder).exists()  # temporary folder removed


def test_cli_writes_a_json_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "result folder" / "self-test.json"
    assert (
        main(["--home", str(tmp_path / "home"), "self-test", "--no-qt", "--report", str(target)])
        == 0
    )
    data = json.loads(target.read_text("utf-8"))
    assert data["passed"] is True and data["app_version"]
    assert "self-test: PASSED" in capsys.readouterr().out


def test_a_required_failure_skips_dependent_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_state: object) -> str:
        raise RuntimeError("integrity check failed: manifest mismatch")

    monkeypatch.setattr(selftest, "_check_models", broken)
    report = selftest.run_self_test(home=tmp_path / "home", include_qt=False)
    by_name = {c.name: c for c in report.checks}
    assert not report.passed
    assert "manifest mismatch" in by_name["model artifacts"].detail
    assert by_name["simulation and diagnostics"].detail.startswith("Skipped")
    assert by_name["reports"].detail.startswith("Skipped")
