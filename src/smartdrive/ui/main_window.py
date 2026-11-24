"""Main window: sidebar, top bar, page stack, keyboard shortcuts and notifications."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from smartdrive import APP_NAME, __version__
from smartdrive.ui.context import UiContext
from smartdrive.ui.navigation import NavItem, Sidebar
from smartdrive.ui.pages.about import AboutPage
from smartdrive.ui.pages.base import Page
from smartdrive.ui.pages.dashboard import DashboardPage
from smartdrive.ui.pages.garage import GaragePage
from smartdrive.ui.pages.live_monitoring import LiveMonitoringPage
from smartdrive.ui.pages.settings_page import SettingsPage
from smartdrive.ui.pages.simulation_lab import SimulationLabPage
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.top_bar import TopBar
from smartdrive.ui.widgets.monitoring_controls import toggle_monitoring, toggle_pause
from smartdrive.ui.widgets.notifications import ToastHost
from smartdrive.ui.widgets.status import StatusLevel

PAGES: tuple[NavItem, ...] = (
    NavItem("dashboard", "Dashboard", "dashboard"),
    NavItem("monitoring", "Live Monitoring", "activity"),
    NavItem("garage", "Vehicle Garage", "car"),
    NavItem("simulation", "Simulation Lab", "flask"),
    NavItem("settings", "Settings", "settings"),
    NavItem("about", "About", "info"),
)

UPCOMING: tuple[NavItem, ...] = (
    NavItem("diagnostics", "AI Diagnostics", "cpu", "Phase 3"),
    NavItem("maintenance", "Predictive Maintenance", "wrench", "Phase 4"),
    NavItem("obd", "OBD-II Diagnostics", "plug", "Phase 4"),
    NavItem("trips", "Trip Analytics", "route", "Phase 4"),
    NavItem("alerts", "Alert Centre", "bell", "Phase 4"),
    NavItem("reports", "Reports", "file", "Phase 4"),
)

MIN_WIDTH = 1180
MIN_HEIGHT = 700


class MainWindow(QMainWindow):
    def __init__(self, ctx: UiContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.resize(1440, 900)

        root = QWidget()
        root.setObjectName("AppRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        settings = ctx.app.settings
        self.sidebar = Sidebar(PAGES, UPCOMING, collapsed=settings.appearance.sidebar_collapsed)
        self.sidebar.animations_enabled = settings.appearance.animations_enabled
        layout.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.top_bar = TopBar(ctx)
        self.stack = QStackedWidget()
        right.addWidget(self.top_bar)
        right.addWidget(self.stack, 1)
        layout.addLayout(right, 1)
        self.setCentralWidget(root)

        self.pages: dict[str, Page] = {}
        dashboard = DashboardPage(ctx)
        dashboard.navigate.connect(self.show_page)
        for page in (
            dashboard,
            LiveMonitoringPage(ctx),
            GaragePage(ctx),
            SimulationLabPage(ctx),
            SettingsPage(ctx),
            AboutPage(ctx),
        ):
            self.pages[page.key] = page
            self.stack.addWidget(page)

        self.toasts = ToastHost(self)
        ctx.notifier.message.connect(self._notify)
        ctx.monitoring.error_occurred.connect(lambda text: self._notify(text, StatusLevel.CRITICAL))
        self.sidebar.page_requested.connect(self.show_page)
        self.sidebar.collapsed_changed.connect(self._remember_sidebar)
        ctx.theme.theme_changed.connect(self.apply_palette)
        ctx.state.settings_changed.connect(self._on_settings_changed)
        self._install_shortcuts()
        self.apply_palette(ctx.theme.palette)
        self.show_page("dashboard")
        self.stack.setFocus()

    @property
    def current_key(self) -> str:
        widget = self.stack.currentWidget()
        return widget.key if isinstance(widget, Page) else ""

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.sidebar.set_current(key)
        self.top_bar.set_page(page.title, page.subtitle)
        page.on_shown()

    def apply_palette(self, palette: object) -> None:
        if not isinstance(palette, ThemePalette):
            return
        for widget in self.findChildren(QWidget):
            apply = getattr(widget, "apply_palette", None)
            if callable(apply):
                apply(palette)
        self.toasts.apply_palette(palette)

    def _install_shortcuts(self) -> None:
        for index, item in enumerate(PAGES, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda key=item.key: self.show_page(key))
        bindings = (
            ("Ctrl+B", self.sidebar.toggle),
            ("Ctrl+M", lambda: toggle_monitoring(self.ctx)),
            ("Ctrl+P", lambda: toggle_pause(self.ctx)),
        )
        for sequence, handler in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(handler)

    def _notify(self, text: str, level: object) -> None:
        self.toasts.notify(text, level if isinstance(level, StatusLevel) else StatusLevel.INFO)

    def _remember_sidebar(self, collapsed: bool) -> None:
        self.ctx.app.settings.appearance.sidebar_collapsed = collapsed
        self.ctx.state.save_settings()

    def _on_settings_changed(self, _settings: object) -> None:
        self.sidebar.animations_enabled = self.ctx.app.settings.appearance.animations_enabled

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.ctx.monitoring.shutdown()
        super().closeEvent(event)
