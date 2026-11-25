"""Report types and the templates that turn gathered data into a :class:`ReportDocument`.

Templates only format data they are given; every number comes from the database, the trained
model manifest or the evaluation file written by the training script. Missing values are shown
as "—" and sections without data say so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from smartdrive.config.constants import SAFETY_DISCLAIMER, DataSource, UnitSystem
from smartdrive.core.sensors import SENSORS
from smartdrive.reporting.document import (
    BarChart,
    Block,
    Heading,
    KeyValues,
    LineChart,
    Notice,
    ReportDocument,
    Series,
    Table,
    Text,
)

DASH: Final = "—"


class ReportType(StrEnum):
    VEHICLE_DIAGNOSTIC = "vehicle_diagnostic"
    AI_ASSESSMENT = "ai_assessment"
    TROUBLE_CODES = "trouble_codes"
    TRIP = "trip"
    MAINTENANCE = "maintenance"
    VEHICLE_OVERVIEW = "vehicle_overview"
    MODEL_EVALUATION = "model_evaluation"

    @property
    def label(self) -> str:
        return {
            "vehicle_diagnostic": "Vehicle diagnostic report",
            "ai_assessment": "AI diagnostic assessment report",
            "trouble_codes": "Diagnostic trouble code report",
            "trip": "Trip report",
            "maintenance": "Vehicle maintenance history report",
            "vehicle_overview": "Comprehensive vehicle overview",
            "model_evaluation": "Model evaluation report",
        }[self.value]

    @property
    def needs_vehicle(self) -> bool:
        return self is not ReportType.MODEL_EVALUATION

    @property
    def needs_trip(self) -> bool:
        return self is ReportType.TRIP


SECTIONS: Final[dict[str, str]] = {
    "vehicle": "Vehicle information",
    "trips": "Trip statistics",
    "sensors": "Sensor summaries",
    "findings": "Diagnostic findings",
    "codes": "Trouble codes",
    "health": "Experimental health score",
    "models": "Model information",
    "explanations": "Explainable AI evidence",
    "maintenance": "Maintenance",
    "charts": "Charts",
    "recommendations": "Recommendations",
}

DEFAULT_SECTIONS: Final[dict[ReportType, tuple[str, ...]]] = {
    ReportType.VEHICLE_DIAGNOSTIC: (
        "vehicle",
        "trips",
        "findings",
        "codes",
        "health",
        "charts",
        "recommendations",
    ),
    ReportType.AI_ASSESSMENT: (
        "vehicle",
        "findings",
        "health",
        "models",
        "explanations",
        "charts",
        "recommendations",
    ),
    ReportType.TROUBLE_CODES: ("vehicle", "codes", "findings", "recommendations"),
    ReportType.TRIP: (
        "vehicle",
        "trips",
        "sensors",
        "findings",
        "health",
        "charts",
        "recommendations",
    ),
    ReportType.MAINTENANCE: ("vehicle", "maintenance", "charts", "recommendations"),
    ReportType.VEHICLE_OVERVIEW: tuple(SECTIONS),
    ReportType.MODEL_EVALUATION: ("models", "charts"),
}


@dataclass(frozen=True, slots=True)
class ReportRequest:
    report_type: ReportType
    vehicle_id: int | None = None
    start: datetime | None = None
    end: datetime | None = None
    session_id: int | None = None
    sections: frozenset[str] = frozenset()
    include_identifiers: bool = False
    include_notes: bool = False

    def wants(self, section: str) -> bool:
        return section in (self.sections or set(DEFAULT_SECTIONS[self.report_type]))


@dataclass
class ReportData:
    """Everything a template may show. Filled by the report service."""

    vehicle: dict[str, Any] | None = None
    trips: list[dict[str, Any]] = field(default_factory=list)
    trip: dict[str, Any] | None = None
    sensor_summary: list[dict[str, Any]] = field(default_factory=list)
    trip_series: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    codes: list[dict[str, Any]] = field(default_factory=list)
    scans: list[dict[str, Any]] = field(default_factory=list)
    health: list[tuple[datetime, int | None]] = field(default_factory=list)
    assessment_summary: dict[str, Any] | None = None
    explanations: list[dict[str, Any]] = field(default_factory=list)
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    evaluation: dict[str, Any] | None = None
    maintenance_records: list[dict[str, Any]] = field(default_factory=list)
    schedules: list[dict[str, Any]] = field(default_factory=list)
    costs: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, str]] = field(default_factory=list)
    observation_evidence: str = ""
    recommendations: list[str] = field(default_factory=list)
    data_sources: dict[str, int] = field(default_factory=dict)
    completeness: float | None = None


def fmt(value: Any, digits: int = 1, unit: str = "") -> str:
    if value is None:
        return DASH
    if isinstance(value, float):
        text = f"{value:,.{digits}f}"
    elif isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        text = moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    else:
        text = str(value)
    return f"{text} {unit}".strip() if unit else text


def source_label(data_sources: dict[str, int]) -> str:
    if not data_sources:
        return "No recorded telemetry in this period"
    names = {
        DataSource.SIMULATION.value: "simulated",
        DataSource.LIVE.value: "live vehicle (OBD-II)",
        DataSource.REPLAY.value: "replayed",
    }
    return ", ".join(f"{names.get(k, k)} ({v})" for k, v in sorted(data_sources.items()))


def limitations(data: ReportData, request: ReportRequest) -> list[Block]:
    blocks: list[Block] = [
        Heading("Limitations", 1),
        Notice("warning", "Not a safety certification", SAFETY_DISCLAIMER),
        Notice(
            "limitation",
            "Experimental models trained on synthetic data",
            "The machine-learning models were trained and evaluated only on simulated "
            "telemetry. Their outputs, the experimental health score and any probabilities are "
            "not validated on real vehicles. The absence of findings does not mean the vehicle "
            "is safe to drive.",
        ),
    ]
    if DataSource.LIVE.value in data.data_sources:
        blocks.append(
            Notice(
                "limitation",
                "Live OBD-II data",
                "Generic OBD-II provides only the parameters a vehicle chooses to report; oil "
                "pressure is never available. Rule thresholds are generic unless vehicle-specific "
                "values were entered. Trouble-code descriptions are generic and manufacturer "
                "meanings may differ.",
            )
        )
    if request.report_type is ReportType.TRIP or data.trips:
        blocks.append(
            Notice(
                "limitation",
                "Estimated distance",
                "Distances are estimated by integrating recorded vehicle speed over time. Gaps "
                "longer than 5 seconds are not bridged, so the estimate can be lower than the "
                "real distance. No GPS or odometer data is used.",
            )
        )
    return blocks


def _vehicle(data: ReportData, request: ReportRequest) -> list[Block]:
    v = data.vehicle
    if v is None:
        return []
    rows = [
        ("Name", v["name"]),
        ("Vehicle", f"{v['year']} {v['manufacturer']} {v['model']}"),
        ("Fuel / transmission", f"{v['fuel_type']} / {v['transmission']}"),
        ("Engine capacity", fmt(v.get("engine_capacity_cc"), unit="cc")),
        ("Recorded odometer", fmt(v.get("mileage_km"), 0, "km")),
    ]
    if request.include_identifiers:
        rows.append(("Registration", v.get("registration_number") or DASH))
        rows.append(("VIN", v.get("vin") or DASH))
    if request.include_notes and v.get("notes"):
        rows.append(("Notes", v["notes"]))
    return [Heading("Vehicle", 1), KeyValues(tuple(rows))]


def _trips(data: ReportData) -> list[Block]:
    if not data.trips:
        return [Heading("Trips", 1), Text("No recorded trips in this period.", "muted")]
    rows = tuple(
        (
            fmt(t["started_at"]),
            t["name"] or f"Trip #{t['id']}",
            t["data_source"],
            fmt(t.get("duration_min"), 1, "min"),
            fmt(t.get("distance_km"), 1, "km (est.)"),
            fmt(t.get("max_speed_kph"), 0, "km/h"),
            str(t.get("warning_count", DASH)),
            str(t.get("critical_count", DASH)),
        )
        for t in data.trips
    )
    return [
        Heading("Trips", 1),
        Table(
            ("Started", "Trip", "Data", "Duration", "Distance", "Max speed", "Warn.", "Crit."),
            rows,
            widths=(2.2, 2.0, 1.2, 1.2, 1.7, 1.3, 0.8, 0.8),
        ),
    ]


def _trip_detail(data: ReportData, request: ReportRequest) -> list[Block]:
    trip = data.trip
    if trip is None:
        return []
    s = trip.get("summary") or {}
    coverage = s.get("distance_coverage")
    blocks: list[Block] = [
        Heading("Trip summary", 1),
        KeyValues(
            (
                ("Trip", trip["name"] or f"Trip #{trip['id']}"),
                ("Data source", trip["data_source_label"]),
                ("Recording status", trip["status"]),
                ("Started / ended", f"{fmt(trip['started_at'])} / {fmt(trip['ended_at'])}"),
                ("Recorded duration", fmt((s.get("recorded_duration_s") or 0) / 60, 1, "min")),
                ("Samples", str(s.get("sample_count", trip.get("sample_count", DASH)))),
                ("Data completeness (core sensors)", fmt(_pct(s.get("data_completeness")), 0, "%")),
                (
                    "Estimated distance",
                    f"{fmt(s.get('distance_km'), 2, 'km')} (speed integration; "
                    f"{fmt(_pct(coverage), 0, '%')} of time covered)",
                ),
                (
                    "Average / maximum speed",
                    f"{fmt(s.get('avg_speed_kph'))} / {fmt(s.get('max_speed_kph'))} km/h",
                ),
                (
                    "Average / maximum engine speed",
                    f"{fmt(s.get('avg_rpm'), 0)} / {fmt(s.get('max_rpm'), 0)} rpm",
                ),
                (
                    "Coolant temperature range",
                    f"{fmt(s.get('min_coolant_c'))} – {fmt(s.get('max_coolant_c'))} °C",
                ),
                (
                    "Diagnostic events (warnings / critical)",
                    f"{s.get('diagnostic_event_count', 0)} "
                    f"({s.get('warning_count', 0)} / {s.get('critical_count', 0)})",
                ),
                (
                    "Model versions",
                    ", ".join(f"{k} {v}" for k, v in (s.get("model_versions") or {}).items())
                    or DASH,
                ),
            )
        ),
    ]
    if request.wants("sensors") and data.sensor_summary:
        blocks += [
            Heading("Sensor summary", 2),
            Table(
                ("Sensor", "Unit", "Minimum", "Average", "Maximum", "Readings present"),
                tuple(
                    (
                        r["label"],
                        r["unit"],
                        fmt(r["min"]),
                        fmt(r["mean"]),
                        fmt(r["max"]),
                        fmt(_pct(r["completeness"]), 0, "%"),
                    )
                    for r in data.sensor_summary
                ),
                widths=(3, 1, 1.2, 1.2, 1.2, 1.4),
            ),
        ]
    if request.wants("charts") and data.trip_series:
        for key, title, unit in (
            ("speed_kph", "Vehicle speed", "km/h"),
            ("rpm", "Engine speed", "rpm"),
            ("coolant_temp_c", "Coolant temperature", "°C"),
        ):
            points = data.trip_series.get(key, [])
            if len(points) >= 2:
                blocks.append(
                    LineChart(title, "Minutes since start", unit, (Series(title, tuple(points)),))
                )
    if data.events:
        blocks += [
            Heading("Diagnostic timeline", 2),
            Table(
                ("Time", "Severity", "Event", "Source"),
                tuple(
                    (fmt(e["occurred_at"]), e["severity"], e["title"], e["source"] or DASH)
                    for e in data.events
                ),
                widths=(2, 1.5, 5, 1.5),
                severity_column=1,
            ),
        ]
    return blocks


FINDING_GROUP_GAP_S: Final = 120.0


def group_findings(findings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated records of one condition into episodes.

    The diagnostic history stores a persisting finding every few seconds. A report lists each
    episode once: consecutive records with the same source, severity and summary that are no more
    than ``FINDING_GROUP_GAP_S`` apart. A change of severity starts a new episode. The CSV export
    keeps every individual record.
    """
    episodes: list[dict[str, Any]] = []
    open_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for f in sorted(findings, key=lambda item: item["created_at"]):
        key = (f["source"], f["severity"], f["summary"], f.get("data_source") or "")
        episode = open_by_key.get(key)
        if (
            episode is not None
            and (f["created_at"] - episode["last_seen"]).total_seconds() <= FINDING_GROUP_GAP_S
        ):
            episode["last_seen"] = f["created_at"]
            episode["count"] += 1
            continue
        episode = {**f, "first_seen": f["created_at"], "last_seen": f["created_at"], "count": 1}
        open_by_key[key] = episode
        episodes.append(episode)
    return episodes


