"""Read-only resources bundled with the application.

Everything here is resolved through :mod:`importlib.resources` relative to the ``smartdrive``
package, so the same code works from a source checkout, an installed wheel and a PyInstaller
build (where the package data is unpacked beside the frozen modules). Resources are never
written to; mutable data lives in the per-user folders from :mod:`smartdrive.config.paths`.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Final

APP_ICON_SVG: Final = ("branding", "smartdrive-icon.svg")
APP_ICON_SMALL_SVG: Final = ("branding", "smartdrive-icon-small.svg")
APP_ICON_ICO: Final = ("branding", "smartdrive-icon.ico")
APP_ICON_PNG: Final = ("branding", "smartdrive-icon-256.png")

REQUIRED: Final[tuple[tuple[str, ...], ...]] = (
    APP_ICON_SVG,
    APP_ICON_SMALL_SVG,
    APP_ICON_ICO,
    APP_ICON_PNG,
    ("ui", "themes", "stylesheet.qss"),
    ("database", "migrations", "env.py"),
    ("database", "migrations", "script.py.mako"),
    ("ai", "artifacts", "manifest.json"),
)


def resource_path(*parts: str) -> Path:
    """Filesystem path of a bundled resource (it may not exist; see :func:`missing_resources`)."""
    if not parts or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts):
        raise ValueError(f"Invalid resource path: {parts!r}")
    return Path(str(files("smartdrive").joinpath(*parts)))


def migration_scripts() -> list[Path]:
    return sorted(resource_path("database", "migrations", "versions").glob("*.py"))


def missing_resources() -> list[str]:
    """Names of required resources that are absent, for the self-test and startup checks."""
    missing = ["/".join(parts) for parts in REQUIRED if not resource_path(*parts).is_file()]
    manifest = resource_path("ai", "artifacts", "manifest.json")
    if manifest.is_file():
        for entry in json.loads(manifest.read_text("utf-8")).get("models", []):
            name = Path(str(entry.get("file", ""))).name
            if not name or not resource_path("ai", "artifacts", name).is_file():
                missing.append(f"ai/artifacts/{name or '?'}")
    if not migration_scripts():
        missing.append("database/migrations/versions/*.py")
    return missing
