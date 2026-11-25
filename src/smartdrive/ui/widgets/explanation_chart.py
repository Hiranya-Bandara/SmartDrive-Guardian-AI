"""Horizontal bar charts for feature contributions (one prediction) and global importance."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget

from smartdrive.ui.themes.palette import DARK, ThemePalette
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.charts import create_plot_widget


class BarChart(Card):
    """Signed horizontal bars with text labels on the left axis."""

    def __init__(
        self, title: str, x_label: str, *, height: int = 260, parent: QWidget | None = None
    ) -> None:
        super().__init__(title, parent)
        self._palette = DARK
        self._labels: list[str] = []
        self._values: list[float] = []
        self.plot = create_plot_widget()
        self.plot.setMinimumHeight(height)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.showGrid(x=True, y=False, alpha=0.15)
        self.plot.setLabel("bottom", x_label)
        self.plot.setAccessibleName(f"{title} chart")
        self.body.addWidget(self.plot)
        self._bars: pg.BarGraphItem | None = None

    @property
    def labels(self) -> list[str]:
        return list(self._labels)

    @property
    def values(self) -> list[float]:
        return list(self._values)

    def set_bars(self, labels: Sequence[str], values: Sequence[float]) -> None:
        """Bars are drawn top-to-bottom in the given order."""
        self._labels = list(labels)
        self._values = [float(v) for v in values]
        self._redraw()

    def clear_bars(self) -> None:
        self.set_bars([], [])

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.plot.setBackground(palette.surface)
        for axis in ("left", "bottom"):
            item = self.plot.getAxis(axis)
            item.setPen(pg.mkPen(palette.border))
            item.setTextPen(pg.mkPen(palette.text_secondary))
        self._redraw()

    def _redraw(self) -> None:
        if self._bars is not None:
            self.plot.removeItem(self._bars)
            self._bars = None
        count = len(self._values)
        axis = self.plot.getAxis("left")
        if not count:
            axis.setTicks([[]])
            return
        positions = np.arange(count, 0, -1, dtype=float)
        values = np.asarray(self._values)
        brushes = [
            pg.mkBrush(self._palette.warning if v >= 0 else self._palette.accent) for v in values
        ]
        self._bars = pg.BarGraphItem(
            x0=np.minimum(values, 0.0),
            y=positions,
            height=0.6,
            width=np.abs(values),
            brushes=brushes,
            pens=[pg.mkPen(None)] * count,
        )
        self.plot.addItem(self._bars)
        axis.setTicks([[(float(p), text) for p, text in zip(positions, self._labels, strict=True)]])
        low = float(min(0.0, values.min()))
        high = float(max(0.0, values.max()))
        span = max(high - low, 1e-6)
        self.plot.setXRange(low - span * 0.05, high + span * 0.05, padding=0)
        self.plot.setYRange(0.4, count + 0.6, padding=0)
