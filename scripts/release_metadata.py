"""Release metadata: CycloneDX SBOM, third-party notices and build information.

The runtime dependency set is read from ``requirements.txt`` (the lock file) and filtered with
the *Windows x64* environment markers, so the SBOM and notices describe what the Windows build
ships, not the developer's whole virtual environment. Licence data and texts come from the
installed distributions; packages that only apply to Windows can be read from downloaded
wheels instead (``--wheel-dir``) when this runs on another operating system.

    python scripts/release_metadata.py sbom --output release/SmartDrive-Guardian-AI-v2.0.0-sbom.json
    python scripts/release_metadata.py notices --output THIRD_PARTY_NOTICES.md
    python scripts/release_metadata.py build-info --release-dir release \
        --output release/BUILD_INFORMATION.json
"""

from __future__ import annotations

import argparse
import email
import hashlib
import importlib.metadata as md
import json
import platform
import re
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smartdrive import APP_NAME, __version__  # noqa: E402

REPOSITORY = "https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI"
PROJECT_REQUIREMENT = "smartdrive-guardian-ai (pyproject.toml)"
WINDOWS_X64 = {
    "implementation_name": "cpython",
    "implementation_version": "3.12.10",
    "os_name": "nt",
    "platform_machine": "AMD64",
    "platform_python_implementation": "CPython",
    "platform_release": "10",
    "platform_system": "Windows",
    "platform_version": "10.0",
    "python_full_version": "3.12.10",
    "python_version": "3.12",
    "sys_platform": "win32",
}
LICENCE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/]*$", re.IGNORECASE)

# Components that are part of the Windows distribution but are not Python packages.
NON_PYTHON_COMPONENTS: list[dict[str, str]] = [
    {
        "name": "CPython runtime",
        "version": "3.12 (as used for the build)",
        "licence": "PSF-2.0",
        "note": "python312.dll and the standard library are bundled by PyInstaller.",
    },
    {
        "name": "Qt 6 (via PySide6-Essentials)",
        "version": "6.12",
        "licence": "LGPL-3.0-only",
        "note": "Qt libraries are shipped as separate, unmodified DLLs in the one-folder build, "
        "so they can be replaced by the user. Source: https://download.qt.io/",
    },
    {
        "name": "PyInstaller bootloader",
        "version": "6.22",
        "licence": "GPL-2.0-or-later WITH Bootloader-exception",
        "note": "The bootloader exception permits distributing the executable under the "
        "application's own licence.",
    },
    {
        "name": "Inno Setup (installer only)",
        "version": "6",
        "licence": "Inno Setup License",
        "note": "Used to build the installer; its licence permits distributing installers "
        "it creates, including commercially. Not part of the installed application.",
    },
]


@dataclass(slots=True)
class Package:
    name: str
    version: str
    direct: bool
    parents: list[str] = field(default_factory=list)
    licence: str = ""
    summary: str = ""
    homepage: str = ""
    licence_texts: dict[str, str] = field(default_factory=dict)
    source: str = ""


def _marker_matches(marker: Marker | None) -> bool:
    return marker is None or marker.evaluate(WINDOWS_X64)  # type: ignore[arg-type]


