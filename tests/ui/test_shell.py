"""Application startup, navigation, sidebar, themes, settings persistence and shutdown."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from smartdrive import __version__
from smartdrive.config.constants import HOME_ENV_VAR, ThemePreference, UnitSystem
from smartdrive.config.settings import SettingsStore
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.main_window import PAGES, UPCOMING
from smartdrive.ui.navigation import COLLAPSED_WIDTH, EXPANDED_WIDTH
from smartdrive.ui.pages.settings_page import SettingsPage
from smartdrive.ui.themes.palette import DARK, LIGHT
from smartdrive.ui.widgets.status import StatusLevel

pytestmark = pytest.mark.ui


def stored_settings(gui: GuiApplication) -> SettingsStore:
    return SettingsStore(gui.app_context.paths.settings_file)


def test_main_window_initialises_every_page(gui: GuiApplication) -> None:
    window = gui.window
    assert __version__ in window.windowTitle()
    assert set(window.pages) == {item.key for item in PAGES}
    assert window.current_key == "dashboard"
    assert window.top_bar.title_label.text() == "Dashboard"
    assert window.minimumWidth() <= 1366
    assert window.isVisible()


def test_future_features_are_visible_but_disabled(gui: GuiApplication) -> None:
    for item in UPCOMING:
        button = gui.window.sidebar.buttons[item.key]
        assert not button.isEnabled()
        assert item.available_in is not None
        assert item.available_in in button.toolTip()
        assert item.key not in gui.window.pages


def test_sidebar_navigation(gui: GuiApplication, qtbot: QtBot) -> None:
    for item in PAGES:
        qtbot.mouseClick(gui.window.sidebar.buttons[item.key], Qt.MouseButton.LeftButton)
        assert gui.window.current_key == item.key
        assert gui.window.sidebar.buttons[item.key].isChecked()
        assert gui.window.top_bar.title_label.text() == gui.window.pages[item.key].title


def test_keyboard_shortcuts_are_registered_for_every_page(gui: GuiApplication) -> None:
    sequences = {s.key().toString() for s in gui.window.findChildren(QShortcut)}
    expected = {f"Ctrl+{i}" for i in range(1, len(PAGES) + 1)} | {"Ctrl+B", "Ctrl+M", "Ctrl+P"}
    assert expected <= sequences
    by_sequence = {s.key().toString(): s for s in gui.window.findChildren(QShortcut)}
    by_sequence["Ctrl+3"].activated.emit()
    assert gui.window.current_key == "garage"
    by_sequence["Ctrl+M"].activated.emit()
    assert gui.ui.monitoring.is_active
    by_sequence["Ctrl+M"].activated.emit()
    assert not gui.ui.monitoring.is_active


def test_nav_buttons_are_keyboard_focusable(gui: GuiApplication) -> None:
    button = gui.window.sidebar.buttons["garage"]
    assert button.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert button.accessibleName()


def test_sidebar_collapse_is_persisted(gui: GuiApplication) -> None:
    sidebar = gui.window.sidebar
    assert sidebar.width() == EXPANDED_WIDTH
    sidebar.toggle()
    assert sidebar.collapsed
    assert sidebar.width() == COLLAPSED_WIDTH
    assert stored_settings(gui).load().appearance.sidebar_collapsed is True
    sidebar.toggle()
    assert stored_settings(gui).load().appearance.sidebar_collapsed is False


def test_theme_switching_applies_and_persists(gui: GuiApplication, qapp: QApplication) -> None:
    page = gui.window.pages["settings"]
    assert isinstance(page, SettingsPage)
    assert gui.ui.theme.palette is DARK
    page.theme_combo.setCurrentIndex(page.theme_combo.findData(ThemePreference.LIGHT))
    assert gui.ui.theme.palette is LIGHT
    assert LIGHT.background in qapp.styleSheet()
    assert stored_settings(gui).load().appearance.theme is ThemePreference.LIGHT

    page.theme_combo.setCurrentIndex(page.theme_combo.findData(ThemePreference.SYSTEM))
    assert stored_settings(gui).load().appearance.theme is ThemePreference.SYSTEM
    assert gui.ui.theme.palette in (DARK, LIGHT)

    page.theme_combo.setCurrentIndex(page.theme_combo.findData(ThemePreference.DARK))
    assert DARK.background in qapp.styleSheet()


def test_unit_preference_updates_pages_and_persists(gui: GuiApplication) -> None:
    page = gui.window.pages["settings"]
    assert isinstance(page, SettingsPage)
    page.units_combo.setCurrentIndex(page.units_combo.findData(UnitSystem.IMPERIAL))
    assert stored_settings(gui).load().units.system is UnitSystem.IMPERIAL
    dashboard = gui.window.pages["dashboard"]
    assert dashboard.speed_unit.text() == "mph"  # type: ignore[attr-defined]


def test_monitoring_settings_validate_and_persist(gui: GuiApplication) -> None:
    page = gui.window.pages["settings"]
    assert isinstance(page, SettingsPage)
    page.refresh_spin.setValue(500)
    page.keep_forever_check.setChecked(True)
    loaded = stored_settings(gui).load()
    assert loaded.monitoring.refresh_interval_ms == 500
    assert loaded.retention.telemetry_retention_days is None
    assert gui.ui.monitoring.interval_ms == 500


def test_reset_preferences_keeps_shared_settings_object(
    gui: GuiApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = gui.window.pages["settings"]
    assert isinstance(page, SettingsPage)
    monkeypatch.setattr("smartdrive.ui.dialogs.confirm.confirm", lambda *a, **k: True)
    settings = gui.app_context.settings
    page.units_combo.setCurrentIndex(page.units_combo.findData(UnitSystem.IMPERIAL))
    page.reset_preferences()
    assert gui.app_context.settings is settings
    assert settings.units.system is UnitSystem.METRIC
    assert stored_settings(gui).load().units.system is UnitSystem.METRIC


def test_backup_and_restore_from_settings(
    gui: GuiApplication, monkeypatch: pytest.MonkeyPatch, vehicle_profile: object
) -> None:
    page = gui.window.pages["settings"]
    assert isinstance(page, SettingsPage)
    monkeypatch.setattr("smartdrive.ui.dialogs.confirm.confirm", lambda *a, **k: True)
    backup = page.backup()
    assert backup is not None and backup.is_file()
    gui.ui.vehicles.add(vehicle_profile)  # type: ignore[arg-type]
    assert page.restore(backup)
    assert gui.ui.vehicles.list_vehicles() == []


def test_restore_refused_while_monitoring(gui: GuiApplication, tmp_path: Path) -> None:
    page = gui.window.pages["settings"]
    assert isinstance(page, SettingsPage)
    gui.ui.monitoring.start()
    assert not page.restore(tmp_path / "anything.db")
    gui.ui.monitoring.stop()


def test_notifications_show_toasts(gui: GuiApplication) -> None:
    gui.ui.notifier.notify("Saved", StatusLevel.NORMAL)
    toasts = gui.window.toasts.toasts()
    assert toasts and toasts[-1].message_label.text() == "Saved"


def test_shutdown_is_idempotent_and_stops_workers(gui: GuiApplication, qtbot: QtBot) -> None:
    gui.ui.monitoring.start()
    with qtbot.waitSignal(gui.ui.monitoring.frame_received, timeout=5000):
        pass
    gui.shutdown()
    gui.shutdown()
    assert not gui.ui.monitoring.threads_running()
    assert not gui.ui.monitoring.is_active


def test_gui_command_launches_and_exits_cleanly(tmp_path: Path) -> None:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", HOME_ENV_VAR: str(tmp_path / "home")}
    result = subprocess.run(
        [sys.executable, "-m", "smartdrive", "gui", "--quit-after-ms", "1500"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home" / "data" / "smartdrive.db").is_file()
