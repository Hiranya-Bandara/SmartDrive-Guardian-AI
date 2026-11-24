"""Small helpers shared by all widgets."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QWidget

from smartdrive.ui.icons import icon
from smartdrive.ui.themes.palette import ThemePalette


def set_props(widget: QWidget, **properties: object) -> None:
    """Set dynamic properties used by the stylesheet and re-evaluate styling."""
    for name, value in properties.items():
        widget.setProperty(name, value)
    repolish(widget)


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def combo_enum[E: StrEnum](combo: QComboBox, enum_type: type[E]) -> E | None:
    """Current item data as ``enum_type``.

    Qt stores ``StrEnum`` item data as plain ``str``, so it must be converted back explicitly.
    """
    data = combo.currentData()
    if data is None:
        return None
    try:
        return enum_type(data)
    except ValueError:
        return None


def label(text: str = "", role: str | None = None, *, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


class IconPushButton(QPushButton):
    """Push button whose icon follows the active palette."""

    def __init__(
        self,
        text: str,
        icon_name: str | None = None,
        *,
        variant: str | None = None,
        tooltip: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._icon_name = icon_name
        if variant:
            self.setProperty("variant", variant)
        if tooltip:
            self.setToolTip(tooltip)
        self.setAccessibleName(text or tooltip or "")

    def set_icon_name(self, name: str | None) -> None:
        self._icon_name = name

    def apply_palette(self, palette: ThemePalette) -> None:
        if not self._icon_name:
            return
        variant = self.property("variant")
        colour = {
            "primary": palette.on_accent,
            "danger": palette.critical,
        }.get(str(variant), palette.text)
        self.setIcon(icon(self._icon_name, colour, disabled_colour=palette.offline, size=16))
