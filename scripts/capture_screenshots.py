"""Render real screenshots of every page into docs/screenshots.

Runs the actual application against a temporary data folder, adds a demonstration vehicle,
records a short simulated session and grabs each page. Works headless:

    $env:QT_QPA_PLATFORM = "offscreen"   # optional on Windows; required on CI/Linux
    python scripts/capture_screenshots.py
"""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from smartdrive.app import bootstrap, shutdown
from smartdrive.config.constants import FuelType, ThemePreference, TransmissionType
from smartdrive.models.diagnostic import ModelRunStatus
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.services.scenarios import ScenarioId
from smartdrive.services.simulator import SimulationConfig
from smartdrive.ui.application import GuiApplication, ensure_qapplication


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def capture(output: Path, width: int, height: int) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    ensure_qapplication()
    written: list[Path] = []
    with tempfile.TemporaryDirectory() as home:
        ctx = bootstrap(home=Path(home), console_logging=False)
        ctx.settings.monitoring.refresh_interval_ms = 250
        gui = GuiApplication(ctx)
        ui, window = gui.ui, gui.window
        vehicle = ui.vehicles.add(
            VehicleProfile(
                name="Family Hatchback",
                manufacturer="Toyota",
                model="Aqua",
                year=2017,
                fuel_type=FuelType.HYBRID,
                transmission=TransmissionType.CVT,
                engine_capacity_cc=1500,
                mileage_km=86_400,
                registration_number="CAB-4821",
            )
        )
        ui.state.set_active_vehicle(vehicle.id)
        ui.state.reload()
        window.resize(width, height)
        window.show()
        ui.monitoring.configure_simulation(
            SimulationConfig(scenario=ScenarioId.OVERHEATING, seed=7, fault_development_s=40)
        )
        ui.monitoring.set_speed_factor(10.0)
        # Poll fast enough that the 60 s analysis window fills within a few seconds of wall time.
        ctx.settings.monitoring.refresh_interval_ms = 100
        ctx.settings.diagnostics.inference_interval_s = 1.0
        ui.diagnostics.apply_settings()
        _wait_until(lambda: not ui.diagnostics.models_loading, 20_000, "model loading")
        ui.monitoring.start(record=True, vehicle_id=vehicle.id)
        wait(9000)
        _wait_until(
            lambda: (
                ui.diagnostics.latest is not None
                and ui.diagnostics.latest.classifier.status is ModelRunStatus.OK
                and bool(ui.diagnostics.latest.explanations)
            ),
            60_000,
            "a classifier explanation",
        )
        for key in ("dashboard", "monitoring", "simulation", "diagnostics"):
            window.show_page(key)
            wait(700)
            written.append(_grab(window, output / f"{key}.png"))
        diagnostics_page = window.pages["diagnostics"]
        scroll = diagnostics_page.findChild(QScrollArea)
        anchor = diagnostics_page.contribution_chart  # type: ignore[attr-defined]
        if scroll is not None:
            scroll.verticalScrollBar().setValue(
                anchor.mapTo(scroll.widget(), anchor.rect().topLeft()).y() - 380
            )
            wait(400)
            written.append(_grab(window, output / "diagnostics-explanations.png"))
        window.pages["monitoring"].set_selected(  # type: ignore[attr-defined]
            [
                "coolant_temp_c",
                "rpm",
                "speed_kph",
                "control_module_voltage_v",
                "oil_pressure_kpa",
                "engine_load_pct",
            ]
        )
        ui.monitoring.stop()
        window.show_page("garage")
        wait(700)
        written.append(_grab(window, output / "garage.png"))
        for key in ("settings", "about"):
            window.show_page(key)
            wait(400)
            written.append(_grab(window, output / f"{key}.png"))
        ui.theme.set_preference(ThemePreference.LIGHT)
        ui.monitoring.start()
        wait(4000)
        window.show_page("dashboard")
        wait(700)
        written.append(_grab(window, output / "dashboard-light.png"))
        ui.monitoring.stop()
        window.show_page("garage")
        window.sidebar.set_collapsed(True, animate=False)
        wait(500)
        written.append(_grab(window, output / "garage-light-collapsed.png"))
        gui.shutdown()
        shutdown(ctx)
    QApplication.processEvents()
    return written


def _wait_until(condition: Callable[[], bool], timeout_ms: int, what: str) -> None:
    waited = 0
    while not condition():
        if waited >= timeout_ms:
            raise SystemExit(f"Timed out waiting for {what}; screenshots would be misleading.")
        wait(200)
        waited += 200


def _grab(window: QWidget, path: Path) -> Path:
    window.grab().save(str(path))
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/screenshots"))
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()
    for path in capture(args.output, args.width, args.height):
        print(path)


if __name__ == "__main__":
    main()