def _episode_time(episode: dict[str, Any]) -> str:
    first, last = episode["first_seen"], episode["last_seen"]
    if last == first:
        return fmt(first)
    end = last.strftime("%H:%M") if last.date() == first.date() else fmt(last)
    return f"{fmt(first)} – {end}"


def _findings(data: ReportData) -> list[Block]:
    if not data.findings:
        return [
            Heading("Diagnostic findings", 1),
            Text(
                "No warning or critical findings were recorded in this period. This does not "
                "confirm that the vehicle is free of faults.",
                "muted",
            ),
        ]
    episodes = group_findings(data.findings)
    rows = tuple(
        (
            _episode_time(e),
            e["severity"],
            e["summary"],
            e["source"],
            str(e["count"]),
            e["data_source"] or DASH,
        )
        for e in episodes
    )
    return [
        Heading("Diagnostic findings", 1),
        Text(
            "Findings are indications to check, not confirmed mechanical faults. Rule findings "
            "come from transparent thresholds; model findings are experimental. Repeated records "
            "of one condition are shown as a single episode; the CSV export lists every record.",
            "small",
        ),
        Table(
            ("Time", "Severity", "Finding", "Source", "Count", "Data"),
            rows,
            widths=(2.6, 1.5, 3.9, 1.3, 0.9, 1.2),
            severity_column=1,
        ),
    ]


