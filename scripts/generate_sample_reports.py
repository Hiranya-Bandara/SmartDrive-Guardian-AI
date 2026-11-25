"""Generate sample PDF and CSV reports from clearly labelled SIMULATED data.

Everything is produced in a throw-away database: a fictional vehicle, one simulated trip run
through the real diagnostic engine, a trouble-code scan from the *mock* OBD-II adapter, and a
few maintenance records entered as examples. The user's own database is never touched.

    python scripts/generate_sample_reports.py [--output docs/samples]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from smartdrive.ai.model_registry import ModelRegistry
from smartdrive.config.constants import (
    DataSource,
    FuelType,
    MaintenanceCategory,
    MaintenanceStatus,
    NotificationCategory,
    NotificationSeverity,
    TransmissionType,
)
from smartdrive.config.settings import DiagnosticSettings
from smartdrive.core.rule_engine import VehicleContext
from smartdrive.core.telemetry_window import WINDOW_SECONDS, TelemetryWindow
from smartdrive.database.connection import Database
from smartdrive.models.diagnostic import DiagnosticAssessment
from smartdrive.models.maintenance import MaintenanceRecordInput, ScheduleInput
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.obd.mock import MOCK_PORT, PROFILES, MockElm327Transport
from smartdrive.obd.session import ConnectionParameters, ObdSession
from smartdrive.reporting.report_templates import ReportRequest, ReportType
from smartdrive.services.diagnostic_engine import DiagnosticEngine
from smartdrive.services.diagnostic_service import DiagnosticService
from smartdrive.services.maintenance_service import EXAMPLE_INTERVALS, MaintenanceService
from smartdrive.services.notification_service import NotificationService
from smartdrive.services.obd_service import ObdHistoryService
from smartdrive.services.report_service import CsvDataset, ReportService
from smartdrive.services.scenarios import ScenarioId
from smartdrive.services.simulator import SimulationConfig, SimulationSource
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.trip_service import TripService
from smartdrive.services.vehicle_service import VehicleService

ROOT = Path(__file__).resolve().parents[1]
DRIVE_SECONDS = 420
ANALYSIS_EVERY_S = 2


def simulate_trip(
    db: Database, vehicle_id: int, start: datetime
) -> tuple[int, DiagnosticAssessment | None]:
    telemetry = TelemetryService(db)
    diagnostics = DiagnosticService(db)
    models = ModelRegistry().load()
    diagnostics.register_models(models)
    settings = DiagnosticSettings()
    engine = DiagnosticEngine(models, settings, VehicleContext(FuelType.PETROL))
    session = telemetry.start_session(
        vehicle_id,
        DataSource.SIMULATION,
        scenario=ScenarioId.OVERHEATING.value,
        random_seed=2026,
        name="Sample simulated drive (engine overheating scenario)",
        started_at=start,
    )
    source = SimulationSource(
        SimulationConfig(scenario=ScenarioId.OVERHEATING, seed=2026, fault_development_s=120)
    )
    source.open()
    times: list[float] = []
    samples = []
    latest: DiagnosticAssessment | None = None
    for second in range(DRIVE_SECONDS):
        frame = source.read(1.0)
        if frame.sample is None:
            continue
        sample = frame.sample.model_copy(update={"timestamp": start + timedelta(seconds=second)})
        samples.append(sample)
        times.append(float(second))
        if second % ANALYSIS_EVERY_S == 0 and second >= 30:
            recent = [
                (t, s) for t, s in zip(times, samples, strict=True) if t > second - WINDOW_SECONDS
            ]
            window = TelemetryWindow.from_samples(recent)
            latest = engine.assess(
                window,
                data_source=DataSource.SIMULATION,
                timestamp=sample.timestamp,
                vehicle_id=vehicle_id,
                session_id=session.id,
            )
            diagnostics.record(latest, history_interval_s=10, alert_cooldown_s=60)
    telemetry.append(session.id, samples)
    telemetry.end_session(session.id)
    TripService(db, telemetry).finalize(session.id)
    return session.id, latest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "samples")
    args = parser.parse_args()
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="smartdrive-samples-"))
    db = Database(workdir / "samples.db")
    try:
        db.upgrade()
        vehicles = VehicleService(db, workdir / "images")
        vehicle = vehicles.add(
            VehicleProfile(
                name="Sample vehicle (fictional)",
                manufacturer="Example",
                model="Hatchback",
                year=2019,
                fuel_type=FuelType.PETROL,
                transmission=TransmissionType.CVT,
                engine_capacity_cc=1500,
                mileage_km=0,
            )
        )
        start = datetime(2026, 11, 20, 8, 30, tzinfo=UTC)
        trip_id, latest = simulate_trip(db, vehicle.id, start)

        obd = ObdHistoryService(db)
        transport = MockElm327Transport(PROFILES["stored_codes"]())
        session = ObdSession(
            ConnectionParameters(port=MOCK_PORT),
            transport_factory=lambda _p, _b: transport,
            clock=lambda: start + timedelta(minutes=10),
        )
        report = session.connect()
        connection_id = obd.record_connection(
            report, vehicle_id=vehicle.id, connection_method="Mock (no hardware)"
        )
        scan = session.scan_trouble_codes()
        obd.record_scan(
            vehicle.id,
            scan,
            data_source=DataSource.SIMULATION,
            is_mock=True,
            protocol=report.protocol_name,
            connection_id=connection_id,
        )
        session.close()
        obd.end_connection(connection_id, reason="Sample complete")

        maintenance = MaintenanceService(db)
        maintenance.record_odometer(vehicle.id, 48_200, when=datetime(2026, 11, 1, tzinfo=UTC))
        days, km = EXAMPLE_INTERVALS[MaintenanceCategory.ENGINE_OIL]
        oil = maintenance.add_schedule(
            vehicle.id,
            ScheduleInput(
                category=MaintenanceCategory.ENGINE_OIL,
                task_name="Engine oil replacement",
                interval_days=days,
                interval_km=km,
                interval_source="example",
            ),
        )
        maintenance.add_schedule(
            vehicle.id,
            ScheduleInput(
                category=MaintenanceCategory.BRAKE_INSPECTION,
                task_name="Brake inspection",
                interval_days=365,
                last_done_date=date(2025, 10, 1),
            ),
        )
        for when, odo, title, cost, provider in (
            (date(2025, 12, 3), 39_800.0, "Engine oil and filter", "18500.00", "Example Motors"),
            (date(2026, 5, 18), 44_100.0, "General inspection", "7500.00", "Example Motors"),
        ):
            maintenance.add_record(
                vehicle.id,
                MaintenanceRecordInput(
                    category=MaintenanceCategory.ENGINE_OIL
                    if "oil" in title.lower()
                    else MaintenanceCategory.GENERAL_INSPECTION,
                    title=title,
                    status=MaintenanceStatus.COMPLETED,
                    service_date=when,
                    mileage_km=odo,
                    provider=provider,
                    cost=Decimal(cost),
                    currency="LKR",
                    schedule_id=oil.id if "oil" in title.lower() else None,
                    notes="Sample record entered for demonstration.",
                ),
            )

        notifications = NotificationService(db)
        notifications.notify(
            NotificationSeverity.SUCCESS,
            NotificationCategory.TRIP,
            "Trip recorded",
            f"Trip #{trip_id} was saved (sample, simulated data).",
            vehicle_id=vehicle.id,
            now=start + timedelta(minutes=8),
        )
        notifications.notify(
            NotificationSeverity.WARNING,
            NotificationCategory.MAINTENANCE,
            "Brake inspection: overdue",
            "Maintenance schedule (sample). Intervals are the ones entered by the user.",
            vehicle_id=vehicle.id,
            now=start + timedelta(minutes=9),
        )
        telemetry = TelemetryService(db)
        service = ReportService(
            db,
            telemetry=telemetry,
            trips=TripService(db, telemetry),
            obd=obd,
            maintenance=maintenance,
            notifications=notifications,
        )
        written: list[Path] = []
        for kind in ReportType:
            request = ReportRequest(
                kind,
                vehicle_id=None if kind is ReportType.MODEL_EVALUATION else vehicle.id,
                session_id=trip_id if kind is ReportType.TRIP else None,
            )
            path = output / f"sample-{kind.value.replace('_', '-')}.pdf"
            result = service.generate_pdf(request, path, overwrite=True, live=latest)
            written.append(result.path)
        for dataset in CsvDataset:
            path = output / f"sample-{dataset.value.replace('_', '-')}.csv"
            result = service.export_csv(
                dataset,
                path,
                vehicle_id=vehicle.id,
                session_id=trip_id,
                overwrite=True,
            )
            written.append(result.path)
        for path in written:
            print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    finally:
        db.dispose()
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
