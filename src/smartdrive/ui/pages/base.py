from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from smartdrive.ui.context import UiContext
from smartdrive.ui.themes.palette import ThemePalette


class Page(QWidget):
    """A navigable page. Content scrolls so every page works at 1366×768."""

    key: str = ""
    title: str = ""
    subtitle: str = ""

    def __init__(self, ctx: UiContext, *, scrollable: bool = True) -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName(f"Page_{self.key}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setObjectName("AppRoot")
        self.content = QVBoxLayout(inner)
        self.content.setContentsMargins(24, 20, 24, 24)
        self.content.setSpacing(16)
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(inner)
            outer.addWidget(scroll)
        else:
            outer.addWidget(inner)

    def on_shown(self) -> None:
        """Called whenever the page becomes visible."""

    def apply_palette(self, palette: ThemePalette) -> None:
        """Pages with custom-painted content override this."""
