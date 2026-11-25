# PyInstaller specification for SmartDrive Guardian AI (one-folder, windowed).
#
# Build with scripts/build-windows.ps1 (or: python -m PyInstaller packaging/smartdrive.spec
# --noconfirm --clean --distpath dist --workpath build/pyinstaller). The version comes from
# smartdrive.__version__ (single source); the Windows version resource is generated from it.
#
# One-folder is used deliberately: PySide6, NumPy/SciPy/scikit-learn and the model artifacts are
# large, and a one-file build would unpack all of them to a temporary folder on every start.
# ruff: noqa
# mypy: ignore-errors

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()  # noqa: F821 - defined by PyInstaller
ROOT = SPEC_DIR.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from smartdrive import APP_NAME, __version__  # noqa: E402

EXE_NAME = "SmartDrive-Guardian-AI"
IS_WINDOWS = sys.platform == "win32"
ICON = ROOT / "src" / "smartdrive" / "branding" / "smartdrive-icon.ico"

# --- Python modules ------------------------------------------------------------------------
# The training-time reporting module needs matplotlib and is never imported by the app.
TRAINING_ONLY = {"smartdrive.ai.reporting"}
hiddenimports = collect_submodules("smartdrive", filter=lambda name: name not in TRAINING_ONLY)
# Model artifacts are joblib pickles of these scikit-learn classes; they are imported by name
# when the trusted, checksum-verified artifact is loaded.
hiddenimports += [
    "sklearn.ensemble._forest",
    "sklearn.ensemble._iforest",
    "sklearn.tree._classes",
    "sklearn.tree._tree",
    "sklearn.utils._typedefs",
    "sklearn.neighbors._partition_nodes",
    # pyqtgraph imports these with importlib at run time (found by the frozen GUI smoke test).
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    # Alembic migration scripts import these at run time from data files.
    "alembic.op",
    "sqlalchemy.dialects.sqlite",
    # Offline speech: pyttsx3 picks its driver module dynamically.
    "pyttsx3.drivers",
    "pyttsx3.drivers.dummy",
]
if IS_WINDOWS:
    hiddenimports += ["pyttsx3.drivers.sapi5", "comtypes.client", "win32com", "pythoncom"]
else:
    hiddenimports += ["pyttsx3.drivers.espeak"]

# --- Read-only data files ------------------------------------------------------------------
# Migration scripts must stay .py files on disk: Alembic loads them from the versions folder.
datas = collect_data_files(
    "smartdrive",
    include_py_files=True,
    includes=[
        "py.typed",
        "ui/themes/*.qss",
        "branding/*.svg",
        "branding/*.png",
        "branding/*.ico",
        "ai/artifacts/manifest.json",
        "ai/artifacts/evaluation_metrics.json",
        "ai/artifacts/*.joblib",
        "database/migrations/env.py",
        "database/migrations/script.py.mako",
        "database/migrations/versions/*.py",
    ],
)

# Build and test tools, and optional imports of runtime packages, that may be present in the
# build environment but are not part of the runtime dependency set (requirements.txt / SBOM).
excludes = [
    "matplotlib",
    "chardet",
    "tomli",
    "attr",
    "attrs",
    "pydantic.mypy",
    "pydantic.v1.mypy",
    "setuptools",
    "pkg_resources",
    "pip",
    "cyclonedx",
    "piplicenses",
    "lxml",
    "jsonschema",
    "tkinter",
    "_tkinter",
    "IPython",
    "pytest",
    "pytest_qt",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "mypy",
    "ruff",
    "pip_audit",
    "PyInstaller",
    # PySide6 modules the application does not use.
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDBus",
    "PySide6.QtConcurrent",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtXml",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
]

a = Analysis(  # noqa: F821
    [str(SPEC_DIR / "launch.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

version_resource = None
if IS_WINDOWS:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(int(part) for part in __version__.split(".")[:3]) + (0,)
    version_resource = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, OS=0x40004, fileType=0x1),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Hiranya Bandara"),
                            StringStruct(
                                "FileDescription",
                                f"{APP_NAME} - offline vehicle diagnostics assistant",
                            ),
                            StringStruct("FileVersion", __version__),
                            StringStruct("InternalName", EXE_NAME),
                            StringStruct("LegalCopyright", "Copyright (c) 2026 Hiranya Bandara. MIT License."),
                            StringStruct("OriginalFilename", f"{EXE_NAME}.exe"),
                            StringStruct("ProductName", APP_NAME),
                            StringStruct("ProductVersion", __version__),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
    # Written for inspection and review; the build uses the object above.
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build" / "windows-version-info.txt").write_text(str(version_resource), "utf-8")

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed executables are flagged by antivirus heuristics more often.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if IS_WINDOWS else None,
    version=version_resource,
    uac_admin=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=EXE_NAME,
)
