"""About: version, safety disclaimer, environment, feature availability and licences."""

from __future__ import annotations

import platform
import sqlite3
from importlib.metadata import PackageNotFoundError, version

import PySide6
from PySide6.QtCore import Qt, qVersion
from PySide6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QLabel

from smartdrive import APP_NAME, APP_TAGLINE, __version__
from smartdrive.config.constants import SAFETY_DISCLAIMER
from smartdrive.ui.context import UiContext
from smartdrive.ui.icons import pixmap
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
    ("AI diagnostics and health score", "Phase 3", StatusLevel.OFFLINE),
    ("OBD-II live vehicle connection", "Phase 4", StatusLevel.OFFLINE),
    ("Trip analytics and replay", "Phase 4", StatusLevel.OFFLINE),
    ("Maintenance centre", "Phase 4", StatusLevel.OFFLINE),
    ("Alert centre and notifications", "Phase 4", StatusLevel.OFFLINE),
    ("PDF and CSV reports", "Phase 4", StatusLevel.OFFLINE),
)

THIRD_PARTY = (
    ("PySide6 / Qt", "LGPL-3.0"),
    ("PyQtGraph", "MIT"),
    ("NumPy", "BSD-3-Clause"),
    ("SQLAlchemy", "MIT"),
    ("Alembic", "MIT"),
    ("Pydantic", "MIT"),
    ("platformdirs", "MIT"),
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
        details.addRow(label(f"Version {__version__} · Experimental", "muted"))
        row.addWidget(self.logo)
        row.addLayout(details, 1)
        hero.body.addLayout(row)
        self.content.addWidget(hero)
        self.content.addWidget(Banner(SAFETY_DISCLAIMER, StatusLevel.WARNING))

        grid = QGridLayout()
        grid.setSpacing(16)
        features = Card("Feature availability")
        for name, status, level in FEATURES:
            line = QHBoxLayout()
            line.addWidget(label(name), 1)
            line.addWidget(StatusIndicator(status, level))
            features.body.addLayout(line)
        grid.addWidget(features, 0, 0, 2, 1)

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
            ("Machine-learning models", "None installed (diagnostic engine: Phase 3)"),
        ):
            value_label = label(value, wrap=True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label(title, "muted"), value_label)
        environment.body.addLayout(form)
        grid.addWidget(environment, 0, 1)

        licences = Card("Licences")
        licences.body.addWidget(
            label(
                "SmartDrive Guardian AI is released under the MIT licence (pending owner "
                "approval). Icons are original artwork. Third-party components:",
                "muted",
                wrap=True,
            )
        )
        for name, licence in THIRD_PARTY:
            line = QHBoxLayout()
            line.addWidget(label(name), 1)
            line.addWidget(label(licence, "muted"))
            licences.body.addLayout(line)
        grid.addWidget(licences, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.content.addLayout(grid)
        self.content.addStretch(1)

    def apply_palette(self, palette: ThemePalette) -> None:
        self.logo.setPixmap(pixmap("shield", palette.accent, 64))
