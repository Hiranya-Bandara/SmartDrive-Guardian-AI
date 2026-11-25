"""Collapsible sidebar navigation."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from smartdrive import APP_NAME
from smartdrive.ui.icons import brand_pixmap, icon, pixmap
from smartdrive.ui.themes.palette import DARK, ThemePalette
from smartdrive.ui.widgets.base import label

EXPANDED_WIDTH = 232
COLLAPSED_WIDTH = 68


@dataclass(frozen=True, slots=True)
class NavItem:
    key: str
    title: str
    icon_name: str
    available_in: str | None = None  # e.g. "Phase 5" for entries not built yet
    group: str = ""
    """Sidebar section heading; consecutive items with the same group share one heading."""
    shortcut: str = ""

    @property
    def enabled(self) -> bool:
        return self.available_in is None


class NavButton(QToolButton):
    def __init__(self, item: NavItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self.setProperty("role", "nav")
        self.setCheckable(item.enabled)
        self.setEnabled(item.enabled)
        self.setText(item.title)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(20, 20))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if not item.enabled:
            tooltip = f"{item.title} — available in {item.available_in}"
        elif item.shortcut:
            tooltip = f"{item.title} ({item.shortcut})"
        else:
            tooltip = item.title
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)

    def set_collapsed(self, collapsed: bool) -> None:
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if collapsed
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )

    def apply_palette(self, palette: ThemePalette) -> None:
        result = icon(self.item.icon_name, palette.text_secondary, disabled_colour=palette.offline)
        result.addPixmap(
            pixmap(self.item.icon_name, palette.accent, 20), result.Mode.Normal, result.State.On
        )
        self.setIcon(result)


class Sidebar(QFrame):
    page_requested = Signal(str)
    collapsed_changed = Signal(bool)

    def __init__(
        self,
        pages: tuple[NavItem, ...],
        upcoming: tuple[NavItem, ...],
        *,
        collapsed: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._collapsed = collapsed
        self._palette = DARK
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 12)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.logo = QLabel()
        self.brand_text = QWidget()
        text_layout = QVBoxLayout(self.brand_text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        title = label("SmartDrive", None)
        title.setObjectName("BrandTitle")
        subtitle = label("Guardian AI", None)
        subtitle.setObjectName("BrandSubtitle")
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)
        brand.addWidget(self.logo)
        brand.addWidget(self.brand_text, 1)
        layout.addLayout(brand)
        layout.addSpacing(18)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, NavButton] = {}
        self.section_labels: list[tuple[QLabel, str]] = []
        # The page list scrolls so every entry stays reachable at small window heights.
        nav = QWidget()
        nav.setObjectName("SidebarNav")
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        current_group: str | None = None
        for item in pages:
            if item.group and item.group != current_group:
                nav_layout.addSpacing(8)
                nav_layout.addWidget(self._section(item.group))
            current_group = item.group
            nav_layout.addWidget(self._make_button(item))
        self.upcoming_label = self._section("COMING LATER")
        self.upcoming_label.setVisible(bool(upcoming))
        if upcoming:
            nav_layout.addSpacing(10)
            nav_layout.addWidget(self.upcoming_label)
        for item in upcoming:
            nav_layout.addWidget(self._make_button(item))
        nav_layout.addStretch(1)
        self.nav_scroll = QScrollArea()
        self.nav_scroll.setObjectName("SidebarScroll")
        self.nav_scroll.setWidget(nav)
        self.nav_scroll.setWidgetResizable(True)
        self.nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.nav_scroll, 1)

        self.toggle_button = QToolButton()
        self.toggle_button.setProperty("role", "nav")
        self.toggle_button.setAccessibleName("Collapse sidebar")
        self.toggle_button.clicked.connect(self.toggle)
        layout.addWidget(self.toggle_button)

        self.animations_enabled = True
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.valueChanged.connect(self._on_width_animated)
        self.setAccessibleName(f"{APP_NAME} navigation")
        self._apply_collapsed(animate=False)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def _section(self, title: str) -> QLabel:
        heading = label(title.upper())
        heading.setObjectName("SidebarSection")
        self.section_labels.append((heading, title.upper()))
        return heading

    def _make_button(self, item: NavItem) -> NavButton:
        button = NavButton(item)
        self.buttons[item.key] = button
        if item.enabled:
            self.group.addButton(button)
            button.clicked.connect(lambda _=False, key=item.key: self.page_requested.emit(key))
        return button

    def set_current(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None and button.item.enabled:
            button.setChecked(True)

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool, *, animate: bool = True) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_collapsed(animate=animate)
        self.collapsed_changed.emit(collapsed)

    def _apply_collapsed(self, *, animate: bool) -> None:
        width = COLLAPSED_WIDTH if self._collapsed else EXPANDED_WIDTH
        for button in self.buttons.values():
            button.set_collapsed(self._collapsed)
        self.brand_text.setVisible(not self._collapsed)
        for heading, text in self.section_labels:
            heading.setText("···" if self._collapsed else text)
        self.toggle_button.setToolTip(
            "Expand sidebar (Ctrl+B)" if self._collapsed else "Collapse sidebar (Ctrl+B)"
        )
        self.toggle_button.setAccessibleName(self.toggle_button.toolTip())
        self.toggle_button.setText("" if self._collapsed else "Collapse")
        self.toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if self._collapsed
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._animation.stop()
        if animate and self.animations_enabled and self.isVisible():
            self._animation.setStartValue(self.width())
            self._animation.setEndValue(width)
            self._animation.start()
        else:
            self.setFixedWidth(width)
        self._refresh_icons()

    def _on_width_animated(self, value: object) -> None:
        if isinstance(value, int):
            self.setFixedWidth(value)

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        for button in self.buttons.values():
            button.apply_palette(palette)
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        p = self._palette
        self.logo.setPixmap(brand_pixmap(30, self.devicePixelRatioF()))
        name = "chevrons-right" if self._collapsed else "chevrons-left"
        self.toggle_button.setIcon(icon(name, p.text_secondary))