def read_lock(path: Path) -> list[Package]:
    """Packages of a uv/pip-compile lock file that apply to Windows x64, with their parents."""
    packages: list[Package] = []
    current: Package | None = None
    for raw in path.read_text("utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        if not raw.startswith(" "):
            requirement = Requirement(raw.split(" #")[0].strip())
            if not _marker_matches(requirement.marker):
                current = None
                continue
            version = next(iter(requirement.specifier)).version
            current = Package(canonicalize_name(requirement.name), version, direct=False)
            packages.append(current)
            continue
        if current is None:
            continue
        text = raw.strip().lstrip("#").strip()
        if text in {"via", ""}:
            continue
        text = text.removeprefix("via ").strip()
        if text.startswith("-c ") or text.startswith("-r "):
            continue
        if text == PROJECT_REQUIREMENT:
            current.direct = True
        else:
            current.parents.append(canonicalize_name(text.split(" ")[0]))
    names = {p.name for p in packages}
    for package in packages:
        package.parents = [p for p in package.parents if p in names]
    return packages


def _licence_from_metadata(meta: Message) -> str:
    expression = meta.get("License-Expression")
    if expression and expression.strip().upper() != "UNKNOWN":
        return expression.strip()
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    if classifiers:
        return " / ".join(classifiers)
    text = (meta.get("License") or "").strip()
    if not text or text.upper() == "UNKNOWN":
        return "See licence text"
    return text.splitlines()[0][:80]


def _homepage(meta: Message) -> str:
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in {"homepage", "home", "source", "repository", "source code"}:
            return url.strip()
    return (meta.get("Home-page") or "").strip()


def _from_installed(package: Package) -> bool:
    try:
        dist = md.distribution(package.name)
    except md.PackageNotFoundError:
        return False
    if canonicalize_name(dist.metadata["Name"]) != package.name or dist.version != package.version:
        raise SystemExit(
            f"{package.name}: installed {dist.version}, lock file pins {package.version}. "
            "Install the pinned requirements before generating release metadata."
        )
    meta = dist.metadata
    package.licence = _licence_from_metadata(meta)  # type: ignore[arg-type]
    package.summary = (meta.get("Summary") or "").strip()
    package.homepage = _homepage(meta)  # type: ignore[arg-type]
    for file in dist.files or []:
        if LICENCE_FILE.search(str(file)):
            path = Path(str(file.locate()))
            if path.is_file():
                package.licence_texts[str(file)] = path.read_text("utf-8", errors="replace")
    package.source = "installed distribution"
    return True


def _from_wheel(package: Package, wheel_dir: Path | None) -> bool:
    if wheel_dir is None:
        return False
    stem = package.name.replace("-", "_")
    for wheel in sorted(wheel_dir.glob("*.whl")):
        name, version = wheel.name.split("-")[:2]
        if canonicalize_name(name) != package.name or version != package.version:
            continue
        with zipfile.ZipFile(wheel) as archive:
            meta_name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            meta = email.message_from_bytes(archive.read(meta_name))
            package.licence = _licence_from_metadata(meta)
            package.summary = (meta.get("Summary") or "").strip()
            package.homepage = _homepage(meta)
            for member in archive.namelist():
                if ".dist-info/" in member and LICENCE_FILE.search(member):
                    package.licence_texts[member] = archive.read(member).decode(
                        "utf-8", errors="replace"
                    )
        package.source = f"wheel {wheel.name}"
        return True
    del stem
    return False


def collect(lock: Path, wheel_dir: Path | None) -> list[Package]:
    packages = read_lock(lock)
    missing = [p.name for p in packages if not (_from_installed(p) or _from_wheel(p, wheel_dir))]
    if missing:
        raise SystemExit(
            "No metadata for: " + ", ".join(missing) + ". Run on Windows with the pinned "
            "requirements installed, or pass --wheel-dir with their downloaded wheels."
        )
    return sorted(packages, key=lambda p: p.name)


def _purl(package: Package) -> str:
    return f"pkg:pypi/{package.name}@{package.version}"


def _licence_entry(expression: str) -> dict[str, Any]:
    """A CycloneDX licence entry: SPDX id, SPDX expression, or a free-text name."""
    from license_expression import ExpressionError, get_spdx_licensing

    licensing = get_spdx_licensing()
    try:
        info = licensing.validate(expression, strict=True)
    except ExpressionError:
        info = None
    if info is not None and not info.errors and not info.invalid_symbols:
        normalised = info.normalized_expression or expression
        if len(licensing.license_keys(normalised)) == 1 and " " not in normalised:
            return {"license": {"id": normalised}}
        return {"expression": normalised}
    return {"license": {"name": expression}}


def build_sbom(packages: list[Package]) -> dict[str, Any]:
    app_ref = f"pkg:github/hiranya-bandara/smartdrive-guardian-ai@v{__version__}"
    components = []
    for package in packages:
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": _purl(package),
            "name": package.name,
            "version": package.version,
            "purl": _purl(package),
            "scope": "required",
        }
        if package.licence:
            component["licenses"] = [_licence_entry(package.licence)]
        if package.homepage:
            component["externalReferences"] = [{"type": "website", "url": package.homepage}]
        components.append(component)
    by_name = {p.name: p for p in packages}
    dependencies = [
        {"ref": app_ref, "dependsOn": sorted(_purl(p) for p in packages if p.direct)},
    ]
    for package in packages:
        children = sorted(_purl(c) for c in packages if package.name in c.parents)
        dependencies.append({"ref": _purl(package), "dependsOn": children})
    del by_name
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "scripts/release_metadata.py",
                        "version": __version__,
                    }
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": app_ref,
                "name": APP_NAME,
                "version": __version__,
                "purl": app_ref,
                "licenses": [{"license": {"id": "MIT"}}],
                "externalReferences": [{"type": "vcs", "url": REPOSITORY}],
            },
            "properties": [
                {"name": "smartdrive:target", "value": "Windows x64, Python 3.12"},
                {"name": "smartdrive:scope", "value": "Runtime dependencies (requirements.txt)"},
                {
                    "name": "smartdrive:excluded",
                    "value": "Development, test and build tools are not shipped and not listed.",
                },
            ],
        },
        "components": components,
        "dependencies": dependencies,
    }


