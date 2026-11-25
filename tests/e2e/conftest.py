"""Fixtures for end-to-end scenarios that start, stop and restart the whole application."""

from __future__ import annotations

import gc
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from smartdrive.app import bootstrap, shutdown
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.workers.voice_worker import VoiceWorker
from tests.ui.conftest import FakeSpeech

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _collect_garbage_on_gui_thread() -> None:
    gc.collect()


@pytest.fixture
def fake_speech() -> FakeSpeech:
    return FakeSpeech()


AppRunner = Callable[..., Any]


@pytest.fixture
def run_app(qapp: QApplication, fake_speech: FakeSpeech) -> Iterator[AppRunner]:
    """Context manager that starts the full GUI application on a data folder and always stops it.

    Each use is one application "launch"; using it twice on the same folder is a restart.
    """
    running: list[GuiApplication] = []

    @contextmanager
    def launch(home: Path, **gui_kwargs: Any) -> Iterator[GuiApplication]:
        ctx = bootstrap(home=home, console_logging=False)
        ctx.settings.monitoring.refresh_interval_ms = 100
        ctx.settings.alerts.desktop_notifications = False
        gui_kwargs.setdefault("voice_worker", VoiceWorker(lambda: fake_speech))
        gui = GuiApplication(ctx, install_excepthook=False, **gui_kwargs)
        running.append(gui)
        gui.window.resize(1366, 768)
        gui.window.show()
        try:
            yield gui
        finally:
            gui.shutdown()
            shutdown(ctx)
            running.remove(gui)
            qapp.processEvents()

    yield launch
    for gui in list(running):  # pragma: no cover - only after a failure inside a launch
        gui.shutdown()
