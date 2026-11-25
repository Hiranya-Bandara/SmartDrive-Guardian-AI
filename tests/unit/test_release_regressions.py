"""Regression tests for release issues: lifecycle rules, packaging entry point, resources,
version consistency and release metadata."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

import smartdrive
from smartdrive import launcher, resources

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src" / "smartdrive" / "ui"

# Objects that outlive the pages: a lambda connected to their signals keeps running after the
# receiving widget is deleted (the Phase 3 HealthScoreWidget teardown error).
LONG_LIVED = re.compile(
    r"\b(ctx|ui|state|monitoring|diagnostics|notifications|connection|trips|tasks|theme|"
    r"controller|worker|registry|notifier)\b"
)


def _sender(node: ast.Call) -> str | None:
    """Source text of X in X.connect(lambda ...), or None if this is not such a call."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "connect" and node.args):
        return None
    if not isinstance(node.args[0], ast.Lambda):
        return None
    return ast.unparse(func.value)


def test_no_lambda_receivers_on_long_lived_signals() -> None:
    offenders = []
    for path in sorted(UI.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            sender = _sender(node) if isinstance(node, ast.Call) else None
            if sender is not None and LONG_LIVED.search(sender):
                offenders.append(f"{path.relative_to(UI)}:{node.lineno} {sender}")
    assert offenders == [], "use a bound method so Qt drops the connection with the receiver"


@pytest.mark.parametrize("module", ["pages/dashboard.py", "pages/ai_diagnostics.py"])
def test_phase_3_lifecycle_fix_is_preserved(module: str) -> None:
    tree = ast.parse((UI / module).read_text("utf-8"))
    lambdas = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _sender(n) is not None]
    assert lambdas == []


