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
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from smartdrive.app import bootstrap, shutdown
from smartdrive.config.constants import (
    FuelType,
    MaintenanceCategory,
    MaintenanceStatus,
    ThemePreference,
    TransmissionType,
)
from smartdrive.models.diagnostic import ModelRunStatus
from smartdrive.models.maintenance import MaintenanceRecordInput, ScheduleInput
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.obd.mock import MOCK_PORT
from smartdrive.services.maintenance_service import EXAMPLE_INTERVALS
from smartdrive.services.scenarios import ScenarioId
from smartdrive.services.simulator import SimulationConfig
from smartdrive.ui.application import GuiApplication, ensure_qapplication
from smartdrive.ui.dialogs.welcome import show_welcome


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
                # Fictional demonstration vehicle: no real make, registration or VIN.
                name="Demo Hatchback (fictional)",
                manufacturer="Example",
                model="Hatchback",
                year=2017,
                fuel_type=FuelType.HYBRID,
                transmission=TransmissionType.CVT,
                engine_capacity_cc=1500,
                mileage_km=86_400,
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
        written += _phase4_pages(gui, vehicle.id, output, Path(home))
        for key in ("settings", "about"):
            window.show_page(key)
            wait(400)
            written.append(_grab(window, output / f"{key}.png"))
        welcome = show_welcome(ui, window)
        wait(500)
        written.append(_grab(welcome, output / "welcome.png"))
        welcome.accept()
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


def _phase4_pages(gui: GuiApplication, vehicle_id: int, output: Path, home: Path) -> list[Path]:
    """Vehicle integration pages. Connected states use the MOCK adapter (labelled simulated)."""
    ui, window = gui.ui, gui.window
    written: list[Path] = []
    _wait_until(lambda: not ui.tasks.busy, 20_000, "the trip summary")
    window.show_page("connection")
    wait(600)
    written.append(_grab(window, output / "connection-no-adapter.png"))
    settings = ui.app.settings
    settings.obd.show_mock_adapter = True
    settings.obd.mock_profile = "stored_codes"
    settings.obd.poll_interval_ms = 500
    page = window.pages["connection"]
    page.refresh_ports()  # type: ignore[attr-defined]
    _wait_until(lambda: bool(ui.connection.ports), 10_000, "the port list")
    ui.connection.connect_adapter(MOCK_PORT, vehicle_id=vehicle_id)
    _wait_until(lambda: ui.connection.ecu_connected, 15_000, "the mock ECU")
    ui.monitoring.set_preferred_mode("live")
    ui.monitoring.start_live(ui.connection)
    wait(3000)
    written.append(_grab(window, output / "connection-mock-adapter.png"))
    ui.connection.scan_codes()
    _wait_until(lambda: ui.connection.last_scan is not None, 15_000, "the code scan")
    window.show_page("codes")
    wait(600)
    codes = window.pages["codes"]
    codes.code_table.selectRow(0)  # type: ignore[attr-defined]
    wait(300)
    written.append(_grab(window, output / "codes-mock-adapter.png"))
    ui.monitoring.stop()
    ui.connection.disconnect_adapter()
    _wait_until(lambda: ui.connection.report is None, 10_000, "the disconnection")
    ui.monitoring.set_preferred_mode("simulation")

    trips = window.pages["trips"]
    window.show_page("trips")
    wait(400)
    trips.table.selectRow(0)  # type: ignore[attr-defined]
    trips.replay_selected()  # type: ignore[attr-defined]
    _wait_until(lambda: ui.monitoring.replay_session_id is not None, 15_000, "the replay")
    ui.monitoring.set_replay_speed(4.0)
    wait(5000)
    written.append(_grab(window, output / "trips-replay.png"))
    ui.monitoring.stop()

    maintenance = ui.maintenance
    maintenance.record_odometer(vehicle_id, 86_400)
    days, km = EXAMPLE_INTERVALS[MaintenanceCategory.ENGINE_OIL]
    oil = maintenance.add_schedule(
        vehicle_id,
        ScheduleInput(
            category=MaintenanceCategory.ENGINE_OIL,
            task_name="Engine oil replacement",
            interval_days=days,
            interval_km=km,
            interval_source="example",
        ),
    )
    maintenance.add_schedule(
        vehicle_id,
        ScheduleInput(
            category=MaintenanceCategory.BRAKE_INSPECTION,
            task_name="Brake inspection",
            interval_days=365,
            last_done_date=date.today() - timedelta(days=380),
        ),
    )
    for when, odo, title, category, cost in (
        (
            date.today() - timedelta(days=200),
            77_100.0,
            "Engine oil and filter",
            MaintenanceCategory.ENGINE_OIL,
            "18500.00",
        ),
        (
            date.today() - timedelta(days=90),
            83_000.0,
            "Battery test",
            MaintenanceCategory.BATTERY,
            "1500.00",
        ),
    ):
        maintenance.add_record(
            vehicle_id,
            MaintenanceRecordInput(
                category=category,
                title=title,
                status=MaintenanceStatus.COMPLETED,
                service_date=when,
                mileage_km=odo,
                provider="Example Motors",
                cost=Decimal(cost),
                currency="LKR",
                schedule_id=oil.id if category is MaintenanceCategory.ENGINE_OIL else None,
            ),
        )
    window.show_page("maintenance")
    wait(600)
    written.append(_grab(window, output / "maintenance.png"))

    reports = window.pages["reports"]
    window.show_page("reports")
    target = home / "overview.pdf"
    request = reports.build_request()  # type: ignore[attr-defined]
    ui.reports.generate_pdf(request, target)
    reports._load_history()  # type: ignore[attr-defined]
    wait(500)
    written.append(_grab(window, output / "reports.png"))
    ui.notifications.check_maintenance()
    _wait_until(lambda: not ui.tasks.busy, 10_000, "the maintenance check")
    window.show_page("alerts")
    wait(600)
    written.append(_grab(window, output / "alerts.png"))
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
    # Lossless re-compression keeps text sharp and the files small.
    with Image.open(path) as image:
        image.load()
    image.save(path, optimize=True)
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
