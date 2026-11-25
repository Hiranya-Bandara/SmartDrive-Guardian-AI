"""First-run guide: operating modes, AI limitations, driving safety and where data is kept.

Shown once when the application starts with a new (or upgraded) settings file, and again on
request from the About page. Non-blocking (``open()``), so it never stalls start-up or the
automated smoke tests. It does not connect to anything and needs no internet access.
"""

from __future__ import annotations

import contextlib
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from smartdrive import APP_NAME, APP_TAGLINE, __version__
from smartdrive.ui.context import UiContext
from smartdrive.ui.icons import brand_pixmap
from smartdrive.ui.widgets.base import label
from smartdrive.utils.exceptions import SmartDriveError

DOCS_URL: Final = (
    "https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI/blob/main/docs/user-guide.md"
)

SECTIONS: Final[tuple[tuple[str, str], ...]] = (
    (
        "Start with simulation",
        "Simulation mode needs no hardware. Pick a documented scenario in the Simulation Lab "
        "or start monitoring from the dashboard. Every simulated value is labelled as "
        "simulated.",
    ),
    (
        "Live vehicle mode is read-only and unverified",
        "With an ELM327-compatible adapter you choose on the Vehicle Connection page, the "
        "application only reads data and trouble codes. It never clears codes, programs or "
        "controls the vehicle, and it never connects on its own. Communication with physical "
        "adapters and vehicles has not yet been verified.",
    ),
    (
        "AI findings are experimental",
        "Rules, machine-learning predictions and trouble codes are shown separately. The "
        "models were trained and evaluated on simulated data only; their accuracy on real "
        "vehicles is unknown. Machine learning on live data is off unless you enable it in "
        "Settings. A finding is not a confirmed fault, and no finding does not mean the "
        "vehicle is safe.",
    ),
    (
        "Do not use the application while driving",
        "Set up monitoring while parked, or let a passenger use it. For any warning sign on the "
        "road, stop safely and consult a qualified mechanic.",
    ),
    (
        "Your data stays on this computer",
        "No account, no internet connection and no telemetry. Vehicles, trips, maintenance "
        "records and settings are stored locally (see About for the folder). Reports are "
        "written only where you choose.",
    ),
)


class WelcomeDialog(QDialog):
    def __init__(self, ctx: UiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.setObjectName("WelcomeDialog")
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(brand_pixmap(56, self.devicePixelRatioF()))
        header.addWidget(logo)
        titles = QVBoxLayout()
        title = label(f"{APP_NAME} {__version__}", "section-title")
        titles.addWidget(title)
        titles.addWidget(label(APP_TAGLINE, "muted"))
        header.addLayout(titles, 1)
        layout.addLayout(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        body_layout.setSpacing(4)
        for index, (heading, text) in enumerate(SECTIONS):
            if index:
                body_layout.addSpacing(10)
            body_layout.addWidget(label(heading, "card-title"))
            paragraph = label(text, wrap=True)
            paragraph.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body_layout.addWidget(paragraph)
        help_text = label(
            f'Help: the <a href="{DOCS_URL}">user guide</a> (online) and the About page.',
            "muted",
            wrap=True,
        )
        help_text.setOpenExternalLinks(True)
        body_layout.addSpacing(10)
        body_layout.addWidget(help_text)
        body_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        self.show_again = QCheckBox("Show this guide when the application starts")
        self.show_again.setChecked(False)
        layout.addWidget(self.show_again)
        buttons = QDialogButtonBox()
        self.start_button = buttons.addButton("Get started", QDialogButtonBox.ButtonRole.AcceptRole)
        self.start_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.resize(640, 640)

    def done(self, result: int) -> None:
        """Remember the choice however the dialog is closed (button, Esc or window close)."""
        settings = self._ctx.app.settings
        seen = not self.show_again.isChecked()
        if settings.general.welcome_seen != seen:
            settings.general.welcome_seen = seen
            # A failed save is already logged; the guide then simply appears again next time.
            with contextlib.suppress(SmartDriveError):
                self._ctx.state.save_settings()
        super().done(result)


def show_welcome(ctx: UiContext, parent: QWidget | None = None) -> WelcomeDialog:
    dialog = WelcomeDialog(ctx, parent)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()
    return dialog
