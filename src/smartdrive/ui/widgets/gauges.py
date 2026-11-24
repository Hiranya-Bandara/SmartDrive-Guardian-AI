"""Custom-painted instrument gauges.

Coloured bands mark generic display ranges (like a tachometer redline). They are not diagnostic
thresholds and never imply that a reading is safe.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from smartdrive.core.units import MISSING_TEXT
from smartdrive.ui.themes.palette import DARK, ThemePalette

START_ANGLE = 225.0
SPAN_ANGLE = -270.0


@dataclass(frozen=True, slots=True)
class GaugeBand:
    start: float
    end: float
    level: str  # "warning" | "critical"


class _AnimatedValueWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = DARK
        self._value: float | None = None
        self._shown = 0.0
        self.animations_enabled = True
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(250)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_animated)

    @property
    def value(self) -> float | None:
        return self._value

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.update()

    def _set_target(self, value: float | None, minimum: float, maximum: float) -> None:
        self._value = value
        target = minimum if value is None else max(minimum, min(maximum, value))
        self._animation.stop()
        if self.animations_enabled and self.isVisible() and value is not None:
            # Both ends must be floats: QVariantAnimation cannot interpolate int -> float.
            self._animation.setStartValue(float(self._shown))
            self._animation.setEndValue(float(target))
            self._animation.start()
        else:
            self._shown = float(target)
            self.update()

    def _on_animated(self, value: object) -> None:
        if isinstance(value, int | float):
            self._shown = float(value)
            self.update()

    def _band_colour(self, level: str) -> QColor:
        return QColor(self._palette.critical if level == "critical" else self._palette.warning)


class CircularGauge(_AnimatedValueWidget):
    def __init__(
        self,
        label: str,
        unit: str,
        minimum: float,
        maximum: float,
        *,
        decimals: int = 0,
        bands: tuple[GaugeBand, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._unit = unit
        self._min = minimum
        self._max = maximum
        self._decimals = decimals
        self._bands = bands
        self._shown = float(minimum)
        self.setMinimumSize(160, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(f"{label} gauge")
        self._update_accessibility()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(190, 190)

    def configure(
        self, *, unit: str, minimum: float, maximum: float, bands: tuple[GaugeBand, ...]
    ) -> None:
        self._unit, self._min, self._max, self._bands = unit, minimum, maximum, bands
        self.set_value(self._value)

    def set_value(self, value: float | None) -> None:
        self._set_target(value, self._min, self._max)
        self._update_accessibility()

    def value_text(self) -> str:
        return MISSING_TEXT if self._value is None else f"{self._value:.{self._decimals}f}"

    def _update_accessibility(self) -> None:
        self.setAccessibleDescription(f"{self._label}: {self.value_text()} {self._unit}")
        self.setToolTip(f"{self._label}: {self.value_text()} {self._unit}")

    def _fraction(self, value: float) -> float:
        span = self._max - self._min
        return 0.0 if span <= 0 else (max(self._min, min(self._max, value)) - self._min) / span

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = self._palette
        caption_height = 26.0
        side = min(self.width(), self.height() - caption_height) - 8
        top = (self.height() - caption_height - side) / 2
        rect = QRectF((self.width() - side) / 2, top, side, side)
        thickness = max(8.0, side * 0.075)
        arc_rect = rect.adjusted(thickness, thickness, -thickness, -thickness)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        def arc(r: QRectF, start_fraction: float, end_fraction: float, pen: QPen) -> None:
            painter.setPen(pen)
            start = START_ANGLE + SPAN_ANGLE * start_fraction
            span = SPAN_ANGLE * (end_fraction - start_fraction)
            painter.drawArc(r, round(start * 16), round(span * 16))

        track = QPen(QColor(p.border), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        arc(arc_rect, 0.0, 1.0, track)

        band_rect = rect.adjusted(
            thickness * 0.25, thickness * 0.25, -thickness * 0.25, -thickness * 0.25
        )
        for band in self._bands:
            pen = QPen(self._band_colour(band.level), max(3.0, thickness * 0.3))
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            arc(band_rect, self._fraction(band.start), self._fraction(band.end), pen)

        if self._value is not None:
            value_pen = QPen(
                QColor(p.accent), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap
            )
            arc(arc_rect, 0.0, max(0.002, self._fraction(self._shown)), value_pen)

        value_font = QFont(self.font())
        value_font.setPixelSize(max(14, int(side * 0.2)))
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.setPen(QColor(p.text if self._value is not None else p.text_secondary))
        shown = MISSING_TEXT if self._value is None else f"{self._shown:.{self._decimals}f}"
        value_rect = QRectF(rect.left(), rect.center().y() - side * 0.17, rect.width(), side * 0.24)
        painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, shown)

        small = QFont(self.font())
        small.setPixelSize(max(10, int(side * 0.075)))
        painter.setFont(small)
        painter.setPen(QColor(p.text_secondary))
        unit_rect = QRectF(rect.left(), value_rect.bottom(), rect.width(), side * 0.1)
        painter.drawText(
            unit_rect,
            Qt.AlignmentFlag.AlignCenter,
            self._unit if self._value is not None else "No data",
        )
        caption = QFont(self.font())
        caption.setPixelSize(13)
        painter.setFont(caption)
        label_rect = QRectF(0, rect.bottom() - side * 0.08, self.width(), caption_height)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self._label)
        painter.end()


class LinearGauge(_AnimatedValueWidget):
    """Horizontal bar with value text; an optional low band is labelled in text, not colour only."""

    def __init__(
        self,
        label: str,
        unit: str,
        minimum: float = 0.0,
        maximum: float = 100.0,
        *,
        decimals: int = 0,
        low_band: float | None = None,
        low_text: str = "Low",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._unit = unit
        self._min = minimum
        self._max = maximum
        self._decimals = decimals
        self._low_band = low_band
        self._low_text = low_text
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{label} indicator")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(220, 56)

    def set_value(self, value: float | None) -> None:
        self._set_target(value, self._min, self._max)
        self.setAccessibleDescription(f"{self._label}: {self.value_text()}")
        self.setToolTip(f"{self._label}: {self.value_text()}")

    def is_low(self) -> bool:
        return (
            self._low_band is not None
            and self._value is not None
            and (self._value <= self._low_band)
        )

    def value_text(self) -> str:
        if self._value is None:
            return MISSING_TEXT
        text = f"{self._value:.{self._decimals}f} {self._unit}".strip()
        return f"{text} · {self._low_text}" if self.is_low() else text

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        painter.setFont(font)
        painter.setPen(QColor(p.text_secondary))
        header = QRectF(0, 0, self.width(), 22)
        painter.drawText(
            header, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label
        )
        bold = QFont(font)
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(QColor(p.warning if self.is_low() else p.text))
        painter.drawText(
            header, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.value_text()
        )

        bar = QRectF(0, 30, self.width(), 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.border))
        painter.drawRoundedRect(bar, 6, 6)
        span = self._max - self._min
        if self._low_band is not None and span > 0:
            low_width = (self._low_band - self._min) / span * bar.width()
            band = QColor(p.warning)
            band.setAlpha(90)
            painter.setBrush(band)
            painter.drawRoundedRect(QRectF(bar.left(), bar.top(), low_width, bar.height()), 6, 6)
        if self._value is not None and span > 0:
            fraction = (self._shown - self._min) / span
            painter.setBrush(QColor(p.warning if self.is_low() else p.accent))
            painter.drawRoundedRect(
                QRectF(
                    bar.left(), bar.top(), max(bar.height(), fraction * bar.width()), bar.height()
                ),
                6,
                6,
            )
        painter.end()
