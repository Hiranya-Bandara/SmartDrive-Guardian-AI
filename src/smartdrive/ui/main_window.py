"""Main window: sidebar, top bar, page stack, keyboard shortcuts and notifications."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from smartdrive import APP_NAME, __version__
from smartdrive.config.constants import NotificationSeverity
from smartdrive.models.notification import Notification
from smartdrive.ui.context import UiContext
from smartdrive.ui.icons import app_icon
from smartdrive.ui.navigation import NavItem, Sidebar
from smartdrive.ui.pages.about import AboutPage
from smartdrive.ui.pages.ai_diagnostics import AiDiagnosticsPage
from smartdrive.ui.pages.alerts import AlertsPage
from smartdrive.ui.pages.base import Page
from smartdrive.ui.pages.dashboard import DashboardPage
from smartdrive.ui.pages.diagnostic_codes import DiagnosticCodesPage
from smartdrive.ui.pages.garage import GaragePage
from smartdrive.ui.pages.live_monitoring import LiveMonitoringPage
from smartdrive.ui.pages.maintenance import MaintenancePage
from smartdrive.ui.pages.reports import ReportsPage
from smartdrive.ui.pages.settings_page import SettingsPage
from smartdrive.ui.pages.simulation_lab import SimulationLabPage
from smartdrive.ui.pages.trip_history import TripHistoryPage
from smartdrive.ui.pages.vehicle_connection import VehicleConnectionPage
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.top_bar import TopBar
from smartdrive.ui.widgets.monitoring_controls import toggle_monitoring, toggle_pause
from smartdrive.ui.widgets.notifications import ToastHost
from smartdrive.ui.widgets.status import StatusLevel

# Sidebar order groups related pages. Shortcuts Ctrl+1…Ctrl+7 keep their Phase 2/3 meaning.
PAGES: tuple[NavItem, ...] = (
    NavItem("dashboard", "Dashboard", "dashboard", shortcut="Ctrl+1"),
    NavItem("monitoring", "Live Monitoring", "activity", group="Monitor", shortcut="Ctrl+2"),
    NavItem("diagnostics", "AI Diagnostics", "cpu", group="Monitor", shortcut="Ctrl+5"),
    NavItem("connection", "Vehicle Connection", "plug", group="Monitor", shortcut="Ctrl+8"),
    NavItem("codes", "Diagnostic Codes", "alert", group="Monitor", shortcut="Ctrl+9"),
    NavItem("garage", "Vehicle Garage", "car", group="Vehicle", shortcut="Ctrl+3"),
    NavItem("trips", "Trip History", "route", group="Vehicle", shortcut="Ctrl+Shift+T"),
    NavItem("maintenance", "Maintenance", "wrench", group="Vehicle", shortcut="Ctrl+Shift+M"),
    NavItem("simulation", "Simulation Lab", "flask", group="Tools", shortcut="Ctrl+4"),
    NavItem("reports", "Reports", "file", group="Tools", shortcut="Ctrl+Shift+R"),
    NavItem("alerts", "Alert Centre", "bell", group="Tools", shortcut="Ctrl+0"),
    NavItem("settings", "Settings", "settings", group="System", shortcut="Ctrl+6"),
    NavItem("about", "About", "info", group="System", shortcut="Ctrl+7"),
)

UPCOMING: tuple[NavItem, ...] = ()

TOAST_LEVEL = {
    NotificationSeverity.INFORMATION: StatusLevel.INFO,
    NotificationSeverity.SUCCESS: StatusLevel.NORMAL,
    NotificationSeverity.WARNING: StatusLevel.WARNING,
    NotificationSeverity.CRITICAL: StatusLevel.CRITICAL,
}

MIN_WIDTH = 1180
MIN_HEIGHT = 700


class MainWindow(QMainWindow):
    def __init__(self, ctx: UiContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(app_icon())
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
        alerts = AlertsPage(ctx)
        alerts.navigate.connect(self.show_page)
        built: dict[str, Page] = {
            page.key: page
            for page in (
                dashboard,
                LiveMonitoringPage(ctx),
                AiDiagnosticsPage(ctx),
                VehicleConnectionPage(ctx),
                DiagnosticCodesPage(ctx),
                GaragePage(ctx),
                TripHistoryPage(ctx),
                MaintenancePage(ctx),
                SimulationLabPage(ctx),
                ReportsPage(ctx),
                alerts,
                SettingsPage(ctx),
                AboutPage(ctx),
            )
        }
        for item in PAGES:
            page = built[item.key]
            self.pages[page.key] = page
            self.stack.addWidget(page)

        self.toasts = ToastHost(self)
        ctx.notifier.message.connect(self._notify)
        ctx.monitoring.error_occurred.connect(self._notify_monitoring_error)
        ctx.diagnostics.error_occurred.connect(self._notify_diagnostics_error)
        ctx.notifications.delivered.connect(self._show_notification)
        ctx.notifications.changed.connect(self._refresh_unread)
        ctx.trips.error.connect(self._notify_trip_error)
        self.sidebar.page_requested.connect(self.show_page)
        self.sidebar.collapsed_changed.connect(self._remember_sidebar)
        ctx.theme.theme_changed.connect(self.apply_palette)
        ctx.state.settings_changed.connect(self._on_settings_changed)
        self._install_shortcuts()
        self.apply_palette(ctx.theme.palette)
        self._refresh_unread()
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
        for item in PAGES:
            if not item.shortcut:
                continue
            shortcut = QShortcut(QKeySequence(item.shortcut), self)
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

    def _notify_monitoring_error(self, text: str) -> None:
        self._notify(text, StatusLevel.CRITICAL)

    def _notify_diagnostics_error(self, text: str) -> None:
        self._notify(text, StatusLevel.WARNING)

    def _notify(self, text: str, level: object) -> None:
        self.toasts.notify(text, level if isinstance(level, StatusLevel) else StatusLevel.INFO)

    def _notify_trip_error(self, text: str) -> None:
        self._notify(text, StatusLevel.WARNING)

    def _show_notification(self, notification: object) -> None:
        if not isinstance(notification, Notification):
            return
        level = TOAST_LEVEL[notification.severity]
        prefix = {StatusLevel.CRITICAL: "Critical: ", StatusLevel.WARNING: "Warning: "}.get(
            level, ""
        )
        self._notify(f"{prefix}{notification.title}", level)

    def _refresh_unread(self) -> None:
        count = self.ctx.notifications.unread_count()
        button = self.sidebar.buttons.get("alerts")
        if button is None:
            return
        title = "Alert Centre" + (f" ({count})" if count else "")
        button.setText(title)
        tooltip = f"Alert Centre — {count} unread" if count else "Alert Centre (Ctrl+0)"
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)

    def _remember_sidebar(self, collapsed: bool) -> None:
        self.ctx.app.settings.appearance.sidebar_collapsed = collapsed
        self.ctx.state.save_settings()

    def _on_settings_changed(self, _settings: object) -> None:
        self.sidebar.animations_enabled = self.ctx.app.settings.appearance.animations_enabled

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.ctx.monitoring.shutdown()
        super().closeEvent(event)