class TestLauncher:
    def test_defaults_to_the_desktop_application(self) -> None:
        assert launcher.default_arguments([]) == ["gui"]
        assert launcher.default_arguments(["--home", "D:\\data"]) == ["--home", "D:\\data", "gui"]

    @pytest.mark.parametrize(
        "argv",
        [["self-test", "--report", "r.json"], ["info"], ["--version"], ["db", "check"], ["-h"]],
    )
    def test_explicit_commands_are_kept(self, argv: list[str]) -> None:
        assert launcher.default_arguments(argv) == argv

    def test_windowed_process_gets_writable_streams(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        launcher.ensure_standard_streams()
        assert sys.stdout is not None and sys.stderr is not None
        print("goes nowhere")
        sys.stdout.close()
        sys.stderr.close()

    @pytest.mark.parametrize(("attached", "expected"), [(1, "CONOUT$"), (0, None)])
    def test_windowed_exe_uses_the_parent_console_when_there_is_one(
        self, monkeypatch: pytest.MonkeyPatch, attached: int, expected: str | None
    ) -> None:
        import ctypes
        import types

        calls: list[int] = []
        kernel32 = types.SimpleNamespace(AttachConsole=lambda pid: calls.append(pid) or attached)
        windll = types.SimpleNamespace(kernel32=kernel32)
        monkeypatch.setattr(ctypes, "windll", windll, raising=False)
        monkeypatch.setattr(launcher, "_IS_WINDOWS", True)
        assert launcher._parent_console_output() == expected
        assert calls == [-1]  # ATTACH_PARENT_PROCESS

    def test_no_console_lookup_off_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(launcher, "_IS_WINDOWS", False)
        assert launcher._parent_console_output() is None

    def test_main_runs_the_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []
        monkeypatch.setattr("smartdrive.cli.main", lambda argv: seen.append(list(argv)) or 0)
        assert launcher.main(["info"]) == 0
        assert seen == [["info"]]


class TestResources:
    def test_all_required_resources_are_present(self) -> None:
        assert resources.missing_resources() == []
        assert len(resources.migration_scripts()) >= 3

    @pytest.mark.parametrize("parts", [(), ("..", "x"), ("branding", "../secret"), ("a/b",)])
    def test_resource_paths_cannot_escape_the_package(self, parts: tuple[str, ...]) -> None:
        with pytest.raises(ValueError, match="Invalid resource path"):
            resources.resource_path(*parts)

    def test_missing_model_file_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        real = resources.resource_path

        def fake(*parts: str) -> Path:
            if parts[:2] == ("ai", "artifacts") and parts[-1].endswith(".joblib"):
                return tmp_path / parts[-1]
            return real(*parts)

        monkeypatch.setattr(resources, "resource_path", fake)
        missing = resources.missing_resources()
        assert any(item.endswith(".joblib") for item in missing)

    def test_windows_icon_has_all_sizes(self) -> None:
        from PIL import Image

        with Image.open(resources.resource_path(*resources.APP_ICON_ICO)) as icon:
            sizes = sorted(icon.info["sizes"])
        assert sizes == [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]


class TestVersionConsistency:
    def test_pyproject_reads_the_package_version(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
        assert "version" not in project and project["dynamic"] == ["version"]
        dynamic = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["tool"]
        assert dynamic["setuptools"]["dynamic"]["version"] == {"attr": "smartdrive.__version__"}

    def test_packaging_files_take_the_version_from_the_source(self) -> None:
        spec = (ROOT / "packaging" / "smartdrive.spec").read_text("utf-8")
        iss = (ROOT / "packaging" / "installer.iss").read_text("utf-8")
        assert "from smartdrive import APP_NAME, __version__" in spec
        assert "#error AppVersion must be defined" in iss
        assert smartdrive.__version__ not in spec + iss  # never hard-coded

    def test_release_documents_name_the_version(self) -> None:
        version = smartdrive.__version__
        assert f"## [{version}]" in (ROOT / "CHANGELOG.md").read_text("utf-8")
        assert version in (ROOT / "RELEASE_NOTES.md").read_text("utf-8").splitlines()[0]


@pytest.fixture(scope="module")
def metadata() -> object:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import release_metadata
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    return release_metadata


class TestReleaseMetadata:
    def test_lock_file_is_filtered_for_windows(self, metadata: object) -> None:
        packages = {p.name: p for p in metadata.read_lock(ROOT / "requirements.txt")}  # type: ignore[attr-defined]
        assert {"comtypes", "pywin32", "pyside6-essentials", "scikit-learn"} <= set(packages)
        assert not any(name.startswith("pyobjc") for name in packages)
        assert packages["pyside6-essentials"].direct
        assert "pyside6-essentials" in packages["shiboken6"].parents
        development = {"pytest", "ruff", "mypy", "pyinstaller", "pip-audit"}
        assert not development & set(packages)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("MIT", {"license": {"id": "MIT"}}),
            ("BSD-3-Clause AND MIT", {"expression": "BSD-3-Clause AND MIT"}),
            ("BSD License", {"license": {"name": "BSD License"}}),
        ],
    )
    def test_licence_entries(self, metadata: object, text: str, expected: dict) -> None:  # type: ignore[type-arg]
        assert metadata._licence_entry(text) == expected  # type: ignore[attr-defined]

    def test_generated_sbom_validates(self, metadata: object) -> None:
        package = metadata.Package("example-lib", "1.0", direct=True, licence="MIT")  # type: ignore[attr-defined]
        child = metadata.Package(  # type: ignore[attr-defined]
            "child-lib", "2.0", direct=False, parents=["example-lib"], licence="BSD License"
        )
        sbom = metadata.build_sbom([package, child])  # type: ignore[attr-defined]
        metadata.validate_sbom(json.dumps(sbom))  # type: ignore[attr-defined]
        assert sbom["metadata"]["component"]["version"] == smartdrive.__version__
        graph = {d["ref"]: d["dependsOn"] for d in sbom["dependencies"]}
        assert graph["pkg:pypi/example-lib@1.0"] == ["pkg:pypi/child-lib@2.0"]