def _codes(data: ReportData) -> list[Block]:
    blocks: list[Block] = [Heading("Diagnostic trouble codes", 1)]
    if not data.scans:
        blocks.append(Text("No trouble-code scans were recorded for this vehicle.", "muted"))
        return blocks
    latest = data.scans[0]
    blocks.append(
        KeyValues(
            (
                ("Latest scan", fmt(latest["scanned_at"])),
                ("Adapter", "Mock adapter (simulated data)" if latest["is_mock"] else "OBD-II"),
                (
                    "Malfunction indicator lamp",
                    {True: "On", False: "Off"}.get(latest["mil_on"], "Not reported"),
                ),
                (
                    "Stored / pending / permanent",
                    f"{latest['stored_count']} / "
                    f"{latest['pending_count']} / " + _permanent_text(latest["permanent_count"]),
                ),
            )
        )
    )
    blocks.append(
        Table(
            ("Code", "Status", "Description", "First seen", "Last seen", "Active"),
            tuple(
                (
                    c["code"],
                    c["status"],
                    c["description"],
                    fmt(c["first_seen_at"]),
                    fmt(c["last_seen_at"]),
                    "yes" if c["is_active"] else "no",
                )
                for c in data.codes
            ),
            widths=(1, 1.2, 4.2, 2, 2, 0.8),
            empty_text="The latest scan reported no trouble codes.",
        )
    )
    blocks.append(
        Text(
            "Descriptions are generic paraphrases from SmartDrive's local reference; "
            "manufacturer-specific codes are shown as unknown. A trouble code records that a "
            "control unit detected a condition — it does not confirm that a component failed. "
            "SmartDrive reads codes only and never clears them.",
            "small",
        )
    )
    return blocks


