from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from smartdrive import __version__
from smartdrive.cli import main
from smartdrive.config.constants import HOME_ENV_VAR

pytestmark = pytest.mark.integration


def test_info_bootstraps_a_fresh_installation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    assert main(["--home", str(home), "info"]) == 0
    out = capsys.readouterr().out
    assert f"SmartDrive Guardian AI {__version__}" in out
    assert "not a certified vehicle safety system" in out
    assert (home / "data" / "smartdrive.db").is_file()
    assert (home / "config" / "settings.json").is_file()
    assert (home / "logs" / "smartdrive.log").is_file()


def test_default_command_is_info(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "Schema revision" in capsys.readouterr().out


def test_backup_check_and_restore_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = ["--home", str(tmp_path / "home")]
    target = tmp_path / "manual.db"
    assert main([*home, "db", "backup", "--output", str(target)]) == 0
    assert target.is_file()
    assert main([*home, "db", "check"]) == 0
    assert main([*home, "db", "restore", str(target), "--yes"]) == 0
    assert "Database restored" in capsys.readouterr().out


def test_restore_failure_reports_error_and_nonzero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bogus = tmp_path / "bogus.db"
    bogus.write_text("nope", encoding="utf-8")
    assert main(["db", "restore", str(bogus), "--yes"]) == 1
    assert "not a SmartDrive backup" in capsys.readouterr().err


def test_settings_show_and_reset(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["settings", "show"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["appearance"]["theme"] == "dark"
    assert main(["settings", "reset"]) == 0


def test_module_entry_point_runs_in_subprocess(tmp_path: Path) -> None:
    env = {HOME_ENV_VAR: str(tmp_path / "sub")}
    import os

    result = subprocess.run(
        [sys.executable, "-m", "smartdrive", "--version"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **env},
        timeout=60,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout
