"""Release UI: first-run guide, About page, branding and safety notices."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel
from pytestqt.qtbot import QtBot

from smartdrive import __version__
from smartdrive.config.settings import SettingsStore
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.dialogs.welcome import SECTIONS, WelcomeDialog, show_welcome
from smartdrive.ui.pages.about import AboutPage

pytestmark = pytest.mark.ui


def test_welcome_guide_is_shown_once_and_remembered(gui: GuiApplication, qtbot: QtBot) -> None:
    settings = gui.app_context.settings
    assert settings.general.welcome_seen is False
    dialog = show_welcome(gui.ui, gui.window)
    qtbot.waitUntil(dialog.isVisible)
    headings = [w.text() for w in dialog.findChildren(QLabel)]
    for heading, _text in SECTIONS:
        assert heading in headings
    assert any("while driving" in h for h in headings)
    assert dialog.show_again.isChecked() is False
    dialog.start_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert settings.general.welcome_seen is True
    stored = SettingsStore(gui.app_context.paths.settings_file).load()
    assert stored.general.welcome_seen is True


def test_welcome_guide_can_be_kept_for_next_start(gui: GuiApplication) -> None:
    gui.app_context.settings.general.welcome_seen = True
    dialog = WelcomeDialog(gui.ui, gui.window)
    dialog.show_again.setChecked(True)
    dialog.reject()  # closing with Esc also records the choice
    assert gui.app_context.settings.general.welcome_seen is False


def test_about_page_identifies_the_release(gui: GuiApplication, qtbot: QtBot) -> None:
    page = gui.window.pages["about"]
    assert isinstance(page, AboutPage)
    gui.window.show_page("about")
    texts = " ".join(w.text() for w in page.findChildren(QLabel))
    assert f"Version {__version__}" in texts
    assert "Hiranya Bandara" in texts
    assert "github.com/Hiranya-Bandara/SmartDrive-Guardian-AI" in texts
    assert "MIT License" in texts
    assert "simulated data only" in texts
    assert "not yet been verified" in texts
    assert "while driving" in texts
    assert "no telemetry" in texts
    assert "synthetic" in texts  # model versions are labelled with their synthetic dataset
    assert "pending owner approval" not in texts
    page.welcome_button.click()
    qtbot.waitUntil(
        lambda: any(
            isinstance(w, WelcomeDialog) and w.isVisible() for w in QApplication.topLevelWidgets()
        )
    )
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, WelcomeDialog):
            widget.accept()


def test_application_and_sidebar_use_the_brand_icon(gui: GuiApplication) -> None:
    icon = gui.window.windowIcon()
    assert not icon.isNull()
    for size in (16, 32, 48, 256):
        assert not icon.pixmap(size, size).isNull()
    logo = gui.window.sidebar.logo.pixmap()
    assert logo is not None and not logo.isNull()
