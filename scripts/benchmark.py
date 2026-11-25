"""Reproducible performance evaluation of SmartDrive Guardian AI.

Measures, on the computer it runs on (results record the environment):

* cold and warm start-up of the desktop application (separate processes);
* memory after start-up, during simulation, inference and trip recording;
* CPU use and GUI event-loop lateness during sustained monitoring;
* per-window AI inference latency (rules, classifier, anomaly detector, explanations);
* database write throughput, trip-history query and replay loading/seek times;
* PDF and CSV report generation time;
* shutdown duration with every worker busy;
* long-running memory growth and bounded buffers, threads and timers;
* size of a PyInstaller distribution, when one has been built.

All telemetry is simulated. Nothing here measures diagnostic accuracy.

    QT_QPA_PLATFORM=offscreen python scripts/benchmark.py --sustained-minutes 10 \\
        --output docs/performance/results-linux.json
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# --- process metrics --------------------------------------------------------------------------


def rss_mb() -> float:
    """Resident set size of this process in MiB (Linux /proc, Windows PSAPI)."""
    if sys.platform == "win32":

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
        ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            handle, ctypes.byref(counters), counters.cb
        )
        return counters.WorkingSetSize / 2**20
    with Path("/proc/self/status").open(encoding="ascii") as status:
        for line in status:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return float("nan")


def os_threads() -> int | None:
    """Native threads of this process (Linux /proc); None where not available."""
    try:
        for line in Path("/proc/self/status").read_text("ascii").splitlines():
            if line.startswith("Threads:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def environment() -> dict[str, Any]:
    import sklearn

    from smartdrive import __version__
    from smartdrive.ai.model_registry import ModelRegistry

    cpu = platform.processor() or platform.machine()
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    ram = None
    if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
        ram = round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30, 1)
    return {
        "app_version": __version__,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "ram_gib": ram,
        "qt_platform": os.environ.get("QT_QPA_PLATFORM", "default"),
        "scikit_learn": sklearn.__version__,
        "models": {k: v.get("version") for k, v in ModelRegistry().manifest().items()},
        "frozen": bool(getattr(sys, "frozen", False)),
    }


def summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "n": len(values),
        "median": round(statistics.median(values), 3),
        "p95": round(p95, 3),
        "max": round(ordered[-1], 3),
        "mean": round(statistics.fmean(values), 3),
    }


# --- start-up ---------------------------------------------------------------------------------

STARTUP_PROBE = r"""
import json, sys, time
t0 = time.perf_counter()
from PySide6.QtWidgets import QApplication
from smartdrive.app import bootstrap, shutdown
from smartdrive.ui.application import GuiApplication, ensure_qapplication
t_import = time.perf_counter()
app = ensure_qapplication([])
ctx = bootstrap(home=__import__("pathlib").Path(sys.argv[1]), console_logging=False)
t_boot = time.perf_counter()
gui = GuiApplication(ctx, install_excepthook=False)
gui.window.show()
app.processEvents()
t_shown = time.perf_counter()
sys.path.insert(0, sys.argv[2])
from benchmark import rss_mb
rss = rss_mb()
t1 = time.perf_counter()
gui.shutdown(); shutdown(ctx)
t_end = time.perf_counter()
print(json.dumps({"imports_s": t_import - t0, "bootstrap_s": t_boot - t_import,
    "window_s": t_shown - t_boot, "to_window_s": t_shown - t0, "rss_mb": rss,
    "shutdown_s": t_end - t1}))
