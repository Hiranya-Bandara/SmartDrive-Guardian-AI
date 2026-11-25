"""Reproducible synthetic dataset generation, splitting, validation and storage.

Each *session* is an independent simulated drive with its own seed, driving pattern, noise,
ambient temperature, data-quality problems and (optionally) faults with random onset, growth
rate, maximum severity and intermittency. Rows are 60-second feature windows taken every few
seconds. Whole sessions are assigned to train/validation/test, so neighbouring windows never
straddle a split.

Labels (one binary column per supported category) come from the simulator's ground truth and are
never used as features. Windows where a fault has started but is still below the labelling
threshold are *ambiguous* and excluded, so a barely-present fault is neither counted as normal
nor as a detectable fault.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import numpy as np

from smartdrive.ai.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, extract_features
from smartdrive.config.constants import FaultCategory, Severity
from smartdrive.core.rule_engine import RuleEngine
from smartdrive.core.telemetry_processing import build_sample
from smartdrive.core.telemetry_window import TelemetryWindow
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.services.scenarios import (
    FAULT_CATEGORY,
    ConnectionLossSpec,
    DrivingPattern,
    FaultKind,
    FaultSpec,
    ScenarioDefinition,
    ScenarioId,
)
from smartdrive.services.simulator import SimulationConfig, VehicleSimulator

LABELS: Final[tuple[FaultCategory, ...]] = (
    FaultCategory.COOLING,
    FaultCategory.LUBRICATION,
    FaultCategory.FUEL,
    FaultCategory.ELECTRICAL,
    FaultCategory.SENSOR,
)
UNSUPPORTED_CATEGORIES: Final = {
    FaultCategory.TRANSMISSION: "No transmission telemetry (gear, slip, fluid temperature) exists.",
    FaultCategory.BRAKE: "No brake telemetry exists.",
}
SPLITS: Final = ("train", "validation", "test")
_KINDS_BY_CATEGORY: Final[dict[FaultCategory, tuple[FaultKind, ...]]] = {
    FaultCategory.COOLING: (FaultKind.OVERHEATING, FaultKind.COOLING_DEGRADATION),
    FaultCategory.LUBRICATION: (FaultKind.LOW_OIL_PRESSURE,),
    FaultCategory.FUEL: (FaultKind.FUEL_DELIVERY,),
    FaultCategory.ELECTRICAL: (FaultKind.CHARGING_FAILURE,),
    FaultCategory.SENSOR: (FaultKind.COOLANT_SENSOR_FAILURE,),
}
_OIL_SENSORS: Final = frozenset({"oil_temp_c", "oil_pressure_kpa"})
_ORIGIN: Final = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    version: str = "sdg-ds-1.1.0"
    master_seed: int = 20261124
    healthy_sessions: int = 120
    sessions_per_fault: int = 30
    multiple_fault_sessions: int = 30
    degraded_data_sessions: int = 24
    min_duration_s: int = 300
    max_duration_s: int = 900
    step_s: float = 1.0
    window_s: int = 60
    stride_s: int = 5
    label_threshold: float = 0.3
    label_lookback_s: float = 20.0
    split_ratios: tuple[float, float, float] = (0.7, 0.15, 0.15)

    def __post_init__(self) -> None:
        if abs(sum(self.split_ratios) - 1.0) > 1e-9:
            raise ValueError("split_ratios must sum to 1")
        if self.min_duration_s <= self.window_s or self.max_duration_s < self.min_duration_s:
            raise ValueError("session durations must exceed the window length")

    @classmethod
    def small(cls, **overrides: object) -> DatasetConfig:
        """A fast configuration for automated tests."""
        values: dict[str, object] = {
            "version": "sdg-ds-test",
            "healthy_sessions": 6,
            "sessions_per_fault": 4,
            "multiple_fault_sessions": 4,
            "degraded_data_sessions": 4,
            "min_duration_s": 200,
            "max_duration_s": 260,
            "stride_s": 10,
        }
        values.update(overrides)
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SessionPlan:
    session_id: int
    group: str
    seed: int
    duration_s: int
    definition: ScenarioDefinition
    noise_scale: float
    ambient_c: float
    initial_coolant_c: float

    def simulation_config(self) -> SimulationConfig:
        return SimulationConfig(
            scenario=ScenarioId.GENERATED,
            seed=self.seed,
            noise_scale=self.noise_scale,
            ambient_c=self.ambient_c,
            custom_definition=self.definition,
            initial_coolant_c=self.initial_coolant_c,
        )

    def describe(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "group": self.group,
            "seed": self.seed,
            "duration_s": self.duration_s,
            "pattern": self.definition.pattern.value,
            "faults": [
                {
                    "kind": f.kind.value,
                    "onset_s": round(f.onset_s, 1),
                    "ramp_s": round(f.ramp_s, 1),
                    "max_severity": round(f.max_severity, 2),
                    "intermittent_period_s": f.intermittent_period_s,
                }
                for f in self.definition.faults
            ],
            "noise_scale": round(self.noise_scale, 2),
            "ambient_c": round(self.ambient_c, 1),
            "initial_coolant_c": round(self.initial_coolant_c, 1),
            "dropout_probability": round(self.definition.dropout_probability, 3),
            "unsupported_sensors": sorted(self.definition.unsupported_sensors),
            "connection_loss": self.definition.connection_loss is not None,
        }


@dataclass
class Dataset:
    features: np.ndarray
    labels: np.ndarray
    rule_labels: np.ndarray
    session_ids: np.ndarray
    split: np.ndarray
    elapsed_s: np.ndarray
    completeness: np.ndarray
    noise_scale: np.ndarray
    sessions: list[dict[str, object]]
    metadata: dict[str, object] = field(default_factory=dict)
    feature_names: tuple[str, ...] = FEATURE_NAMES

    def subset(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        mask = self.split == name
        return self.features[mask], self.labels[mask]

    def mask(self, name: str) -> np.ndarray:
        return np.asarray(self.split == name)


# -- planning -----------------------------------------------------------------------------------


def _random_fault(rng: random.Random, category: FaultCategory, duration: int) -> FaultSpec:
    latest_onset = max(40.0, duration * 0.45)
    return FaultSpec(
        kind=rng.choice(_KINDS_BY_CATEGORY[category]),
        onset_s=rng.uniform(30.0, latest_onset),
        ramp_s=rng.uniform(30.0, 180.0),
        max_severity=rng.uniform(0.4, 1.0),
        intermittent_period_s=rng.uniform(15.0, 40.0) if rng.random() < 0.25 else None,
    )


def plan_sessions(config: DatasetConfig) -> list[SessionPlan]:
    rng = random.Random(config.master_seed)
    patterns = list(DrivingPattern)
    groups: list[tuple[str, tuple[FaultCategory, ...]]] = []
    groups += [("healthy", ())] * config.healthy_sessions
    for category in LABELS:
        groups += [(f"fault:{category.value}", (category,))] * config.sessions_per_fault
    groups += [("multiple", ())] * config.multiple_fault_sessions
    groups += [("degraded_data", ())] * config.degraded_data_sessions

    plans: list[SessionPlan] = []
    healthy_index = 0
    for session_id, (group, categories) in enumerate(groups):
        duration = rng.randint(config.min_duration_s, config.max_duration_s)
        if group == "multiple":
            categories = tuple(rng.sample(LABELS, 2))
        unsupported: frozenset[str] = frozenset()
        connection = None
        dropout = rng.uniform(0.0, 0.03)
        if group == "degraded_data":
            choice = rng.randrange(3)
            if choice == 0:
                dropout = rng.uniform(0.05, 0.15)
            elif choice == 1:
                connection = ConnectionLossSpec(0.02, 2.0, 6.0)
            else:
                unsupported = _OIL_SENSORS
        faults = tuple(_random_fault(rng, c, duration) for c in categories)
        if group == "healthy":
            # Healthy sessions cycle through every driving pattern so that normal behaviour in
            # each operating condition (including long idling) is well represented.
            pattern = patterns[healthy_index % len(patterns)]
            healthy_index += 1
        else:
            pattern = rng.choice(patterns)
        ambient = rng.uniform(15.0, 40.0)
        # Engine temperature at the start ranges from a cold start to fully warmed up.
        initial_coolant = rng.uniform(ambient + 5.0, 92.0)
        definition = ScenarioDefinition(
            id=ScenarioId.GENERATED,
            title=f"Generated session {session_id}",
            description=group,
            pattern=pattern,
            faults=faults,
            unsupported_sensors=unsupported,
            dropout_probability=dropout,
            connection_loss=connection,
        )
        plans.append(
            SessionPlan(
                session_id=session_id,
                group=group,
                seed=rng.randrange(2**31),
                duration_s=duration,
                definition=definition,
                noise_scale=rng.uniform(0.5, 2.0),
                ambient_c=ambient,
                initial_coolant_c=initial_coolant,
            )
        )
    return plans


def assign_splits(plans: list[SessionPlan], config: DatasetConfig) -> dict[int, str]:
    """Stratify by group so every split contains every session type; whole sessions only."""
    rng = random.Random(config.master_seed + 1)
    by_group: dict[str, list[int]] = {}
    for plan in plans:
        by_group.setdefault(plan.group, []).append(plan.session_id)
    assignment: dict[int, str] = {}
    for ids in by_group.values():
        shuffled = sorted(ids)
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_test = max(1, round(n * config.split_ratios[2]))
        n_val = max(1, round(n * config.split_ratios[1]))
        for index, session_id in enumerate(shuffled):
            assignment[session_id] = (
                "test" if index < n_test else "validation" if index < n_test + n_val else "train"
            )
    return assignment


# -- generation ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowRow:
    elapsed_s: float
    features: np.ndarray
    labels: np.ndarray
    rule_labels: np.ndarray
    completeness: float


def _label_vector(
    history: list[tuple[float, dict[FaultKind, float]]], now: float, config: DatasetConfig
) -> tuple[np.ndarray, bool]:
    """Max severity per category over the look-back period; flags ambiguous windows."""
    peak = dict.fromkeys(LABELS, 0.0)
    for elapsed, faults in reversed(history):
        if elapsed < now - config.label_lookback_s:
            break
        for kind, severity in faults.items():
            category = FAULT_CATEGORY[kind]
            peak[category] = max(peak[category], severity)
    labels = np.array([peak[c] >= config.label_threshold for c in LABELS], dtype=np.int8)
    ambiguous = any(0.0 < peak[c] < config.label_threshold for c in LABELS)
    return labels, ambiguous


def generate_session(plan: SessionPlan, config: DatasetConfig) -> tuple[list[WindowRow], int]:
    """Simulate one session; return its labelled windows and the number of ambiguous windows."""
    simulator = VehicleSimulator(plan.simulation_config())
    rules = RuleEngine()
    samples: list[tuple[float, TelemetrySample]] = []
    fault_history: list[tuple[float, dict[FaultKind, float]]] = []
    rows: list[WindowRow] = []
    ambiguous = 0
    next_window = float(config.window_s)
    for step in simulator.iter_steps(plan.duration_s, config.step_s):
        now = step.elapsed_s
        fault_history.append((now, dict(step.labels.faults)))
        if step.readings is not None:
            timestamp = _ORIGIN + timedelta(seconds=now)
            samples.append((now, build_sample(timestamp, step.readings).sample))
        if now + 1e-9 < next_window:
            continue
        next_window += config.stride_s
        window = TelemetryWindow.from_samples(
            (s for s in samples if s[0] > now - config.window_s), window_s=config.window_s
        )
        window = TelemetryWindow(
            now, window.times, window.values, window.sample_count, window.window_s
        )
        findings = rules.evaluate(window)
        quality = window.quality()
        if not quality.sufficient:
            continue
        labels, is_ambiguous = _label_vector(fault_history, now, config)
        if is_ambiguous:
            ambiguous += 1
            continue
        rule_labels = np.array(
            [
                any(
                    f.category is c and f.severity in (Severity.WARNING, Severity.CRITICAL)
                    for f in findings
                )
                for c in LABELS
            ],
            dtype=np.int8,
        )
        rows.append(
            WindowRow(
                now, extract_features(window), labels, rule_labels, quality.overall_completeness
            )
        )
    return rows, ambiguous


def build_dataset(
    config: DatasetConfig, progress: Callable[[int, int], None] | None = None
) -> Dataset:
    plans = plan_sessions(config)
    splits = assign_splits(plans, config)
    feature_rows: list[np.ndarray] = []
    label_rows: list[np.ndarray] = []
    rule_rows: list[np.ndarray] = []
    columns: dict[str, list[object]] = {
        k: [] for k in ("session", "split", "elapsed", "completeness", "noise")
    }
    sessions: list[dict[str, object]] = []
    ambiguous_total = 0
    for index, plan in enumerate(plans):
        rows, ambiguous = generate_session(plan, config)
        ambiguous_total += ambiguous
        sessions.append(
            {
                **plan.describe(),
                "split": splits[plan.session_id],
                "windows": len(rows),
                "ambiguous_windows": ambiguous,
            }
        )
        for row in rows:
            feature_rows.append(row.features)
            label_rows.append(row.labels)
            rule_rows.append(row.rule_labels)
            columns["session"].append(plan.session_id)
            columns["split"].append(splits[plan.session_id])
            columns["elapsed"].append(row.elapsed_s)
            columns["completeness"].append(row.completeness)
            columns["noise"].append(plan.noise_scale)
        if progress is not None:
            progress(index + 1, len(plans))
    dataset = Dataset(
        features=np.vstack(feature_rows).astype(np.float64),
        labels=np.vstack(label_rows).astype(np.int8),
        rule_labels=np.vstack(rule_rows).astype(np.int8),
        session_ids=np.asarray(columns["session"], dtype=np.int32),
        split=np.asarray(columns["split"]),
        elapsed_s=np.asarray(columns["elapsed"], dtype=np.float64),
        completeness=np.asarray(columns["completeness"], dtype=np.float64),
        noise_scale=np.asarray(columns["noise"], dtype=np.float64),
        sessions=sessions,
    )
    dataset.metadata = {
        "dataset_version": config.version,
        "synthetic": True,
        "source": "SmartDrive Guardian AI vehicle simulator (no real-vehicle data)",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(config).items()},
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_count": len(FEATURE_NAMES),
        "labels": [c.value for c in LABELS],
        "unsupported_categories": {k.value: v for k, v in UNSUPPORTED_CATEGORIES.items()},
        "ambiguous_windows_excluded": ambiguous_total,
        "fingerprint": dataset_fingerprint(dataset),
        "summary": summarise(dataset),
    }
    return dataset


def dataset_fingerprint(dataset: Dataset) -> str:
    """SHA-256 over the content arrays: identical configs must give identical fingerprints."""
    digest = hashlib.sha256()
    for array in (dataset.features, dataset.labels, dataset.session_ids, dataset.split):
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


# -- analysis and validation --------------------------------------------------------------------


def summarise(dataset: Dataset) -> dict[str, object]:
    summary: dict[str, object] = {"rows": len(dataset.labels)}
    for name in SPLITS:
        mask = dataset.mask(name)
        labels = dataset.labels[mask]
        summary[name] = {
            "rows": int(mask.sum()),
            "sessions": int(np.unique(dataset.session_ids[mask]).size),
            "normal_rows": int((labels.sum(axis=1) == 0).sum()),
            "multi_label_rows": int((labels.sum(axis=1) > 1).sum()),
            "positives": {c.value: int(labels[:, i].sum()) for i, c in enumerate(LABELS)},
        }
    missing = np.isnan(dataset.features).mean(axis=0)
    summary["missing_value_fraction"] = {
        "overall": round(float(np.isnan(dataset.features).mean()), 4),
        "most_missing_features": {
            dataset.feature_names[i]: round(float(missing[i]), 4)
            for i in np.argsort(missing)[::-1][:8]
        },
    }
    return summary


@dataclass(frozen=True, slots=True)
class ValidationReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


FORBIDDEN_FEATURE_TERMS: Final = ("scenario", "label", "fault", "severity", "session", "split")


def validate_dataset(dataset: Dataset) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    n = len(dataset.labels)
    if dataset.features.shape != (n, len(FEATURE_NAMES)):
        errors.append(f"Feature matrix shape {dataset.features.shape} does not match schema.")
    if tuple(dataset.feature_names) != FEATURE_NAMES:
        errors.append("Feature names differ from the current feature schema.")
    leaked = [f for f in dataset.feature_names if any(t in f for t in FORBIDDEN_FEATURE_TERMS)]
    if leaked:
        errors.append(f"Features that could leak labels: {leaked}")
    if np.isinf(dataset.features).any():
        errors.append("Feature matrix contains infinite values.")
    if not np.isin(dataset.labels, (0, 1)).all():
        errors.append("Labels must be binary.")
    split_sessions = {
        name: set(np.unique(dataset.session_ids[dataset.mask(name)]).tolist()) for name in SPLITS
    }
    for i, first in enumerate(SPLITS):
        for second in SPLITS[i + 1 :]:
            overlap = split_sessions[first] & split_sessions[second]
            if overlap:
                errors.append(
                    f"Sessions {sorted(overlap)[:5]} appear in both {first} and {second}."
                )
    for name in SPLITS:
        labels = dataset.labels[dataset.mask(name)]
        if labels.size == 0:
            errors.append(f"The {name} split is empty.")
            continue
        for index, category in enumerate(LABELS):
            if labels[:, index].sum() == 0:
                errors.append(f"No positive {category.value} rows in the {name} split.")
        if (labels.sum(axis=1) == 0).sum() == 0:
            errors.append(f"No normal rows in the {name} split.")
    all_nan = np.isnan(dataset.features).all(axis=0)
    if all_nan.any():
        warnings.append(f"{int(all_nan.sum())} feature(s) are always missing.")
    return ValidationReport(tuple(errors), tuple(warnings))


# -- storage ------------------------------------------------------------------------------------


def save_dataset(dataset: Dataset, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        directory / "dataset.npz",
        features=dataset.features,
        labels=dataset.labels,
        rule_labels=dataset.rule_labels,
        session_ids=dataset.session_ids,
        split=dataset.split,
        elapsed_s=dataset.elapsed_s,
        completeness=dataset.completeness,
        noise_scale=dataset.noise_scale,
        feature_names=np.asarray(dataset.feature_names),
    )
    (directory / "metadata.json").write_text(json.dumps(dataset.metadata, indent=2), "utf-8")
    (directory / "sessions.json").write_text(json.dumps(dataset.sessions, indent=1), "utf-8")
    return directory


def load_dataset(directory: Path) -> Dataset:
    with np.load(directory / "dataset.npz", allow_pickle=False) as data:
        dataset = Dataset(
            features=data["features"],
            labels=data["labels"],
            rule_labels=data["rule_labels"],
            session_ids=data["session_ids"],
            split=data["split"],
            elapsed_s=data["elapsed_s"],
            completeness=data["completeness"],
            noise_scale=data["noise_scale"],
            sessions=json.loads((directory / "sessions.json").read_text("utf-8")),
            feature_names=tuple(str(n) for n in data["feature_names"]),
        )
    dataset.metadata = json.loads((directory / "metadata.json").read_text("utf-8"))
    return dataset


def iter_split_sessions(dataset: Dataset, name: str) -> Iterator[np.ndarray]:
    """Row indices per session within a split, in time order (for streaming evaluation)."""
    for session_id in np.unique(dataset.session_ids[dataset.mask(name)]):
        rows = np.flatnonzero(dataset.session_ids == session_id)
        yield rows[np.argsort(dataset.elapsed_s[rows])]