def _health(data: ReportData, request: ReportRequest) -> list[Block]:
    points = [(t, s) for t, s in data.health if s is not None]
    blocks: list[Block] = [Heading("Experimental health score", 1)]
    if not points:
        blocks.append(Text("No health score was available in this period.", "muted"))
        return blocks
    scores = [s for _, s in points]
    blocks.append(
        KeyValues(
            (
                ("Analyses with a score", str(len(scores))),
                ("Latest / lowest / highest", f"{scores[-1]} / {min(scores)} / {max(scores)}"),
            )
        )
    )
    if request.wants("charts") and len(points) >= 2:
        start = points[0][0]
        span_s = (points[-1][0] - start).total_seconds()
        divisor, unit = (60.0, "Minutes") if span_s <= 3 * 3600 else (3600.0, "Hours")
        series = tuple(((t - start).total_seconds() / divisor, float(s)) for t, s in points)
        blocks.append(
            LineChart(
                "Health score",
                f"{unit} since first analysis",
                "score",
                (Series("Health score", series),),
            )
        )
    blocks.append(
        Text(
            "Experimental indicator combining rule findings, model outputs and alerts. It is not "
            "a safety rating.",
            "small",
        )
    )
    return blocks


def _models(data: ReportData) -> list[Block]:
    if not data.models:
        return [Heading("Models", 1), Text("No model manifest was found.", "muted")]
    rows = []
    for name, entry in data.models.items():
        rows.append(
            (
                name,
                entry.get("version", DASH),
                entry.get("model_type", DASH),
                entry.get("dataset_version", DASH),
                "yes" if entry.get("synthetic", True) else "no",
                fmt(entry.get("trained_at")),
            )
        )
    return [
        Heading("Models", 1),
        Table(
            ("Model", "Version", "Type", "Dataset", "Synthetic", "Trained"),
            tuple(rows),
            widths=(2, 1, 2.4, 1.4, 1, 2),
        ),
    ]


