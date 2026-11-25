"""Entry point of the packaged Windows executable (``SmartDrive-Guardian-AI.exe``).

The executable is built as a windowed (GUI) program, so it has no console: ``sys.stdout`` and
``sys.stderr`` are ``None``. They are pointed at the null device so that nothing which writes to
them can fail; diagnostics go to the log file. Started without a command (double-click, Start
Menu shortcut) it opens the desktop application; the maintenance commands remain available,
e.g. ``SmartDrive-Guardian-AI.exe self-test --report result.json`` used by the build scripts.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

COMMANDS: Final = frozenset({"info", "gui", "db", "settings", "self-test"})
PASSTHROUGH_FLAGS: Final = frozenset({"-h", "--help", "--version"})
# A plain flag (not an inline sys.platform check) so the Windows branch is type-checked and
# testable everywhere.
_IS_WINDOWS: Final = sys.platform == "win32"


def _parent_console_output() -> str | None:
    """On Windows, attach to the console of the process that started us (cmd, PowerShell).

    Returns the device to write to, or None when there is no such console (started from
    Explorer or a shortcut). Best effort: output of commands such as ``info`` then appears in
    the terminal; ``self-test --report`` writes a file and does not depend on it.
    """
    if not _IS_WINDOWS:
        return None
    try:
        import ctypes

        attach_parent_process = -1
        if ctypes.windll.kernel32.AttachConsole(attach_parent_process):  # type: ignore[attr-defined,unused-ignore]
            return "CONOUT$"
    except (AttributeError, OSError):
        return None
    return None


def ensure_standard_streams() -> None:
    """Give a windowed process writable stdout/stderr: the parent console or the null device."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    target = _parent_console_output() or os.devnull
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, Path(target).open("w", encoding="utf-8"))  # noqa: SIM115


def default_arguments(argv: Sequence[str]) -> list[str]:
    """Add the ``gui`` command when none was given (global options such as --home are kept)."""
    args = list(argv)
    if any(arg in COMMANDS or arg in PASSTHROUGH_FLAGS for arg in args):
        return args
    return [*args, "gui"]


def main(argv: Sequence[str] | None = None) -> int:
    # scikit-learn/joblib may start worker processes; in a frozen program each would otherwise
    # re-run the application instead of the worker.
    multiprocessing.freeze_support()
    ensure_standard_streams()
    from smartdrive.cli import main as cli_main

    return cli_main(default_arguments(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
