"""Status pills: a coloured dot plus explicit text, so status never relies on colour alone."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from smartdrive.ui.themes.palette import DARK, ThemePalette


class StatusLevel(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    OFFLINE = "offline"
    INFO = "info"
    SIMULATION = "simulation"


def level_colour(palette: ThemePalette, level: StatusLevel) -> str:
    return {
        StatusLevel.NORMAL: palette.normal,
        StatusLevel.WARNING: palette.warning,
        StatusLevel.CRITICAL: palette.critical,
        StatusLevel.OFFLINE: palette.offline,
        StatusLevel.INFO: palette.accent,
        StatusLevel.SIMULATION: palette.simulation,
    }[level]


class _Dot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.colour = QColor(DARK.offline)
        self.setFixedSize(QSize(10, 10))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.colour)
        painter.setBrush(self.colour)
        painter.drawEllipse(1, 1, 8, 8)
        painter.end()


class StatusIndicator(QFrame):
    def __init__(
        self,
        text: str = "",
        level: StatusLevel = StatusLevel.OFFLINE,
        *,
        prefix: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "status-pill")
        self._palette = DARK
        self._level = level
        self._prefix = prefix
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 12, 4)
        layout.setSpacing(7)
        self._dot = _Dot(self)
        self._label = QLabel(self)
        layout.addWidget(self._dot)
        layout.addWidget(self._label)
        self.set_status(text, level)

    @property
    def level(self) -> StatusLevel:
        return self._level

    @property
    def text(self) -> str:
        return self._label.text()

    def set_status(self, text: str, level: StatusLevel) -> None:
        self._level = level
        shown = f"{self._prefix}{text}"
        self._label.setText(shown)
        self.setAccessibleName(shown)
        self.setToolTip(shown)
        self._refresh()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self._refresh()

    def _refresh(self) -> None:
        self._dot.colour = QColor(level_colour(self._palette, self._level))
        self._dot.update()
