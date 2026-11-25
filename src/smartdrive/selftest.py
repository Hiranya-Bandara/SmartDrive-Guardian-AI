"""Headless self-test of an installation (source or packaged).

``smartdrive self-test`` exercises the real application stack end to end in a throw-away data
folder: directories, settings, database migration and integrity, bundled resources, trusted
model loading, a simulated drive through the diagnostic engine, trip summary, maintenance
persistence, PDF and CSV export, serial-port discovery (listing only, never connecting), the
offline voice backend and the Qt platform plugin. It is what the Windows build scripts run
against the frozen executable, so a missing DLL, Qt plugin, migration script or model file
shows up as a named failing check instead of a crash on a user's computer.

The user's own data is never touched unless ``--home`` points at it explicitly. All telemetry is
simulated and labelled as such.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from smartdrive import APP_NAME, __version__

logger = logging.getLogger(__name__)

SIMULATED_SECONDS: Final = 240
ANALYSIS_EVERY_S: Final = 2


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    duration_ms: float


@dataclass(slots=True)
class SelfTestReport:
    app_version: str
    frozen: bool
    python: str
    platform: str
    data_folder: str
    started_at: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    def to_json(self) -> str:
        payload: dict[str, Any] = asdict(self)
        payload["passed"] = self.passed
        return json.dumps(payload, indent=2)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


class _State:
    """Objects shared between consecutive checks."""

    def __init__(self) -> None:
        self.context: Any = None
        self.models: Any = None
        self.vehicle_id: int | None = None
        self.session_id: int | None = None
        self.latest: Any = None
        self.qt_app: Any = None


def _require[T](value: T | None, what: str) -> T:
    if value is None:
        raise RuntimeError(f"No {what}: an earlier check did not complete.")
    return value


def simulate_drive(
    database: Any,
    models: Any,
    vehicle_id: int,
    *,
    seconds: int = SIMULATED_SECONDS,
    start: datetime | None = None,
    seed: int = 2026,
) -> tuple[int, Any]:
    """Run the engine-overheating simulation through the real diagnostic pipeline.

    Returns the recorded session id and the last assessment. Data is labelled SIMULATION.
    """
    from smartdrive.config.constants import DataSource, FuelType
    from smartdrive.config.settings import DiagnosticSettings
    from smartdrive.core.rule_engine import VehicleContext
    from smartdrive.core.telemetry_window import WINDOW_SECONDS, TelemetryWindow
    from smartdrive.services.diagnostic_engine import DiagnosticEngine
    from smartdrive.services.diagnostic_service import DiagnosticService
    from smartdrive.services.scenarios import ScenarioId
    from smartdrive.services.simulator import SimulationConfig, SimulationSource
    from smartdrive.services.telemetry_service import TelemetryService

    start = start or datetime.now(UTC).replace(microsecond=0)
    telemetry = TelemetryService(database)
    diagnostics = DiagnosticService(database)
    diagnostics.register_models(models)
    engine = DiagnosticEngine(models, DiagnosticSettings(), VehicleContext(FuelType.PETROL))
    session = telemetry.start_session(
        vehicle_id,
        DataSource.SIMULATION,
        scenario=ScenarioId.OVERHEATING.value,
        random_seed=seed,
        name="Self-test simulated drive",
        started_at=start,
    )
    source = SimulationSource(
        SimulationConfig(scenario=ScenarioId.OVERHEATING, seed=seed, fault_development_s=60)
    )
    source.open()
    times: list[float] = []
    samples: list[Any] = []
    latest = None
    try:
        for second in range(seconds):
            frame = source.read(1.0)
            if frame.sample is None:
                continue
            sample = frame.sample.model_copy(
                update={"timestamp": start + timedelta(seconds=second)}
            )
            samples.append(sample)
            times.append(float(second))
            if second % ANALYSIS_EVERY_S == 0 and second >= 30:
                recent = [
                    (t, s)
                    for t, s in zip(times, samples, strict=True)
                    if t > second - WINDOW_SECONDS
                ]
                latest = engine.assess(
                    TelemetryWindow.from_samples(recent),
                    data_source=DataSource.SIMULATION,
                    timestamp=sample.timestamp,
                    vehicle_id=vehicle_id,
                    session_id=session.id,
                )
                diagnostics.record(latest, history_interval_s=10, alert_cooldown_s=60)
    finally:
        source.close()
    telemetry.append(session.id, samples)
    telemetry.end_session(session.id)
    return session.id, latest


def _check_paths(state: _State, home: Path) -> str:
    from smartdrive.app import bootstrap

    state.context = bootstrap(home=home, console_logging=False)
    paths = state.context.paths
    for directory in (paths.data_dir, paths.config_dir, paths.log_dir, paths.backup_dir):
        probe = directory / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    return f"Writable: data, config, logs, backups under {home}"


def _check_settings(state: _State) -> str:
    from smartdrive.config.settings import SettingsStore

    ctx = state.context
    ctx.save_settings()
    reloaded = SettingsStore(ctx.paths.settings_file).load()
    if reloaded != ctx.settings:
        raise AssertionError("Settings changed after a save and reload.")
    if reloaded.diagnostics.live_ml_enabled:
        raise AssertionError("Experimental live ML must be off by default.")
    return "Defaults saved and reloaded; experimental live ML is off by default."


def _check_database(state: _State) -> str:
    from sqlalchemy import text

    db = state.context.database
    current, head = db.current_revision(), db.head_revision()
    if current != head:
        raise AssertionError(f"Schema at {current}, expected {head}.")
    if not db.integrity_check():
        raise AssertionError("SQLite integrity check failed.")
    with db.session() as session:
        problems = session.execute(text("PRAGMA foreign_key_check")).fetchall()
    if problems:
        raise AssertionError(f"Foreign-key check reported {len(problems)} problem(s).")
    return f"Migrated to {head}; integrity and foreign-key checks passed."


def _check_resources(state: _State) -> str:
    from smartdrive.resources import missing_resources

    missing = missing_resources()
    if missing:
        raise AssertionError("Missing bundled resources: " + ", ".join(missing))
    return "Themes, branding, migrations and model files present."


def _check_models(state: _State) -> str:
    from smartdrive.ai.model_registry import LoadStatus, ModelRegistry

    state.models = ModelRegistry().load()
    bad = {k: v for k, v in state.models.status.items() if v is not LoadStatus.AVAILABLE}
    if bad:
        detail = "; ".join(f"{k}: {v.value} ({state.models.messages[k]})" for k, v in bad.items())
        raise AssertionError(detail)
    return "; ".join(f"{k} {v}" for k, v in state.models.messages.items())


def _check_simulation(state: _State) -> str:
    from smartdrive.config.constants import FuelType, TransmissionType
    from smartdrive.models.vehicle import VehicleProfile
    from smartdrive.services.vehicle_service import VehicleService

    ctx = state.context
    vehicle = VehicleService(ctx.database, ctx.paths.data_dir / "images").add(
        VehicleProfile(
            name="Self-test vehicle (fictional)",
            manufacturer="Example",
            model="Test",
            year=2020,
            fuel_type=FuelType.PETROL,
            transmission=TransmissionType.MANUAL,
            engine_capacity_cc=1500,
            mileage_km=0,
        )
    )
    state.vehicle_id = vehicle.id
    state.session_id, state.latest = simulate_drive(ctx.database, state.models, vehicle.id)
    if state.latest is None:
        raise AssertionError("The diagnostic engine produced no assessment.")
    findings = len(state.latest.findings)
    if findings == 0:
        raise AssertionError("The overheating scenario produced no diagnostic findings.")
    return f"{SIMULATED_SECONDS} s simulated; {findings} finding(s) in the last assessment."


def _check_trip(state: _State) -> str:
    from smartdrive.services.telemetry_service import TelemetryService
    from smartdrive.services.trip_service import TripService

    db = state.context.database
    session_id = _require(state.session_id, "simulated trip")
    summary = TripService(db, TelemetryService(db)).finalize(session_id)
    if not summary:
        raise AssertionError("The trip summary is empty.")
    return f"Trip #{session_id} summarised ({len(summary)} fields)."


def _check_maintenance(state: _State) -> str:
    from smartdrive.config.constants import MaintenanceCategory, MaintenanceStatus
    from smartdrive.models.maintenance import MaintenanceRecordInput
    from smartdrive.services.maintenance_service import MaintenanceService

    vehicle_id = _require(state.vehicle_id, "self-test vehicle")
    service = MaintenanceService(state.context.database)
    added = service.add_record(
        vehicle_id,
        MaintenanceRecordInput(
            category=MaintenanceCategory.ENGINE_OIL,
            title="Self-test record",
            status=MaintenanceStatus.COMPLETED,
            service_date=date.today(),
            cost=Decimal("100.00"),
            currency="LKR",
        ),
    )
    if added.id not in {record.id for record in service.records(vehicle_id)}:
        raise AssertionError("The maintenance record was not read back.")
    return "Record written and read back."


def _check_reports(state: _State, out_dir: Path) -> str:
    from smartdrive.reporting.report_templates import ReportRequest, ReportType
    from smartdrive.services.maintenance_service import MaintenanceService
    from smartdrive.services.notification_service import NotificationService
    from smartdrive.services.obd_service import ObdHistoryService
    from smartdrive.services.report_service import CsvDataset, ReportService
    from smartdrive.services.telemetry_service import TelemetryService
    from smartdrive.services.trip_service import TripService

    db = state.context.database
    telemetry = TelemetryService(db)
    service = ReportService(
        db,
        telemetry=telemetry,
        trips=TripService(db, telemetry),
        obd=ObdHistoryService(db),
        maintenance=MaintenanceService(db),
        notifications=NotificationService(db),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = service.generate_pdf(
        ReportRequest(ReportType.TRIP, vehicle_id=state.vehicle_id, session_id=state.session_id),
        out_dir / "self-test-trip.pdf",
        live=state.latest,
    ).path
    if not pdf.read_bytes().startswith(b"%PDF"):
        raise AssertionError("The PDF report is not a PDF file.")
    csv = service.export_csv(
        CsvDataset.TELEMETRY,
        out_dir / "self-test-telemetry.csv",
        vehicle_id=state.vehicle_id,
        session_id=state.session_id,
    ).path
    rows = csv.read_text("utf-8-sig").count("\n")
    if rows < 2:
        raise AssertionError("The CSV export has no data rows.")
    return f"PDF {pdf.stat().st_size // 1024} KB; CSV {rows - 1} data rows."


def _check_serial(state: _State) -> str:
    from smartdrive.obd.discovery import list_serial_ports

    ports = list_serial_ports()
    return (
        f"{len(ports)} serial port(s) listed. No port was opened; connections are made only "
        "when the user chooses one."
    )


def _check_voice(state: _State) -> str:
    from smartdrive.services.voice import create_backend

    backend = create_backend()
    try:
        if backend.available:
            return f"Offline speech available ({len(backend.voices())} voice(s)); nothing spoken."
        return f"Speech unavailable, handled gracefully: {backend.unavailable_reason}"
    finally:
        backend.close()


def _check_qt(state: _State) -> str:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from smartdrive.resources import resource_path

    state.qt_app = QApplication.instance() or QApplication([APP_NAME])
    icon = QIcon(str(resource_path("branding", "smartdrive-icon.svg")))
    if icon.isNull() or icon.pixmap(32, 32).isNull():
        raise AssertionError("The SVG application icon could not be rendered (QtSvg plugin?).")
    return f"Qt platform '{state.qt_app.platformName()}' loaded; SVG icon rendered."


def _check_logs(state: _State) -> str:
    log_file: Path = state.context.paths.log_file
    if not log_file.is_file() or log_file.stat().st_size == 0:
        raise AssertionError(f"No log written at {log_file}.")
    return f"Log written ({log_file.stat().st_size} bytes)."


@contextmanager
def _home(home: Path | None, keep: bool) -> Iterator[Path]:
    if home is not None:
        yield home
        return
    root = Path(tempfile.mkdtemp(prefix="smartdrive-selftest-"))
    try:
        yield root
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def run_self_test(
    *,
    home: Path | None = None,
    keep: bool = False,
    include_qt: bool = True,
    progress: Callable[[CheckResult], None] | None = None,
) -> SelfTestReport:
    """Run every check in order. A failed check is recorded and later dependent checks skip."""
    from smartdrive.app import shutdown

    with _home(home, keep) as root:
        report = SelfTestReport(
            app_version=__version__,
            frozen=is_frozen(),
            python=platform.python_version(),
            platform=platform.platform(terse=True),
            data_folder=str(root),
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        state = _State()
        steps: list[tuple[str, Callable[[], str], bool]] = [
            ("data folders", lambda: _check_paths(state, root), True),
            ("settings", lambda: _check_settings(state), False),
            ("database", lambda: _check_database(state), True),
            ("bundled resources", lambda: _check_resources(state), False),
            ("model artifacts", lambda: _check_models(state), True),
            ("simulation and diagnostics", lambda: _check_simulation(state), True),
            ("trip summary", lambda: _check_trip(state), False),
            ("maintenance", lambda: _check_maintenance(state), False),
            ("reports", lambda: _check_reports(state, root / "exports"), False),
            ("serial discovery", lambda: _check_serial(state), False),
            ("offline voice", lambda: _check_voice(state), False),
        ]
        if include_qt:
            steps.append(("qt platform", lambda: _check_qt(state), False))
        steps.append(("log file", lambda: _check_logs(state), False))
        blocked: str | None = None
        try:
            for name, step, required in steps:
                started = time.perf_counter()
                if blocked is not None:
                    result = CheckResult(name, False, f"Skipped: {blocked} failed.", 0.0)
                else:
                    try:
                        detail = step()
                        ok = True
                    except Exception as exc:
                        logger.exception("Self-test check failed", extra={"check": name})
                        detail, ok = f"{type(exc).__name__}: {exc}", False
                    elapsed = (time.perf_counter() - started) * 1000
                    result = CheckResult(name, ok, detail, round(elapsed, 1))
                    if not ok and required:
                        blocked = name
                report.checks.append(result)
                if progress is not None:
                    progress(result)
        finally:
            if state.context is not None:
                shutdown(state.context)
    return report


def main_self_test(home: Path | None, report_path: Path | None, keep: bool, no_qt: bool) -> int:
    def show(result: CheckResult) -> None:
        mark = "PASS" if result.ok else "FAIL"
        print(f"[{mark}] {result.name}: {result.detail}", flush=True)

    if no_qt is False and not os.environ.get("QT_QPA_PLATFORM") and sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    report = run_self_test(home=home, keep=keep, include_qt=not no_qt, progress=show)
    print(f"{APP_NAME} {__version__} self-test: {'PASSED' if report.passed else 'FAILED'}")
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.to_json(), encoding="utf-8")
    return 0 if report.passed else 1
