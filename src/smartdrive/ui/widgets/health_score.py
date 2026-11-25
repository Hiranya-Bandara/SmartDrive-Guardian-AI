"""Experimental health score ring. The score is always labelled experimental and shows an
explicit unavailable state instead of a number when there is not enough evidence."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from smartdrive.core.units import MISSING_TEXT
from smartdrive.models.diagnostic import HealthScore
from smartdrive.ui.themes.palette import DARK, ThemePalette


def score_colour(palette: ThemePalette, score: int | None) -> str:
    if score is None:
        return palette.offline
    if score >= 85:
        return palette.normal
    if score >= 60:
        return palette.accent
    if score >= 30:
        return palette.warning
    return palette.critical


class HealthScoreWidget(QWidget):
    def __init__(self, *, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = DARK
        self._health: HealthScore | None = None
        self._compact = compact
        side = 120 if compact else 170
        self.setMinimumSize(side, side + 18)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Experimental vehicle health score")
        self._update_text()

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    @property
    def health(self) -> HealthScore | None:
        return self._health

    def score_text(self) -> str:
        if self._health is None or self._health.score is None:
            return MISSING_TEXT
        return str(self._health.score)

    def band_text(self) -> str:
        if self._health is None:
            return "Not assessed"
        return self._health.band

    def set_health(self, health: HealthScore | None) -> None:
        self._health = health
        self._update_text()
        self.update()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def _update_text(self) -> None:
        reason = ""
        if self._health is not None and not self._health.available:
            reason = f" — {self._health.reason}"
        text = f"Experimental health score: {self.score_text()} ({self.band_text()}){reason}"
        self.setAccessibleDescription(text)
        self.setToolTip(text)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = self._palette
        score = self._health.score if self._health else None
        side = min(self.width(), self.height() - 18) - 8
        rect = QRectF((self.width() - side) / 2, 4, side, side)
        thickness = max(8.0, side * 0.08)
        ring = rect.adjusted(thickness, thickness, -thickness, -thickness)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(QColor(p.border), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawArc(ring, 0, 360 * 16)
        if score is not None:
            painter.setPen(
                QPen(
                    QColor(score_colour(p, score)),
                    thickness,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawArc(ring, 90 * 16, round(-360 * 16 * score / 100))
        big = QFont(self.font())
        big.setPixelSize(max(16, int(side * 0.27)))
        big.setBold(True)
        painter.setFont(big)
        painter.setPen(QColor(p.text if score is not None else p.text_secondary))
        painter.drawText(
            QRectF(rect.left(), rect.top() + side * 0.24, side, side * 0.32),
            Qt.AlignmentFlag.AlignCenter,
            self.score_text(),
        )
        small = QFont(self.font())
        small.setPixelSize(max(10, int(side * 0.085)))
        painter.setFont(small)
        painter.setPen(QColor(p.text_secondary))
        painter.drawText(
            QRectF(rect.left(), rect.top() + side * 0.56, side, side * 0.14),
            Qt.AlignmentFlag.AlignCenter,
            self.band_text(),
        )
        caption = QFont(self.font())
        caption.setPixelSize(11)
        caption.setBold(True)
        painter.setFont(caption)
        painter.setPen(QColor(p.warning))
        painter.drawText(
            QRectF(0, rect.bottom() + 2, self.width(), 16),
            Qt.AlignmentFlag.AlignCenter,
            "EXPERIMENTAL",
        )
        painter.end()
