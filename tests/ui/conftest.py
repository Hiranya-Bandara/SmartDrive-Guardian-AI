from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from smartdrive.app import bootstrap, shutdown
from smartdrive.models.vehicle import Vehicle, VehicleProfile
from smartdrive.ui.application import GuiApplication

pytestmark = pytest.mark.ui


@pytest.fixture
def gui(qapp: QApplication, tmp_path: Path) -> Iterator[GuiApplication]:
    ctx = bootstrap(home=tmp_path / "home", console_logging=False)
    ctx.settings.monitoring.refresh_interval_ms = 100
    ctx.settings.appearance.animations_enabled = False
    app = GuiApplication(ctx, install_excepthook=False)
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
