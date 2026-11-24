"""Applies the active palette to the application and notifies custom-painted widgets."""

from __future__ import annotations

import contextlib
from importlib.resources import files
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from smartdrive.config.constants import ThemePreference
from smartdrive.ui.themes.palette import DARK, LIGHT, ThemePalette


def load_stylesheet(palette: ThemePalette) -> str:
    template = files("smartdrive.ui.themes").joinpath("stylesheet.qss").read_text("utf-8")
    return Template(template).substitute(palette.tokens())


def system_prefers_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hints.colorScheme() != Qt.ColorScheme.Light


class ThemeManager(QObject):
    theme_changed = Signal(object)

    def __init__(self, preference: ThemePreference, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._preference = preference
        self._palette = self._resolve(preference)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)

    def dispose(self) -> None:
        """Detach from the application-wide colour-scheme signal."""
        with contextlib.suppress(RuntimeError, TypeError):
            QGuiApplication.styleHints().colorSchemeChanged.disconnect(
                self._on_system_scheme_changed
            )

    @property
    def preference(self) -> ThemePreference:
        return self._preference

    @property
    def palette(self) -> ThemePalette:
        return self._palette

    def set_preference(self, preference: ThemePreference) -> None:
        self._preference = preference
        self._activate(self._resolve(preference))

    def apply(self) -> None:
        self._activate(self._palette, force=True)

    def _resolve(self, preference: ThemePreference) -> ThemePalette:
        if preference is ThemePreference.SYSTEM:
            return DARK if system_prefers_dark() else LIGHT
        return LIGHT if preference is ThemePreference.LIGHT else DARK

    def _activate(self, palette: ThemePalette, *, force: bool = False) -> None:
        changed = palette != self._palette
        self._palette = palette
        app = QApplication.instance()
        if isinstance(app, QApplication) and (changed or force):
            app.setPalette(_qt_palette(palette))
            app.setStyleSheet(load_stylesheet(palette))
        if changed or force:
            self.theme_changed.emit(palette)

    def _on_system_scheme_changed(self, _scheme: Qt.ColorScheme) -> None:
        if self._preference is ThemePreference.SYSTEM:
            self._activate(self._resolve(ThemePreference.SYSTEM))


def _qt_palette(theme: ThemePalette) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: theme.background,
        QPalette.ColorRole.WindowText: theme.text,
        QPalette.ColorRole.Base: theme.background_secondary,
        QPalette.ColorRole.AlternateBase: theme.surface,
        QPalette.ColorRole.Text: theme.text,
        QPalette.ColorRole.Button: theme.surface,
        QPalette.ColorRole.ButtonText: theme.text,
        QPalette.ColorRole.Highlight: theme.accent,
        QPalette.ColorRole.HighlightedText: theme.on_accent,
        QPalette.ColorRole.ToolTipBase: theme.surface,
        QPalette.ColorRole.ToolTipText: theme.text,
        QPalette.ColorRole.PlaceholderText: theme.text_secondary,
        QPalette.ColorRole.Link: theme.accent,
    }
    for role, colour in roles.items():
        palette.setColor(role, QColor(colour))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme.offline))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme.offline)
    )
    return palette