def validate_sbom(text: str) -> None:
    from cyclonedx.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator

    error = JsonStrictValidator(SchemaVersion.V1_6).validate_str(text)
    if error is not None:
        raise SystemExit(f"SBOM failed CycloneDX 1.6 schema validation: {error}")


NOTICES_HEADER = """# Third-party notices

{app} {version} is distributed under the MIT License (see `LICENSE`). The Windows distribution
also contains the third-party software listed below, each under its own licence. This file is
generated by `scripts/release_metadata.py notices` from the pinned runtime dependencies for
Windows x64; the full licence texts shipped by each package follow the summary table.

This is an engineering inventory, not legal advice. See `docs/licensing.md` for the review
notes and open questions.

## Components that are not Python packages

| Component | Version | Licence | Notes |
|---|---|---|---|
{non_python}

## Original project assets

* Application icons, logo and installer artwork: created for this project (see
  `scripts/build_brand_assets.py`); MIT License with the rest of the project. The wordmark in
  the raster and outlined-SVG logos was drawn from DejaVu Sans (Bitstream Vera licence, which
  permits this); no font file is distributed.
* Machine-learning models (`ai/artifacts`): trained by this project on its own synthetic
  dataset; MIT License.
* Diagnostic trouble code descriptions: short descriptions written for this project in its
  own words for generic SAE J2012 codes; the SAE standard itself is not reproduced.

## Python packages ({count})

| Package | Version | Licence | Required by |
|---|---|---|---|
{rows}

## Licence texts
"""


def build_notices(packages: list[Package]) -> str:
    non_python = "\n".join(
        f"| {c['name']} | {c['version']} | {c['licence']} | {c['note']} |"
        for c in NON_PYTHON_COMPONENTS
    )
    rows = "\n".join(
        f"| {p.name} | {p.version} | {p.licence.replace('|', '/')} | "
        f"{'SmartDrive Guardian AI' if p.direct else ', '.join(p.parents)} |"
        for p in packages
    )
    parts = [
        NOTICES_HEADER.format(
            app=APP_NAME,
            version=__version__,
            non_python=non_python,
            count=len(packages),
            rows=rows,
        )
    ]
    for package in packages:
        parts.append(f"\n### {package.name} {package.version}\n")
        if package.homepage:
            parts.append(f"\nHomepage: {package.homepage}\n")
        if not package.licence_texts:
            parts.append(f"\nLicence: {package.licence} (no licence file in the distribution).\n")
        for name, text in sorted(package.licence_texts.items()):
            clean = text.replace("\r\n", "\n").replace("\r", "\n").strip()
            parts.append(f"\n`{Path(name).name}`\n\n```text\n{clean}\n```\n")
    return "".join(parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed arguments
            ["git", *args],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def build_info(release_dir: Path | None) -> dict[str, Any]:
    manifest = json.loads((ROOT / "src/smartdrive/ai/artifacts/manifest.json").read_text("utf-8"))
    info: dict[str, Any] = {
        "application": APP_NAME,
        "version": __version__,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "build_platform": platform.platform(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "tools": {},
        "lock_files_sha256": {
            name: _sha256(ROOT / name)
            for name in ("requirements.txt", "requirements-dev.txt", "requirements-release.txt")
            if (ROOT / name).is_file()
        },
        "models": [
            {k: m.get(k) for k in ("name", "version", "sha256", "sklearn_version")}
            for m in manifest.get("models", [])
        ],
        "code_signing": "unsigned",
        "artifacts": [],
    }
    for tool in ("pyinstaller", "pyside6-essentials", "scikit-learn"):
        try:
            info["tools"][tool] = md.version(tool)
        except md.PackageNotFoundError:
            info["tools"][tool] = None
    if release_dir is not None and release_dir.is_dir():
        for path in sorted(release_dir.iterdir()):
            if path.is_file() and path.name not in {"BUILD_INFORMATION.json", "SHA256SUMS.txt"}:
                info["artifacts"].append(
                    {"file": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}
                )
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("sbom", "notices"):
        command = sub.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--lock", type=Path, default=ROOT / "requirements.txt")
        command.add_argument("--wheel-dir", type=Path)
    info = sub.add_parser("build-info")
    info.add_argument("--output", type=Path, required=True)
    info.add_argument("--release-dir", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "build-info":
        text = json.dumps(build_info(args.release_dir), indent=2)
    else:
        packages = collect(args.lock, args.wheel_dir)
        if args.command == "sbom":
            text = json.dumps(build_sbom(packages), indent=2)
            validate_sbom(text)
        else:
            text = build_notices(packages)
    args.output.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