def _assessment(data: ReportData) -> list[Block]:
    a = data.assessment_summary
    if a is None:
        return [Heading("Latest assessment", 1), Text("No stored assessment.", "muted")]
    rows = [
        ("Time", fmt(a["created_at"])),
        ("Status", a["status"]),
        ("Data source", a["data_source"]),
        ("Classifier / anomaly detector", f"{a['classifier_status']} / {a['anomaly_status']}"),
        ("Data completeness", fmt(_pct(a["data_completeness"]), 0, "%")),
        ("Experimental health score", fmt(a["health_score"])),
    ]
    probabilities = a.get("probabilities") or {}
    blocks: list[Block] = [Heading("Latest assessment", 1), KeyValues(tuple(rows))]
    if probabilities:
        blocks.append(
            Table(
                ("Category", "Model output (not a failure probability)"),
                tuple((k, f"{v:.2f}") for k, v in probabilities.items()),
                widths=(2, 3),
            )
        )
    return blocks


def _explanations(data: ReportData) -> list[Block]:
    if not data.explanations:
        return [
            Heading("Explainable AI evidence", 1),
            Text(
                "No model explanation is available: explanations are produced only when the "
                "classifier ran on sufficient data, and they are not stored with the history.",
                "muted",
            ),
        ]
    blocks: list[Block] = [Heading("Explainable AI evidence", 1)]
    for item in data.explanations:
        blocks.append(
            BarChart(
                f"Largest feature contributions — {item['category']} (output "
                f"{item['probability']:.2f})",
                tuple(c[0] for c in item["contributions"]),
                tuple(abs(c[1]) for c in item["contributions"]),
                "Absolute contribution to the model output",
            )
        )
        blocks.append(
            Text(
                "Tree-path decomposition of the Random Forest output. "
                + "; ".join(
                    f"{label} {'raises' if value > 0 else 'lowers'} it by {abs(value):.3f}"
                    for label, value in item["contributions"]
                ),
                "small",
            )
        )
    return blocks


