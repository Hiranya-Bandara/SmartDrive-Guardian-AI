from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from smartdrive.core.units import MISSING_TEXT
from smartdrive.ui.widgets.base import label


class Card(QFrame):
    """Rounded surface with an optional title row and a body layout."""

    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(16, 14, 16, 16)
        self._outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label: QLabel | None = None
        if title is not None:
            self.title_label = label(title.upper(), "card-title")
            self.header.addWidget(self.title_label)
            self.header.addStretch(1)
            self._outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self._outer.addLayout(self.body, 1)

    def set_title(self, title: str) -> None:
        if self.title_label is not None:
            self.title_label.setText(title.upper())


class MetricCard(Card):
    """Single value with unit and a short caption. Missing values render as an em dash."""

    def __init__(self, title: str, unit: str = "", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.value_label = label(MISSING_TEXT, "metric-value")
        self.unit_label = label(unit, "metric-unit")
        row.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self.unit_label, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        self.body.addLayout(row)
        self.caption_label = label("", "muted", wrap=True)
        self.body.addWidget(self.caption_label)
        self._title = title

    def set_value(self, text: str | None, unit: str | None = None, caption: str = "") -> None:
        shown = text if text is not None else MISSING_TEXT
        self.value_label.setText(shown)
        if unit is not None:
            self.unit_label.setText(unit)
        self.caption_label.setText(caption)
        self.caption_label.setVisible(bool(caption))
        self.setAccessibleName(f"{self._title}: {shown} {self.unit_label.text()}".strip())
