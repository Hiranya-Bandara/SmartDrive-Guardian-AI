from __future__ import annotations

import gc
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from smartdrive.app import bootstrap, shutdown
from smartdrive.models.vehicle import Vehicle, VehicleProfile
from smartdrive.services.voice import VoiceInfo
from smartdrive.ui.application import GuiApplication
from smartdrive.ui.workers.voice_worker import VoiceWorker

pytestmark = pytest.mark.ui


class FakeSpeech:
    """Records announcements instead of speaking. Tests never use the real speech engine."""

    def __init__(self, *, fail: bool = False) -> None:
        self.spoken: list[str] = []
        self.closed = False
        self.fail = fail

    @property
    def available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    def voices(self) -> list[VoiceInfo]:
        return [VoiceInfo("fake-1", "Test voice")]

    def speak(self, text: str, *, voice_id: str | None, rate: int, volume: float) -> None:
        if self.fail:
            raise RuntimeError("synthesiser crashed")
        self.spoken.append(text)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _collect_garbage_on_gui_thread() -> None:
    # Leftover Qt objects from earlier tests must be freed here, never by a worker thread.
    gc.collect()


@pytest.fixture
def fake_speech() -> FakeSpeech:
    return FakeSpeech()


@pytest.fixture
def gui(qapp: QApplication, tmp_path: Path, fake_speech: FakeSpeech) -> Iterator[GuiApplication]:
    ctx = bootstrap(home=tmp_path / "home", console_logging=False)
    ctx.settings.monitoring.refresh_interval_ms = 100
    ctx.settings.appearance.animations_enabled = False
    ctx.settings.alerts.desktop_notifications = False
    app = GuiApplication(
        ctx, install_excepthook=False, voice_worker=VoiceWorker(lambda: fake_speech)
    )
    app.window.resize(1366, 768)
    app.window.show()
    yield app
    app.shutdown()
    shutdown(ctx)
    qapp.processEvents()


@pytest.fixture
def active_vehicle(gui: GuiApplication, vehicle_profile: VehicleProfile) -> Vehicle:
    vehicle = gui.ui.vehicles.add(vehicle_profile)
    gui.ui.state.set_active_vehicle(vehicle.id)
    gui.ui.state.reload()
    return gui.ui.vehicles.get(vehicle.id)