def _maintenance(data: ReportData, request: ReportRequest) -> list[Block]:
    blocks: list[Block] = [Heading("Maintenance", 1)]
    if data.schedules:
        blocks += [
            Heading("Schedules", 2),
            Table(
                ("Task", "Status", "Due date", "Due odometer", "Interval", "Source"),
                tuple(
                    (
                        s["task_name"],
                        s["state"],
                        fmt(s["due_date"]),
                        fmt(s["due_km"], 0, "km"),
                        s["interval"],
                        s["source"],
                    )
                    for s in data.schedules
                ),
                widths=(2.6, 1.8, 1.4, 1.5, 1.8, 1.2),
            ),
        ]
    else:
        blocks.append(Text("No maintenance schedules are configured.", "muted"))
    blocks += [
        Heading("Service history", 2),
        Table(
            ("Date", "Service", "Odometer", "Provider", "Cost"),
            tuple(
                (
                    fmt(r["service_date"]),
                    r["title"],
                    fmt(r["mileage_km"], 0, "km"),
                    r["provider"] or DASH,
                    f"{r['cost']} {r['currency']}" if r["cost"] is not None else DASH,
                )
                for r in data.maintenance_records
            ),
            widths=(1.5, 4, 1.6, 2.2, 1.7),
            empty_text="No maintenance records.",
        ),
    ]
    if data.costs:
        blocks.append(Heading("Costs by currency", 2))
        blocks.append(
            Table(
                ("Currency", "Total", "Records"),
                tuple((c["currency"], c["total"], str(c["record_count"])) for c in data.costs),
                widths=(1, 2, 1),
            )
        )
        if request.wants("charts"):
            for c in data.costs:
                if c["by_year"]:
                    blocks.append(
                        BarChart(
                            f"Maintenance spending per year ({c['currency']})",
                            tuple(c["by_year"].keys()),
                            tuple(float(v) for v in c["by_year"].values()),
                            c["currency"],
                        )
                    )
        blocks.append(
            Text("Amounts in different currencies are listed separately and never added.", "small")
        )
    if data.observations:
        blocks.append(Heading("AI-related maintenance observations (experimental)", 2))
        blocks.append(
            Table(
                ("Observation", "Evidence"),
                tuple((o["title"] + ": " + o["detail"], o["evidence"]) for o in data.observations),
                widths=(3, 2),
            )
        )
    if data.observation_evidence:
        blocks.append(Text(data.observation_evidence, "small"))
    return blocks


