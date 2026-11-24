"""Chart container around PyQtGraph with theme support and gap-aware curves."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from smartdrive.ui.themes.palette import DARK, ThemePalette
from smartdrive.ui.widgets.cards import Card

pg.setConfigOptions(antialias=True, foreground=DARK.text_secondary, background=None)


def _top_level_menus() -> set[QMenu]:
    return {w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu)}


class ChartContainer(Card):
    """A titled card holding one plot. NaN values break the line, so gaps stay visible."""

    def __init__(
        self,
        title: str,
        y_label: str = "",
        *,
        x_label: str = "Time (s)",
        height: int = 180,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self._palette = DARK
        self._curve_colours: dict[str, str] = {}
        existing_menus = _top_level_menus()
        self.plot = pg.PlotWidget()
        # PyQtGraph creates its context menus without a parent; adopt them so they are
        # destroyed with the chart instead of living for the rest of the process.
        for menu in _top_level_menus() - existing_menus:
            menu.setParent(self.plot, menu.windowFlags())
        self.plot.setMinimumHeight(height)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setClipToView(True)
        self.plot.setDownsampling(auto=True, mode="peak")
        self.plot.setLabel("bottom", x_label)
        self.plot.setLabel("left", y_label)
        self.plot.setAccessibleName(f"{title} chart")
        self._legend: pg.LegendItem | None = None
        self.curves: dict[str, pg.PlotDataItem] = {}
        self.body.addWidget(self.plot)

    def add_curve(self, key: str, name: str, colour_role: str = "accent") -> None:
        if len(self.curves) == 1 and self._legend is None:
            self._legend = self.plot.addLegend(offset=(10, 5))
        curve = self.plot.plot([], [], name=name, connect="finite")
        self.curves[key] = curve
        self._curve_colours[key] = colour_role
        self._style_curve(key)

    def set_y_label(self, text: str) -> None:
        self.plot.setLabel("left", text)

    def set_data(self, key: str, times: Sequence[float], values: Sequence[float]) -> None:
        self.curves[key].setData(
            np.asarray(times, dtype=float), np.asarray(values, dtype=float), connect="finite"
        )

    def set_x_window(self, end: float, seconds: float) -> None:
        self.plot.setXRange(max(0.0, end - seconds), max(seconds, end), padding=0)

    def set_y_range(self, low: float, high: float) -> None:
        self.plot.setYRange(low, high, padding=0.05)

    def clear_data(self) -> None:
        for curve in self.curves.values():
            curve.setData([], [])

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.plot.setBackground(palette.surface)
        for axis in ("left", "bottom"):
            item = self.plot.getAxis(axis)
            item.setPen(pg.mkPen(palette.border))
            item.setTextPen(pg.mkPen(palette.text_secondary))
        for key in self.curves:
            self._style_curve(key)
        if self._legend is not None:
            self._legend.setLabelTextColor(palette.text_secondary)

    def _style_curve(self, key: str) -> None:
        colour = getattr(self._palette, self._curve_colours[key])
        self.curves[key].setPen(pg.mkPen(colour, width=2))
