"""Transient toast notifications and persistent inline banners."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from smartdrive.ui.icons import icon, pixmap
from smartdrive.ui.themes.palette import DARK, ThemePalette
from smartdrive.ui.widgets.base import label, set_props
from smartdrive.ui.widgets.status import StatusLevel, level_colour

_LEVEL_ICON = {
    StatusLevel.NORMAL: "check",
    StatusLevel.WARNING: "alert",
    StatusLevel.CRITICAL: "alert",
    StatusLevel.INFO: "info",
    StatusLevel.OFFLINE: "info",
    StatusLevel.SIMULATION: "flask",
}


class Banner(QFrame):
    """Persistent message strip, e.g. to label simulated data on a page."""

    def __init__(
        self, text: str = "", level: StatusLevel = StatusLevel.INFO, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "banner")
        self._palette = DARK
        self._level = level
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        self.icon_label = QLabel()
        self.text_label = label(text, wrap=True)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label, 1)
        self.set_message(text, level)

    def set_message(self, text: str, level: StatusLevel) -> None:
        self._level = level
        self.text_label.setText(text)
        self.setAccessibleName(text)
        set_props(self, level=level.value)
        self._refresh()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self._refresh()

    def _refresh(self) -> None:
        colour = level_colour(self._palette, self._level)
        self.icon_label.setPixmap(pixmap(_LEVEL_ICON[self._level], colour, 18))


class Toast(QFrame):
    def __init__(
        self, message: str, level: StatusLevel, palette: ThemePalette, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "toast")
        self.setProperty("level", level.value)
        self.setAccessibleName(message)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 8, 10)
        layout.setSpacing(10)
        badge = QLabel()
        badge.setPixmap(pixmap(_LEVEL_ICON[level], level_colour(palette, level), 18))
        self.message_label = label(message, wrap=True)
        self.message_label.setMaximumWidth(320)
        close = QToolButton()
        close.setProperty("role", "icon")
        close.setIcon(icon("x", palette.text_secondary, size=14))
        close.setToolTip("Dismiss")
        close.setAccessibleName("Dismiss notification")
        close.clicked.connect(self.dismiss)
        layout.addWidget(badge)
        layout.addWidget(self.message_label, 1)
        layout.addWidget(close)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def dismiss(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()


class ToastHost(QObject):
    """Stacks toasts in the bottom-right corner of a host window."""

    MARGIN = 20
    MAX_VISIBLE = 4

    def __init__(self, host: QWidget, palette: ThemePalette = DARK) -> None:
        super().__init__(host)
        self._host = host
        self._palette = palette
        self.container = QWidget(host)
        self.container.setObjectName("ToastContainer")
        self._layout = QVBoxLayout(self.container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        host.installEventFilter(self)
        self._reposition()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette

    def notify(
        self, message: str, level: StatusLevel = StatusLevel.INFO, *, timeout_ms: int = 4500
    ) -> Toast:
        toasts = self.toasts()
        if len(toasts) >= self.MAX_VISIBLE:
            toasts[0].deleteLater()
        toast = Toast(message, level, self._palette, self.container)
        self._layout.addWidget(toast)
        toast.destroyed.connect(self._reposition)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, toast, toast.dismiss)
        self.container.show()
        self.container.raise_()
        self._reposition()
        return toast

    def toasts(self) -> list[Toast]:
        return self.container.findChildren(Toast)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._host and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._reposition()
        return False

    def _reposition(self) -> None:
        self.container.adjustSize()
        width = 400
        height = min(self._host.height() - 2 * self.MARGIN, self.container.sizeHint().height())
        self.container.setGeometry(
            self._host.width() - width - self.MARGIN,
            self._host.height() - height - self.MARGIN,
            width,
            max(0, height),
        )
