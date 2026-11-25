"""About: version, developer, limitations, privacy, environment, features and licences."""

from __future__ import annotations

import platform
import sqlite3
from importlib.metadata import PackageNotFoundError, version

import PySide6
from PySide6.QtCore import Qt, qVersion
from PySide6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QLabel, QPushButton

from smartdrive import APP_NAME, APP_TAGLINE, __version__
from smartdrive.ai.model_registry import ModelRegistry
from smartdrive.config.constants import SAFETY_DISCLAIMER
from smartdrive.ui.context import UiContext
from smartdrive.ui.dialogs.welcome import show_welcome
from smartdrive.ui.icons import brand_pixmap
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.notifications import Banner
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel

FEATURES: tuple[tuple[str, str, StatusLevel], ...] = (
    ("Dashboard and live monitoring", "Available", StatusLevel.NORMAL),
    ("Vehicle garage", "Available", StatusLevel.NORMAL),
    ("Simulation laboratory", "Available", StatusLevel.NORMAL),
    ("AI diagnostics and experimental health score", "Available", StatusLevel.NORMAL),
    (
        "Read-only OBD-II connection and trouble codes",
        "Available — physical adapters not yet verified",
        StatusLevel.WARNING,
    ),
    ("Trip history and replay", "Available", StatusLevel.NORMAL),
    ("Maintenance centre", "Available", StatusLevel.NORMAL),
    ("Alert centre, desktop and voice notifications", "Available", StatusLevel.NORMAL),
    ("PDF and CSV reports", "Available", StatusLevel.NORMAL),
)

THIRD_PARTY = (
    ("PySide6 / Qt", "LGPL-3.0"),
    ("PyQtGraph", "MIT"),
    ("NumPy", "BSD-3-Clause"),
    ("scikit-learn", "BSD-3-Clause"),
    ("SciPy", "BSD-3-Clause"),
    ("joblib", "BSD-3-Clause"),
    ("SQLAlchemy", "MIT"),
    ("Alembic", "MIT"),
    ("Pydantic", "MIT"),
    ("platformdirs", "MIT"),
    ("pySerial", "BSD-3-Clause"),
    ("ReportLab", "BSD"),
    ("Pillow", "MIT-CMU"),
    ("pyttsx3", "MPL-2.0"),
    ("comtypes", "MIT (Windows)"),
    ("pywin32", "PSF (Windows)"),
)


DEVELOPER = "Hiranya Bandara"
REPOSITORY = "https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI"

LIMITATIONS = (
    "Educational and informational software. Not a certified automotive diagnostic or safety "
    "system, and it cannot confirm that a vehicle is safe to drive.",
    "Machine-learning models were trained and evaluated on simulated data only. Their "
    "accuracy on real vehicles has not been measured.",
    "OBD-II access is read-only (no clearing codes, programming or control). Physical "
    "adapters and vehicles have not yet been verified; compatibility varies by vehicle.",
    "A trouble code or finding is not a confirmed failed part; consult a qualified mechanic.",
    "Do not operate the application while driving.",
)
PRIVACY = (
    "Works offline: no account, no telemetry, no analytics and no automatic uploads.",
    "Vehicles, trips, maintenance, notifications and settings are stored only in the data "
    "folder shown under Environment. Reports are written only where you choose.",
    "Registration numbers and VINs are left out of reports unless you enable them.",
)


def _bullets(lines: tuple[str, ...]) -> QLabel:
    widget = label("<br>".join(f"•&nbsp;{line}" for line in lines), wrap=True)
    widget.setTextFormat(Qt.TextFormat.RichText)
    return widget


def _model_summary() -> str:
    manifest = ModelRegistry().manifest()
    if not manifest:
        return "No trusted models installed (rule engine only)"
    return ", ".join(
        f"{entry['name'].replace('_', ' ')} {entry['version']} "
        f"(dataset {entry['dataset_version']}, synthetic)"
        for entry in manifest.values()
    )


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


class AboutPage(Page):
    key = "about"
    title = "About"
    subtitle = f"{APP_NAME} {__version__}"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        hero = Card()
        row = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = label(f"{APP_NAME}", "section-title")
        text.setStyleSheet("font-size: 20pt;")
        details = QFormLayout()
        details.addRow(text)
        details.addRow(label(APP_TAGLINE, "muted"))
        details.addRow(label(f"Version {__version__} · Educational software", "muted"))
        developer = label(
            f'Developed by {DEVELOPER} · <a href="{REPOSITORY}">GitHub repository</a> · '
            "MIT License",
            "muted",
        )
        developer.setOpenExternalLinks(True)
        details.addRow(developer)
        self.welcome_button = QPushButton("Show welcome guide")
        self.welcome_button.clicked.connect(self._show_welcome)
        button_row = QHBoxLayout()
        button_row.addWidget(self.welcome_button)
        button_row.addStretch(1)
        details.addRow(button_row)
        row.addWidget(self.logo)
        row.addLayout(details, 1)
        hero.body.addLayout(row)
        self.content.addWidget(hero)
        self.content.addWidget(Banner(SAFETY_DISCLAIMER, StatusLevel.WARNING))

        grid = QGridLayout()
        grid.setSpacing(16)
        limitations = Card("Diagnostic and hardware limitations")
        limitations.body.addWidget(_bullets(LIMITATIONS))
        grid.addWidget(limitations, 0, 0)
        privacy = Card("Privacy")
        privacy.body.addWidget(_bullets(PRIVACY))
        grid.addWidget(privacy, 0, 1)
        features = Card("Feature availability")
        for name, status, level in FEATURES:
            line = QHBoxLayout()
            line.addWidget(label(name), 1)
            line.addWidget(StatusIndicator(status, level))
            features.body.addLayout(line)
        features.body.addStretch(1)
        grid.addWidget(features, 1, 0, 2, 1)

        environment = Card("Environment")
        form = QFormLayout()
        paths = ctx.app.paths
        for title, value in (
            ("Python", platform.python_version()),
            ("Qt / PySide6", f"{qVersion()} / {PySide6.__version__}"),
            ("PyQtGraph", _package_version("pyqtgraph")),
            ("SQLite", sqlite3.sqlite_version),
            ("Operating system", platform.platform(terse=True)),
            ("Database schema", str(ctx.app.database.current_revision())),
            ("Data folder", str(paths.data_dir)),
            ("Log file", str(paths.log_file)),
            ("Machine-learning models", _model_summary()),
        ):
            value_label = label(value, wrap=True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label(title, "muted"), value_label)
        environment.body.addLayout(form)
        grid.addWidget(environment, 1, 1)

        licences = Card("Licences")
        licences.body.addWidget(
            label(
                "SmartDrive Guardian AI is released under the MIT License. The logo, icons and "
                "models are original to this project. Full licence texts of the components "
                "below are in THIRD_PARTY_NOTICES.md (installation folder or repository).",
                "muted",
                wrap=True,
            )
        )
        for name, licence in THIRD_PARTY:
            line = QHBoxLayout()
            line.addWidget(label(name), 1)
            line.addWidget(label(licence, "muted"))
            licences.body.addLayout(line)
        grid.addWidget(licences, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.content.addLayout(grid)
        self.content.addStretch(1)

    def _show_welcome(self) -> None:
        show_welcome(self.ctx, self.window())

    def apply_palette(self, palette: ThemePalette) -> None:
        self.logo.setPixmap(brand_pixmap(72, self.devicePixelRatioF()))
