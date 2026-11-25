"""Gathers stored data for reports and writes PDF and CSV files.

Every export is recorded in ``export_history`` with its outcome; a failed export is recorded as
failed and raised, never reported as a success. Report ids are random UUIDs. Vehicle
identifiers (registration, VIN) and personal notes are excluded unless explicitly requested.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select

from smartdrive import __version__
from smartdrive.ai.features import describe_feature
from smartdrive.ai.model_registry import EVALUATION_FILE, ModelRegistry
from smartdrive.config.constants import DataSource, ExportFormat, Severity
from smartdrive.database.connection import Database
from smartdrive.database.models import (
    DiagnosticAssessmentRecord,
    DiagnosticResultRecord,
    DrivingSessionRecord,
    ExportHistoryRecord,
    VehicleRecord,
)
from smartdrive.database.types import utc_now
from smartdrive.models.diagnostic import DiagnosticAssessment
from smartdrive.models.telemetry import SENSOR_FIELDS
from smartdrive.reporting.csv_exporter import Column, write_csv
from smartdrive.reporting.document import ReportDocument
from smartdrive.reporting.pdf_generator import render_pdf
from smartdrive.reporting.report_templates import (
    ReportData,
    ReportRequest,
    ReportType,
    build_document,
    fmt,
    sensor_rows,
)
from smartdrive.services.maintenance_service import MaintenanceService
from smartdrive.services.notification_service import NotificationService
from smartdrive.services.obd_service import ObdHistoryService
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.trip_service import TripService
from smartdrive.utils.exceptions import ExportError, RecordNotFoundError

logger = logging.getLogger(__name__)

MAX_FINDINGS: Final = 300
MAX_CHART_POINTS: Final = 600
SOURCE_LABELS: Final = {
    DataSource.SIMULATION: "Simulated telemetry",
    DataSource.LIVE: "Live vehicle telemetry (OBD-II)",
    DataSource.REPLAY: "Replayed recording",
}


class CsvDataset(StrEnum):
    TELEMETRY = "telemetry"
    TRIPS = "trips"
    FINDINGS = "findings"
    TROUBLE_CODES = "trouble_codes"
    HEALTH = "health"
    MAINTENANCE = "maintenance"
    NOTIFICATIONS = "notifications"
    MODEL_EVALUATION = "model_evaluation"

    @property
    def label(self) -> str:
        return {
            "telemetry": "Trip telemetry",
            "trips": "Recorded trips",
            "findings": "Diagnostic findings",
            "trouble_codes": "Trouble codes",
            "health": "Health score history",
            "maintenance": "Maintenance records",
            "notifications": "Notifications",
            "model_evaluation": "Model evaluation results",
        }[self.value]

    @property
    def needs_trip(self) -> bool:
        return self is CsvDataset.TELEMETRY


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    report_id: str
    rows: int | None
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ExportHistoryItem:
    id: int
    created_at: datetime
    report_type: str
    export_format: str
    file_name: str
    file_path: str | None
    status: str
    message: str


class ReportService:
    def __init__(
        self,
        database: Database,
        *,
        telemetry: TelemetryService,
        trips: TripService,
        obd: ObdHistoryService,
        maintenance: MaintenanceService,
        notifications: NotificationService,
        registry: ModelRegistry | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._db = database
        self._telemetry = telemetry
        self._trips = trips
        self._obd = obd
        self._maintenance = maintenance
        self._notifications = notifications
        self._registry = registry or ModelRegistry()
        self._clock = clock

    # -- gathering ------------------------------------------------------------------------------

    def gather(
        self, request: ReportRequest, *, live: DiagnosticAssessment | None = None
    ) -> ReportData:
        data = ReportData()
        kind = request.report_type
        vehicle_id = request.vehicle_id
        if kind.needs_vehicle and vehicle_id is None:
            raise ExportError("No vehicle", user_message="Select a vehicle for this report.")
        if kind.needs_trip and request.session_id is None:
            raise ExportError("No trip", user_message="Select a trip for this report.")
        if vehicle_id is not None:
            data.vehicle = self._vehicle(vehicle_id)
        if kind is ReportType.MODEL_EVALUATION or request.wants("models"):
            data.models = self._registry.manifest()
        if kind is ReportType.MODEL_EVALUATION:
            data.evaluation = self._evaluation()
            return data
        if vehicle_id is None:
            return data
        start, end = request.start, request.end
        if kind is ReportType.TRIP and request.session_id is not None:
            self._trip(data, request.session_id)
            start, end = None, None
        else:
            trips = self._trips.list_trips(vehicle_id=vehicle_id, start=start, end=end)
            data.trips = [
                {
                    "id": t.session.id,
                    "name": t.session.name,
                    "started_at": t.session.started_at,
                    "data_source": t.session.data_source.value,
                    "duration_min": None if t.duration_s is None else t.duration_s / 60,
                    **(t.summary or {}),
                }
                for t in trips
            ]
            data.data_sources = dict(Counter(t["data_source"] for t in data.trips))
        session_filter = request.session_id if kind is ReportType.TRIP else None
        if request.wants("findings") or request.wants("recommendations"):
            data.findings = self._findings(vehicle_id, start, end, session_filter)
            data.recommendations = [f["recommendation"] for f in data.findings]
        if request.wants("codes"):
            data.codes = [c.model_dump() for c in self._obd.trouble_codes(vehicle_id)]
            for code in data.codes:
                code["status"] = code["status"].value
            data.scans = [s.model_dump() for s in self._obd.scans(vehicle_id, limit=20)]
        if request.wants("health"):
            data.health = self._health(vehicle_id, start, end, session_filter)
        if kind is ReportType.AI_ASSESSMENT:
            data.assessment_summary = self._latest_assessment(vehicle_id, start, end)
        if request.wants("explanations") and live is not None and live.vehicle_id == vehicle_id:
            data.explanations = _explanations(live)
        if request.wants("maintenance"):
            self._maintenance_data(data, vehicle_id)
        return data

    def _vehicle(self, vehicle_id: int) -> dict[str, Any]:
        with self._db.session() as session:
            record = session.get(VehicleRecord, vehicle_id)
            if record is None:
                raise RecordNotFoundError(f"Vehicle {vehicle_id} does not exist.")
            return {
                "id": record.id,
                "name": record.name,
                "manufacturer": record.manufacturer,
                "model": record.model,
                "year": record.year,
                "fuel_type": record.fuel_type.value,
                "transmission": record.transmission.value,
                "engine_capacity_cc": record.engine_capacity_cc,
                "mileage_km": record.mileage_km if record.mileage_updated_at else None,
                "registration_number": record.registration_number,
                "vin": record.vin,
                "notes": record.notes,
            }

    def _trip(self, data: ReportData, session_id: int) -> None:
        trip = self._trips.get_trip(session_id)
        samples = self._telemetry.load_samples(session_id)
        source = trip.session.data_source
        label = SOURCE_LABELS.get(source, source.value)
        if trip.session.scenario == "mock-obd-adapter":
            label = "Simulated telemetry from the mock OBD-II adapter"
        data.trip = {
            "id": trip.session.id,
            "name": trip.session.name,
            "data_source_label": label,
            "status": trip.session.status.value,
            "started_at": trip.session.started_at,
            "ended_at": trip.session.ended_at,
            "sample_count": trip.sample_count,
            "summary": trip.summary,
        }
        data.data_sources = {source.value: 1}
        data.sensor_summary = sensor_rows(samples)
        if samples:
            start = samples[0].timestamp
            step = max(1, len(samples) // MAX_CHART_POINTS)
            for key in ("speed_kph", "rpm", "coolant_temp_c"):
                data.trip_series[key] = [
                    ((s.timestamp - start).total_seconds() / 60.0, float(getattr(s, key)))
                    for s in samples[::step]
                    if getattr(s, key) is not None
                ]
        data.events = [
            {
                "occurred_at": e.occurred_at,
                "severity": e.severity.value,
                "title": e.title,
                "source": e.source,
            }
            for e in self._trips.events(session_id)
        ]
        if trip.summary:
            data.completeness = trip.summary.get("data_completeness")

    def _findings(
        self,
        vehicle_id: int,
        start: datetime | None,
        end: datetime | None,
        session_id: int | None,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(DiagnosticResultRecord)
            .where(
                DiagnosticResultRecord.vehicle_id == vehicle_id,
                DiagnosticResultRecord.severity.in_((Severity.WARNING, Severity.CRITICAL)),
            )
            .order_by(DiagnosticResultRecord.created_at.desc())
            .limit(MAX_FINDINGS)
        )
        if session_id is not None:
            stmt = stmt.where(DiagnosticResultRecord.session_id == session_id)
        if start is not None:
            stmt = stmt.where(DiagnosticResultRecord.created_at >= start)
        if end is not None:
            stmt = stmt.where(DiagnosticResultRecord.created_at <= end)
        with self._db.session() as session:
            return [
                {
                    "created_at": r.created_at,
                    "severity": r.severity.value,
                    "summary": r.summary,
                    "source": r.source.value,
                    "category": r.category.value,
                    "data_source": r.data_source.value if r.data_source else None,
                    "session_id": r.session_id,
                    "recommendation": r.recommendation.split("\n")[0] if r.recommendation else "",
                    "confidence": r.confidence,
                    "model_version": r.model_version,
                    "explanation": r.explanation.get("text", "") if r.explanation else "",
                }
                for r in session.scalars(stmt)
            ]

    def _health(
        self,
        vehicle_id: int,
        start: datetime | None,
        end: datetime | None,
        session_id: int | None,
    ) -> list[tuple[datetime, int | None]]:
        stmt = (
            select(DiagnosticAssessmentRecord.created_at, DiagnosticAssessmentRecord.health_score)
            .where(DiagnosticAssessmentRecord.vehicle_id == vehicle_id)
            .order_by(DiagnosticAssessmentRecord.created_at)
        )
        if session_id is not None:
            stmt = stmt.where(DiagnosticAssessmentRecord.session_id == session_id)
        if start is not None:
            stmt = stmt.where(DiagnosticAssessmentRecord.created_at >= start)
        if end is not None:
            stmt = stmt.where(DiagnosticAssessmentRecord.created_at <= end)
        with self._db.session() as session:
            return [(t, s) for t, s in session.execute(stmt)]

    def _latest_assessment(
        self, vehicle_id: int, start: datetime | None, end: datetime | None
    ) -> dict[str, Any] | None:
        stmt = (
            select(DiagnosticAssessmentRecord)
            .where(DiagnosticAssessmentRecord.vehicle_id == vehicle_id)
            .order_by(DiagnosticAssessmentRecord.created_at.desc())
            .limit(1)
        )
        if start is not None:
            stmt = stmt.where(DiagnosticAssessmentRecord.created_at >= start)
        if end is not None:
            stmt = stmt.where(DiagnosticAssessmentRecord.created_at <= end)
        with self._db.session() as session:
            record = session.scalar(stmt)
            if record is None:
                return None
            return {
                "created_at": record.created_at,
                "status": record.status.value,
                "data_source": record.data_source.value,
                "classifier_status": record.classifier_status,
                "anomaly_status": record.anomaly_status,
                "data_completeness": record.data_completeness,
                "health_score": record.health_score,
                "probabilities": dict(record.probabilities or {}),
            }

    def _maintenance_data(self, data: ReportData, vehicle_id: int) -> None:
        data.maintenance_records = [r.model_dump() for r in self._maintenance.records(vehicle_id)]
        statuses = self._maintenance.statuses(vehicle_id)
        data.schedules = [
            {
                "task_name": s.schedule.task_name,
                "state": s.state.label,
                "due_date": s.due_date,
                "due_km": s.due_km,
                "interval": _interval_text(s.schedule.interval_days, s.schedule.interval_km),
                "source": "example" if s.schedule.interval_source == "example" else "user",
            }
            for s in statuses
        ]
        data.costs = [
            {
                "currency": c.currency,
                "total": f"{c.total:,.2f}",
                "record_count": c.record_count,
                "by_year": c.by_year,
            }
            for c in self._maintenance.cost_summary(vehicle_id)
        ]
        observations, evidence = self._maintenance.observations(vehicle_id)
        data.observations = [
            {"title": o.title, "detail": o.detail, "evidence": o.evidence} for o in observations
        ]
        data.observation_evidence = evidence
        data.recommendations += [o.detail for o in observations]

    def _evaluation(self) -> dict[str, Any] | None:
        path = self._registry.directory / EVALUATION_FILE
        if not path.is_file():
            return None
        try:
            loaded = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Evaluation file is unreadable")
            return None
        return loaded if isinstance(loaded, dict) else None

    # -- documents ------------------------------------------------------------------------------

    def build(
        self, request: ReportRequest, *, live: DiagnosticAssessment | None = None
    ) -> ReportDocument:
        data = self.gather(request, live=live)
        return build_document(
            request,
            data,
            report_id=str(uuid.uuid4()),
            app_version=__version__,
            generated_at=self._clock(),
            period_label=_period(request),
        )

    def generate_pdf(
        self,
        request: ReportRequest,
        path: Path,
        *,
        overwrite: bool = False,
        live: DiagnosticAssessment | None = None,
    ) -> ExportResult:
        path = Path(path)
        try:
            if path.exists() and not overwrite:
                raise ExportError(
                    f"{path} exists", user_message="A file with that name already exists."
                )
            document = self.build(request, live=live)
            render_pdf(document, path)
        except ExportError as exc:
            self._record(request.report_type.value, ExportFormat.PDF, path, request, None, exc)
            raise
        result = ExportResult(path, document.report_id, None, path.stat().st_size)
        self._record(request.report_type.value, ExportFormat.PDF, path, request, result, None)
        return result

    def export_csv(
        self,
        dataset: CsvDataset,
        path: Path,
        *,
        vehicle_id: int | None = None,
        session_id: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        overwrite: bool = False,
    ) -> ExportResult:
        path = Path(path)
        request = ReportRequest(
            ReportType.VEHICLE_OVERVIEW,
            vehicle_id=vehicle_id,
            start=start,
            end=end,
            session_id=session_id,
        )
        try:
            columns, rows = self._csv_rows(dataset, vehicle_id, session_id, start, end)
            count = write_csv(path, columns, rows, overwrite=overwrite)
        except ExportError as exc:
            self._record(f"csv:{dataset.value}", ExportFormat.CSV, path, request, None, exc)
            raise
        result = ExportResult(path, str(uuid.uuid4()), count, path.stat().st_size)
        self._record(f"csv:{dataset.value}", ExportFormat.CSV, path, request, result, None)
        return result

    def _csv_rows(
        self,
        dataset: CsvDataset,
        vehicle_id: int | None,
        session_id: int | None,
        start: datetime | None,
        end: datetime | None,
    ) -> tuple[list[Column], Iterable[Sequence[Any]]]:
        def need_vehicle() -> int:
            if vehicle_id is None:
                raise ExportError("No vehicle", user_message="Select a vehicle to export.")
            return vehicle_id

        if dataset is CsvDataset.TELEMETRY:
            if session_id is None:
                raise ExportError("No trip", user_message="Select a trip to export.")
            trip = self._trips.get_trip(session_id)
            samples = self._telemetry.load_samples(session_id, limit=1_000_000)
            extra_keys = sorted({k for s in samples for k in s.extra})
            columns = [
                Column("timestamp_utc"),
                Column("vehicle_id"),
                Column("trip_id"),
                Column("data_source"),
                *[Column(name) for name in SENSOR_FIELDS],
                Column("fuel_rate_estimated"),
                *[Column(f"extra_{k}") for k in extra_keys],
            ]
            rows = (
                [
                    s.timestamp,
                    trip.session.vehicle_id,
                    session_id,
                    trip.session.data_source,
                    *[getattr(s, name) for name in SENSOR_FIELDS],
                    s.fuel_rate_estimated,
                    *[s.extra.get(k) for k in extra_keys],
                ]
                for s in samples
            )
            return columns, rows
        if dataset is CsvDataset.TRIPS:
            trips = self._trips.list_trips(vehicle_id=vehicle_id, start=start, end=end)
            keys = (
                "sample_count",
                "recorded_duration_s",
                "data_completeness",
                "avg_speed_kph",
                "max_speed_kph",
                "avg_rpm",
                "max_rpm",
                "min_coolant_c",
                "max_coolant_c",
                "distance_km",
                "distance_coverage",
                "diagnostic_event_count",
                "warning_count",
                "critical_count",
                "anomaly_count",
                "dtc_count",
            )
            columns = [
                Column(n)
                for n in (
                    "trip_id",
                    "vehicle_id",
                    "vehicle_name",
                    "name",
                    "data_source",
                    "status",
                    "started_at_utc",
                    "ended_at_utc",
                    *keys,
                    "distance_is_estimate",
                )
            ]
            rows = (
                [
                    t.session.id,
                    t.session.vehicle_id,
                    t.vehicle_name,
                    t.session.name,
                    t.session.data_source,
                    t.session.status,
                    t.session.started_at,
                    t.session.ended_at,
                    *[(t.summary or {}).get(k) for k in keys],
                    True,
                ]
                for t in trips
            )
            return columns, rows
        if dataset is CsvDataset.FINDINGS:
            findings = self._findings(need_vehicle(), start, end, session_id)
            columns = [
                Column(n)
                for n in (
                    "created_at_utc",
                    "vehicle_id",
                    "trip_id",
                    "data_source",
                    "source",
                    "category",
                    "severity",
                    "summary",
                    "model_output",
                    "model_version",
                    "explanation",
                )
            ]
            vid = need_vehicle()
            rows = (
                [
                    f["created_at"],
                    vid,
                    f["session_id"],
                    f["data_source"],
                    f["source"],
                    f["category"],
                    f["severity"],
                    f["summary"],
                    f["confidence"],
                    f["model_version"],
                    f["explanation"],
                ]
                for f in findings
            )
            return columns, rows
        if dataset is CsvDataset.TROUBLE_CODES:
            vid = need_vehicle()
            columns = [
                Column(n)
                for n in (
                    "vehicle_id",
                    "code",
                    "status",
                    "description",
                    "description_source",
                    "first_seen_utc",
                    "last_seen_utc",
                    "detection_count",
                    "active",
                )
            ]
            rows = (
                [
                    vid,
                    c.code,
                    c.status,
                    c.description,
                    c.description_source,
                    c.first_seen_at,
                    c.last_seen_at,
                    c.detection_count,
                    c.is_active,
                ]
                for c in self._obd.trouble_codes(vid)
            )
            return columns, rows
        if dataset is CsvDataset.HEALTH:
            vid = need_vehicle()
            columns = [Column("created_at_utc"), Column("vehicle_id"), Column("health_score")]
            points = self._health(vid, start, end, session_id)
            return columns, ([t, vid, s] for t, s in points)
        if dataset is CsvDataset.MAINTENANCE:
            vid = need_vehicle()
            columns = [
                Column(n)
                for n in (
                    "record_id",
                    "vehicle_id",
                    "category",
                    "description",
                    "status",
                    "service_date",
                    "odometer_km",
                    "provider",
                    "cost",
                    "currency",
                    "next_due_date",
                    "next_due_odometer_km",
                )
            ]
            rows = (
                [
                    r.id,
                    vid,
                    r.category,
                    r.title,
                    r.status,
                    r.service_date,
                    r.mileage_km,
                    r.provider,
                    r.cost,
                    r.currency,
                    r.next_due_date,
                    r.next_due_km,
                ]
                for r in self._maintenance.records(vid)
            )
            return columns, rows
        if dataset is CsvDataset.NOTIFICATIONS:
            items = self._notifications.list_notifications(
                vehicle_id=vehicle_id, start=start, end=end, limit=100_000
            )
            columns = [
                Column(n)
                for n in (
                    "created_at_utc",
                    "last_occurrence_utc",
                    "vehicle_id",
                    "severity",
                    "category",
                    "title",
                    "message",
                    "occurrences",
                    "read_at_utc",
                    "acknowledged_at_utc",
                )
            ]
            rows = (
                [
                    n.created_at,
                    n.last_occurrence_at,
                    n.vehicle_id,
                    n.severity,
                    n.category,
                    n.title,
                    n.message,
                    n.occurrence_count,
                    n.read_at,
                    n.acknowledged_at,
                ]
                for n in items
            )
            return columns, rows
        evaluation = self._evaluation()
        if evaluation is None:
            raise ExportError(
                "Evaluation file missing", user_message="No model evaluation results were found."
            )
        per_label = (
            evaluation.get("classifier", {}).get("all_rows_model_output", {}).get("per_label", {})
        )
        columns = [
            Column(n)
            for n in (
                "category",
                "precision",
                "recall",
                "f1",
                "false_positive_rate",
                "false_negative_rate",
                "support",
                "data",
            )
        ]
        rows = (
            [
                name,
                m.get("precision"),
                m.get("recall"),
                m.get("f1"),
                m.get("false_positive_rate"),
                m.get("false_negative_rate"),
                m.get("support"),
                "synthetic test split",
            ]
            for name, m in per_label.items()
        )
        return columns, rows

    # -- history --------------------------------------------------------------------------------

    def _record(
        self,
        report_type: str,
        export_format: ExportFormat,
        path: Path,
        request: ReportRequest,
        result: ExportResult | None,
        error: ExportError | None,
    ) -> None:
        try:
            with self._db.session() as session:
                vehicle_id = request.vehicle_id
                if vehicle_id is not None and session.get(VehicleRecord, vehicle_id) is None:
                    vehicle_id = None
                session.add(
                    ExportHistoryRecord(
                        vehicle_id=vehicle_id,
                        report_type=report_type[:64],
                        export_format=export_format,
                        file_name=path.name[:255],
                        file_path=str(path)[:1024] if result else None,
                        created_at=self._clock(),
                        report_id=result.report_id if result else None,
                        status="success" if result else "failed",
                        file_size=result.size_bytes if result else None,
                        message="" if error is None else error.user_message,
                    )
                )
        except Exception:
            logger.warning("Export history could not be recorded", exc_info=True)

    def history(self, *, limit: int = 50) -> list[ExportHistoryItem]:
        stmt = (
            select(ExportHistoryRecord)
            .order_by(ExportHistoryRecord.created_at.desc(), ExportHistoryRecord.id.desc())
            .limit(limit)
        )
        with self._db.session() as session:
            return [
                ExportHistoryItem(
                    r.id,
                    r.created_at,
                    r.report_type,
                    r.export_format.value,
                    r.file_name,
                    r.file_path,
                    r.status,
                    r.message,
                )
                for r in session.scalars(stmt)
            ]

    def trip_choices(self, vehicle_id: int) -> list[tuple[int, str]]:
        with self._db.session() as session:
            rows = session.execute(
                select(
                    DrivingSessionRecord.id,
                    DrivingSessionRecord.name,
                    DrivingSessionRecord.started_at,
                    DrivingSessionRecord.data_source,
                )
                .where(
                    DrivingSessionRecord.vehicle_id == vehicle_id,
                    DrivingSessionRecord.data_source != DataSource.REPLAY,
                )
                .order_by(DrivingSessionRecord.started_at.desc())
                .limit(200)
            )
            return [
                (sid, f"{name or f'Trip #{sid}'} · {fmt(started)} · {source.value}")
                for sid, name, started, source in rows
            ]


def _explanations(assessment: DiagnosticAssessment) -> list[dict[str, Any]]:
    items = []
    for category, explanation in assessment.explanations.items():
        ranked = sorted(explanation.contributions, key=lambda c: abs(c.contribution), reverse=True)
        items.append(
            {
                "category": category.value,
                "probability": explanation.probability,
                "contributions": [
                    (describe_feature(c.feature), round(c.contribution, 4)) for c in ranked[:8]
                ],
            }
        )
    return items


def _interval_text(days: int | None, km: float | None) -> str:
    parts = []
    if days:
        parts.append(f"{days} days")
    if km:
        parts.append(f"{km:,.0f} km")
    return " or ".join(parts) or "—"


def _period(request: ReportRequest) -> str:
    if request.report_type is ReportType.MODEL_EVALUATION:
        return "Not applicable"
    if request.report_type is ReportType.TRIP:
        return f"Trip #{request.session_id}"
    if request.start is None and request.end is None:
        return "All recorded data"
    start = request.start.astimezone(UTC).strftime("%Y-%m-%d") if request.start else "beginning"
    end = request.end.astimezone(UTC).strftime("%Y-%m-%d") if request.end else "now"
    return f"{start} to {end}"