def _evaluation(data: ReportData, request: ReportRequest) -> list[Block]:
    evaluation = data.evaluation
    blocks: list[Block] = [Heading("Evaluation on synthetic held-out data", 1)]
    if evaluation is None:
        blocks.append(Text("The evaluation results file was not found.", "muted"))
        return blocks
    classifier = evaluation.get("classifier", {})
    overall = classifier.get("all_rows_model_output", {})
    per_label = overall.get("per_label", {})
    blocks.append(
        KeyValues(
            (
                ("Test sessions", str(classifier.get("sessions", DASH))),
                ("Macro-F1 (model)", fmt(overall.get("macro_f1"), 3)),
                ("Micro-F1 (model)", fmt(overall.get("micro_f1"), 3)),
                (
                    "Macro-F1 (rules only)",
                    fmt(classifier.get("rule_baseline", {}).get("macro_f1"), 3),
                ),
                (
                    "Isolation Forest ROC AUC",
                    fmt(
                        evaluation.get("anomaly_detector", {}).get("roc_auc_normal_vs_abnormal"), 3
                    ),
                ),
            )
        )
    )
    if per_label:
        blocks.append(
            Table(
                ("Category", "Precision", "Recall", "F1", "False-positive rate", "Support"),
                tuple(
                    (
                        name,
                        fmt(m.get("precision"), 3),
                        fmt(m.get("recall"), 3),
                        fmt(m.get("f1"), 3),
                        fmt(m.get("false_positive_rate"), 4),
                        str(m.get("support", DASH)),
                    )
                    for name, m in per_label.items()
                ),
                widths=(2, 1, 1, 1, 1.6, 1),
            )
        )
        if request.wants("charts"):
            blocks.append(
                BarChart(
                    "F1 score per category (synthetic test set)",
                    tuple(per_label),
                    tuple(float(m.get("f1") or 0.0) for m in per_label.values()),
                    "F1",
                )
            )
    blocks.append(
        Notice(
            "limitation",
            "Synthetic evaluation only",
            "These figures measure the models on simulated sessions held out from training. "
            "They do not demonstrate diagnostic accuracy on real vehicles.",
        )
    )
    return blocks


def _recommendations(data: ReportData) -> list[Block]:
    items = list(dict.fromkeys(r for r in data.recommendations if r))
    if not items:
        return []
    return [Heading("Recommendations", 1), *[Text(f"• {r}") for r in items[:12]]]


def _pct(value: float | None) -> float | None:
    return None if value is None else value * 100.0


def build_document(
    request: ReportRequest,
    data: ReportData,
    *,
    report_id: str,
    app_version: str,
    generated_at: datetime,
    period_label: str,
) -> ReportDocument:
    blocks: list[Block] = []
    kind = request.report_type
    if request.wants("vehicle"):
        blocks += _vehicle(data, request)
    if kind is ReportType.MODEL_EVALUATION:
        if request.wants("models"):
            blocks += _models(data)
        blocks += _evaluation(data, request)
    if kind is ReportType.TRIP:
        blocks += _trip_detail(data, request)
    elif request.wants("trips"):
        blocks += _trips(data)
    if kind is ReportType.AI_ASSESSMENT:
        blocks += _assessment(data)
    if request.wants("findings"):
        blocks += _findings(data)
    if request.wants("codes"):
        blocks += _codes(data)
    if request.wants("health") and kind is not ReportType.MODEL_EVALUATION:
        blocks += _health(data, request)
    if request.wants("models") and kind is not ReportType.MODEL_EVALUATION:
        blocks += _models(data)
    if request.wants("explanations"):
        blocks += _explanations(data)
    if request.wants("maintenance"):
        blocks += _maintenance(data, request)
    if request.wants("recommendations"):
        blocks += _recommendations(data)
    blocks += limitations(data, request)
    vehicle = data.vehicle
    return ReportDocument(
        title=kind.label,
        report_id=report_id,
        generated_at=generated_at,
        app_version=app_version,
        data_source_label=source_label(data.data_sources)
        if kind is not ReportType.MODEL_EVALUATION
        else "synthetic evaluation data",
        period_label=period_label,
        vehicle_label=vehicle["name"] if vehicle else "All vehicles",
        blocks=tuple(blocks),
    )


def sensor_rows(samples: Sequence[Any]) -> list[dict[str, Any]]:
    rows = []
    for spec in SENSORS:
        values = [getattr(s, spec.key) for s in samples if getattr(s, spec.key) is not None]
        rows.append(
            {
                "label": spec.label,
                "unit": spec.unit(UnitSystem.METRIC),
                "min": min(values) if values else None,
                "mean": sum(values) / len(values) if values else None,
                "max": max(values) if values else None,
                "completeness": len(values) / len(samples) if samples else 0.0,
            }
        )
    return rows


def _permanent_text(count: int | None) -> str:
    return "not supported" if count is None else str(count)
