"""Loading, empty and error states, and a stack that switches between them and real content."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QStackedWidget, QVBoxLayout, QWidget

from smartdrive.ui.icons import pixmap
from smartdrive.ui.themes.palette import DARK, ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, label


class ViewState(StrEnum):
    CONTENT = "content"
    LOADING = "loading"
    EMPTY = "empty"
    ERROR = "error"


class StatePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = DARK
        self._icon_name = "info"
        self._icon_level = "text_secondary"
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        self.icon_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.title_label = label("", "section-title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label = label("", "muted", wrap=True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setMaximumWidth(460)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(220)
        self.action_button = IconPushButton("", variant="primary")
        self._action: Callable[[], None] | None = None
        self.action_button.clicked.connect(self._run_action)
        for widget in (self.icon_label, self.title_label, self.message_label):
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.progress, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignHCenter)

    def show_state(
        self,
        state: ViewState,
        title: str,
        message: str = "",
        *,
        action_text: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        self._icon_name, self._icon_level = {
            ViewState.LOADING: ("refresh", "accent"),
            ViewState.EMPTY: ("info", "text_secondary"),
            ViewState.ERROR: ("alert", "critical"),
            ViewState.CONTENT: ("info", "text_secondary"),
        }[state]
        self.title_label.setText(title)
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        self.progress.setVisible(state is ViewState.LOADING)
        self._action = action
        self.action_button.setText(action_text or "")
        self.action_button.setAccessibleName(action_text or "")
        self.action_button.setVisible(bool(action_text and action))
        self._refresh_icon()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self._refresh_icon()
        self.action_button.apply_palette(palette)

    def _refresh_icon(self) -> None:
        colour = getattr(self._palette, self._icon_level)
        self.icon_label.setPixmap(pixmap(self._icon_name, colour, 40))

    def _run_action(self) -> None:
        if self._action is not None:
            self._action()


class StatefulStack(QStackedWidget):
    """Shows ``content`` normally, or a :class:`StatePanel` for loading/empty/error states."""

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.content = content
        self.panel = StatePanel()
        self.addWidget(content)
        self.addWidget(self.panel)
        self._state = ViewState.CONTENT

    @property
    def state(self) -> ViewState:
        return self._state

    def show_content(self) -> None:
        self._state = ViewState.CONTENT
        self.setCurrentWidget(self.content)

    def show_loading(self, title: str = "Loading…", message: str = "") -> None:
        self._show(ViewState.LOADING, title, message)

    def show_empty(
        self,
        title: str,
        message: str = "",
        *,
        action_text: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        self._show(ViewState.EMPTY, title, message, action_text=action_text, action=action)

    def show_error(
        self,
        title: str,
        message: str = "",
        *,
        action_text: str | None = "Try again",
        action: Callable[[], None] | None = None,
    ) -> None:
        self._show(ViewState.ERROR, title, message, action_text=action_text, action=action)

    def apply_palette(self, palette: ThemePalette) -> None:
        self.panel.apply_palette(palette)

    def _show(
        self,
        state: ViewState,
        title: str,
        message: str,
        *,
        action_text: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self.panel.show_state(state, title, message, action_text=action_text, action=action)
        self.setCurrentWidget(self.panel)