"""


def measure_startup(runs: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="smartdrive-bench-") as tmp:
        home = Path(tmp) / "home"

        def once() -> dict[str, float]:
            wall = time.perf_counter()
            out = subprocess.run(  # noqa: S603 - fixed interpreter and probe
                [sys.executable, "-c", STARTUP_PROBE, str(home), str(ROOT / "scripts")],
                capture_output=True,
                text=True,
                check=True,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            )
            data = json.loads(out.stdout.strip().splitlines()[-1])
            data["process_wall_s"] = time.perf_counter() - wall
            return data

        results["first_launch_new_data_folder"] = {k: round(v, 3) for k, v in once().items()}
        warm = [once() for _ in range(runs)]
        results["repeat_launches"] = {key: summary([w[key] for w in warm]) for key in warm[0]}
    results["method"] = (
        "Separate Python process per launch: imports, bootstrap (settings, logging, "
        "migrations), main window construction with all pages, first paint. 'First launch' "
        "uses a new data folder (database created and migrated); OS file caches are not "
        "cleared, so it is not a true cold-boot figure. Repeat launches reuse the folder."
    )
    return results


# --- micro-benchmarks -------------------------------------------------------------------------


def timed(fn: Callable[[], Any], repeat: int) -> list[float]:
    values = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        values.append((time.perf_counter() - start) * 1000)
    return values


def measure_components(work: Path) -> dict[str, Any]:
    from smartdrive.ai.model_registry import ModelRegistry
    from smartdrive.config.constants import DataSource, FuelType, TransmissionType
    from smartdrive.config.settings import DiagnosticSettings
    from smartdrive.core.rule_engine import VehicleContext
    from smartdrive.core.telemetry_window import WINDOW_SECONDS, TelemetryWindow
    from smartdrive.database.connection import Database
    from smartdrive.models.vehicle import VehicleProfile
    from smartdrive.reporting.report_templates import ReportRequest, ReportType
    from smartdrive.selftest import simulate_drive
    from smartdrive.services.diagnostic_engine import DiagnosticEngine
    from smartdrive.services.maintenance_service import MaintenanceService
    from smartdrive.services.notification_service import NotificationService
    from smartdrive.services.obd_service import ObdHistoryService
    from smartdrive.services.replay_service import ReplaySource
    from smartdrive.services.report_service import CsvDataset, ReportService
    from smartdrive.services.scenarios import ScenarioId
    from smartdrive.services.simulator import SimulationConfig, SimulationSource
    from smartdrive.services.telemetry_service import TelemetryService
    from smartdrive.services.trip_service import TripService
    from smartdrive.services.vehicle_service import VehicleService

    results: dict[str, Any] = {}
    start = time.perf_counter()
    models = ModelRegistry().load()
    results["model_loading_ms"] = round((time.perf_counter() - start) * 1000, 1)

    # Inference latency on 60 s windows from the overheating scenario.
    source = SimulationSource(SimulationConfig(scenario=ScenarioId.OVERHEATING, seed=7))
    source.open()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    samples = []
    for second in range(400):
        frame = source.read(1.0)
        if frame.sample is not None:
            samples.append(
                (
                    float(second),
                    frame.sample.model_copy(update={"timestamp": base + timedelta(seconds=second)}),
                )
            )
    source.close()
    engine = DiagnosticEngine(models, DiagnosticSettings(), VehicleContext(FuelType.PETROL))
    windows = [
        TelemetryWindow.from_samples(
            [(t, s) for t, s in samples if end - WINDOW_SECONDS < t <= end]
        )
        for end in range(60, 400, 2)
    ]
    window_ms = timed(lambda: TelemetryWindow.from_samples(samples[-60:]), 200)
    results["telemetry_window_build_ms"] = summary(window_ms)
    latencies = []
    for window in windows:
        begin = time.perf_counter()
        engine.assess(window, data_source=DataSource.SIMULATION, timestamp=base)
        latencies.append((time.perf_counter() - begin) * 1000)
    results["inference_latency_ms"] = summary(latencies)
    results["inference_note"] = (
        "One full assessment per 60-second window: rules, Random Forest classifier, Isolation "
        "Forest, tree-path explanations and health score. Simulated data."
    )

    # Database writes and trip queries.
    db = Database(work / "bench.db")
    db.upgrade()
    vehicle = VehicleService(db, work / "images").add(
        VehicleProfile(
            name="Benchmark (fictional)",
            manufacturer="Example",
            model="Bench",
            year=2020,
            fuel_type=FuelType.PETROL,
            transmission=TransmissionType.MANUAL,
            engine_capacity_cc=1500,
            mileage_km=0,
        )
    )
    telemetry = TelemetryService(db)
    trips = TripService(db, telemetry)
    batch = [s for _t, s in samples] * 5  # 2000 samples
    write_rates = []
    session_ids = []
    for index in range(20):
        session = telemetry.start_session(
            vehicle.id,
            DataSource.SIMULATION,
            name=f"bench {index}",
            started_at=base + timedelta(hours=index),
        )
        shifted = [
            s.model_copy(update={"timestamp": base + timedelta(hours=index, seconds=i)})
            for i, s in enumerate(batch)
        ]
        begin = time.perf_counter()
        telemetry.append(session.id, shifted)
        write_rates.append(len(shifted) / (time.perf_counter() - begin))
        telemetry.end_session(session.id)
        trips.finalize(session.id)
        session_ids.append(session.id)
    results["database_write_samples_per_s"] = summary(write_rates)
    results["database_rows"] = {"trips": 20, "telemetry_samples": 20 * len(batch)}
    results["trip_list_query_ms"] = summary(timed(lambda: trips.list_trips(), 30))
    results["trip_detail_query_ms"] = summary(timed(lambda: trips.get_trip(session_ids[5]), 30))
    loaded: list[Any] = []
    results["trip_samples_load_ms"] = summary(
        timed(lambda: loaded.append(telemetry.load_samples(session_ids[5])), 10)
    )
    replay_samples = loaded[-1]
    results["replay_prepare_ms"] = summary(
        timed(
            lambda: ReplaySource(
                replay_samples, session_id=1, original_source=DataSource.SIMULATION
            ),
            20,
        )
    )
    replay = ReplaySource(replay_samples, session_id=1, original_source=DataSource.SIMULATION)
    results["replay_seek_ms"] = summary(timed(lambda: replay.seek(replay.duration_s / 2), 200))
    results["replay_trip_samples"] = len(replay_samples)

    # Reports, on a trip recorded through the diagnostic pipeline.
    session_id, latest = simulate_drive(db, models, vehicle.id, seconds=300, start=base)
    trips.finalize(session_id)
    service = ReportService(
        db,
        telemetry=telemetry,
        trips=trips,
        obd=ObdHistoryService(db),
        maintenance=MaintenanceService(db),
        notifications=NotificationService(db),
    )
    reports: dict[str, Any] = {}
    for kind in (ReportType.TRIP, ReportType.VEHICLE_OVERVIEW, ReportType.MODEL_EVALUATION):
        request = ReportRequest(
            kind,
            vehicle_id=None if kind is ReportType.MODEL_EVALUATION else vehicle.id,
            session_id=session_id if kind is ReportType.TRIP else None,
        )
        reports[f"pdf_{kind.value}_ms"] = summary(
            timed(
                lambda request=request, kind=kind: service.generate_pdf(
                    request, work / f"{kind.value}.pdf", overwrite=True, live=latest
                ),
                5,
            )
        )
    reports["csv_telemetry_2000_rows_ms"] = summary(
        timed(
            lambda: service.export_csv(
                CsvDataset.TELEMETRY,
                work / "t.csv",
                vehicle_id=vehicle.id,
                session_id=session_ids[0],
                overwrite=True,
            ),
            5,
        )
    )
    results["reports"] = reports
    db.dispose()
    return results


# --- sustained GUI run ------------------------------------------------------------------------


def measure_sustained(minutes: float, work: Path) -> dict[str, Any]:
    from PySide6.QtCore import QObject, QTimer

    from smartdrive.app import bootstrap, shutdown
    from smartdrive.config.constants import FuelType, TransmissionType
    from smartdrive.models.vehicle import VehicleProfile
    from smartdrive.services.scenarios import ScenarioId
    from smartdrive.services.simulator import SimulationConfig
    from smartdrive.ui.application import GuiApplication, ensure_qapplication

    app = ensure_qapplication([])
    ctx = bootstrap(home=work / "sustained", console_logging=False)
    ctx.settings.alerts.desktop_notifications = False
    ctx.settings.monitoring.refresh_interval_ms = 1000
    ctx.settings.diagnostics.inference_interval_s = 2.0
    gui = GuiApplication(ctx, install_excepthook=False)
    gui.window.resize(1366, 768)
    gui.window.show()
    rss_after_start = rss_mb()
    vehicle = gui.ui.vehicles.add(
        VehicleProfile(
            name="Sustained (fictional)",
            manufacturer="Example",
            model="Bench",
            year=2020,
            fuel_type=FuelType.PETROL,
            transmission=TransmissionType.MANUAL,
            engine_capacity_cc=1500,
            mileage_km=0,
        )
    )
    gui.ui.state.set_active_vehicle(vehicle.id)
    gui.ui.state.reload()
    deadline = time.monotonic() + 60
    while gui.ui.diagnostics.models_loading and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    monitoring = gui.ui.monitoring
    monitoring.configure_simulation(
        # Several faults developing over the run: rules, model findings and alerts all fire.
        SimulationConfig(scenario=ScenarioId.MULTIPLE, seed=3)
    )
    monitoring.set_speed_factor(1.0)
    monitoring.start(record=True, vehicle_id=vehicle.id)

    lateness: list[float] = []
    expected = [time.perf_counter() + 0.05]

    def tick() -> None:
        now = time.perf_counter()
        lateness.append(max(0.0, (now - expected[0]) * 1000))
        expected[0] = now + 0.05

    probe = QTimer()
    probe.setInterval(50)
    probe.timeout.connect(tick)
    probe.start()

    owners: list[QObject] = [
        gui.window,
        gui.ui.monitoring,
        gui.ui.diagnostics,
        gui.ui.connection,
        gui.ui.notifications,
        gui.ui.trips,
        gui.ui.tasks,
    ]
    samples: list[dict[str, float]] = []
    frames = [0]
    monitoring.frame_received.connect(lambda _f: frames.__setitem__(0, frames[0] + 1))
    total = minutes * 60
    started = time.monotonic()
    cpu_started = time.process_time()
    next_sample = started
    while time.monotonic() - started < total:
        app.processEvents()
        if time.monotonic() >= next_sample:
            gc.collect()
            samples.append(
                {
                    "t_s": round(time.monotonic() - started, 1),
                    "rss_mb": round(rss_mb(), 1),
                    "buffer_points": len(monitoring.buffer),
                    "python_threads": threading.active_count(),
                    "os_threads": os_threads() or -1,
                    "qtimers": sum(len(o.findChildren(QTimer)) for o in owners),
                    "notifications_in_db": len(gui.ui.notifications.service.list_notifications()),
                }
            )
            next_sample += 60
        time.sleep(0.005)
    elapsed = time.monotonic() - started
    cpu = time.process_time() - cpu_started
    probe.stop()
    session_id = monitoring.session_id
    stop_started = time.perf_counter()
    monitoring.stop()
    stop_s = time.perf_counter() - stop_started
    # Shutdown with replay running and a report job queued.
    if session_id is not None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            app.processEvents()
            if gui.ui.trips.trips.get_trip(session_id).summary is not None:
                break
            time.sleep(0.05)
        gui.ui.trips.start_replay(session_id, speed=4.0)
        for _ in range(100):
            app.processEvents()
            time.sleep(0.01)
    gui.ui.tasks.submit("benchmark job", lambda: time.sleep(0.2))
    shutdown_started = time.perf_counter()
    gui.shutdown()
    shutdown_s = time.perf_counter() - shutdown_started
    shutdown(ctx)

    first, last = samples[1] if len(samples) > 1 else samples[0], samples[-1]
    hours = max(1e-9, (last["t_s"] - first["t_s"]) / 3600)
    return {
        "duration_s": round(elapsed, 1),
        "settings": "1 Hz refresh (real time), inference every 2 s, trip recording on, simulated",
        "frames_received": frames[0],
        "rss_after_start_mb": round(rss_after_start, 1),
        "rss_mb": summary([s["rss_mb"] for s in samples]),
        "rss_growth_mb_per_hour_after_first_minute": round(
            (last["rss_mb"] - first["rss_mb"]) / hours, 1
        ),
        "cpu_percent_of_one_core": round(100 * cpu / elapsed, 1),
        "event_loop_lateness_ms": summary(lateness),
        "buffer_points_max": max(s["buffer_points"] for s in samples),
        "python_threads": sorted({s["python_threads"] for s in samples}),
        "os_threads": sorted({s["os_threads"] for s in samples}),
        "qtimers": sorted({s["qtimers"] for s in samples}),
        "stop_monitoring_s": round(stop_s, 3),
        "shutdown_with_replay_and_job_s": round(shutdown_s, 3),
        "timeline": samples,
    }


def distribution_size() -> dict[str, Any]:
    dist = ROOT / "dist" / "SmartDrive-Guardian-AI"
    if not dist.is_dir():
        return {"status": "not built"}
    files = [p for p in dist.rglob("*") if p.is_file()]
    return {
        "status": "measured",
        "platform_of_build": platform.system(),
        "files": len(files),
        "mib": round(sum(p.stat().st_size for p in files) / 2**20, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-runs", type=int, default=5)
    parser.add_argument("--sustained-minutes", type=float, default=10.0)
    args = parser.parse_args()
    results: dict[str, Any] = {"environment": environment()}
    print("start-up...", flush=True)
    results["startup"] = measure_startup(args.startup_runs)
    with tempfile.TemporaryDirectory(prefix="smartdrive-bench-") as tmp:
        print("components...", flush=True)
        results["components"] = measure_components(Path(tmp))
        print(f"sustained run ({args.sustained_minutes} min)...", flush=True)
        results["sustained"] = measure_sustained(args.sustained_minutes, Path(tmp))
    results["distribution"] = distribution_size()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
