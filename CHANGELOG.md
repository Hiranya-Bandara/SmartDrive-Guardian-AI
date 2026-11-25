# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added — Phase 3: Advanced AI Engine

- **Dataset pipeline** (`ai/dataset.py`): reproducible synthetic dataset `sdg-ds-1.1.0` (324
  sessions, 33,194 windows). It covers varied driving patterns, noise, ambient and starting
  temperatures, dropouts, unsupported sensors and connection loss, with gradual,
  partial-severity, intermittent and simultaneous faults, and labels from ground truth.
  Splits are by whole session, with leakage checks, validation, a fingerprint, metadata and a
  dataset card.
- **Features** (`ai/features.py`): 96 features from a 60-second window resampled to 1-second
  bins (independent of the refresh rate), with completeness indicators. Missing values stay
  missing.
- **Random Forest** multi-label fault classifier: model selection and precision-constrained
  thresholds on validation, abstention on insufficient, stale or out-of-distribution data, and
  "not assessed" for lubrication when oil pressure is unavailable.
- **Isolation Forest** anomaly detector trained on normal driving, with three sensitivity levels
  and persistence.
- **Rule engine** (`core/rule_engine.py`): seven transparent rules with configurable
  thresholds, persistence, hysteresis, missing/stale handling and vehicle context.
- **Hybrid diagnostic engine** with a documented disagreement policy (rules are never
  overridden; model findings are at most warning; anomaly-only findings are information),
  insufficient-data and stale states, cautious recommendations and an experimental health score
  with itemised deductions.
- **Explainable AI:** exact tree-path contributions per prediction, plus global permutation
  importance.
- **Trusted model registry:** SHA-256 manifest, scikit-learn version and feature-schema checks,
  and reported unavailable, integrity-failed and incompatible states.
- **Evaluation and reporting:** `scripts/train_models.py` produces metrics.json,
  classification_report.json, confusion matrices, feature importance, calibration and
  anomaly-score figures, a model card, a dataset card and an evaluation report. The report
  includes the rule-baseline comparison, recall by driving pattern and a check of the built-in
  scenarios through the full engine.
- **Database migration 0002:** `diagnostic_assessments` (prediction and health history),
  links from findings to assessments, and diagnostic source and data source on findings and
  alerts. Existing records are preserved.
- **Diagnostic persistence and alerts:** throttled history, per-vehicle deduplication,
  cooldown and escalation.
- **GUI:**
  - Background `InferenceWorker` and `DiagnosticsController` (no overlapping jobs, stale
    results discarded).
  - New **AI Diagnostics** page (overview, findings, recommendations, model output, anomaly
    status, explanation and importance charts, health trend, filterable history).
  - An AI summary card on the dashboard, alert toasts, and AI settings in Settings.
- **Documentation:** `docs/ml/README.md`, `docs/user-guide.md`, and database upgrade and
  recovery procedures. Phase 3 adds 84 tests (327 in total), which use a tiny dataset and small forests.

### Changed — Phase 3

- Simulator: faults support a maximum severity and an intermittent on/off cycle; configs accept
  a custom scenario definition and an optional initial coolant temperature. Defaults are
  unchanged, so existing scenarios behave exactly as before.
- Dependencies: scikit-learn 1.9 and joblib (runtime); matplotlib in the new `training` extra.
- AI Diagnostics moved from "Coming later" into the main navigation (Ctrl+5); Settings is now
  Ctrl+6 and About Ctrl+7.

### Fixed — Phase 3

- The first trained models (dataset 1.0.0) reported cooling faults on healthy idling in
  44–60 % of analyses. Dataset 1.1.0 and a new built-in-scenario check in every training run
  address this (now 0 alarms in 40 healthy drives).

### Added — Phase 2: Professional Desktop Application

- PySide6 desktop application (`smartdrive gui`, `smartdrive-gui`), with a lifecycle manager,
  high-DPI rounding policy, Segoe UI / Inter typography and orderly shutdown.
- Main window with a collapsible, persisted sidebar, a top bar (active-vehicle selector,
  operating mode, connection status, last-update time), keyboard shortcuts and toast
  notifications. Future modules are shown but disabled.
- Pages: Dashboard, Live Monitoring, Vehicle Garage, Simulation Laboratory, Settings and About.
- Reusable components: cards, metric cards, circular and linear gauges, status pills, chart
  containers, navigation buttons, form fields, confirmation and vehicle dialogs, banners,
  toasts, and loading/empty/error states.
- Dark (specification palette), light and follow-system themes generated from a single QSS
  template; tests confirm WCAG AA text contrast. Original line icons.
- A time-dependent, reproducible vehicle simulator with 15 scenarios, gradual fault
  development, measurement noise, dropouts, connection loss, manual overrides and
  ground-truth labels, behind a common `TelemetrySource` interface.
- A shared telemetry validation pipeline: implausible values are rejected, never clamped or
  invented. Bounded telemetry buffers, statistics and staleness tracking.
- Background `MonitoringWorker` and `PersistenceWorker` QThreads with batched database writes,
  bounded queues, graceful cancellation and recovery of sessions left open by a crash.
- Vehicle service (including validated image import), telemetry service (sessions, history,
  distance estimate) and backup service.
- 143 new tests (243 total) using pytest-qt, plus real screenshots in `docs/screenshots`.

### Changed

- Runtime dependencies: PySide6-Essentials, PyQtGraph and NumPy. Dev dependency: pytest-qt.
- CI installs the Qt runtime libraries on Linux, runs the GUI headless and adds a desktop
  smoke test.
- The vehicle repository now copies only user-editable profile fields.

### Added — Phase 1: Foundation & Architecture

- Fresh, independent Python 3.12 project with a `src/` layout. `pyproject.toml` is the single
  source of configuration, and exact cross-platform pins live in `requirements*.txt`.
- Per-user application directories via platformdirs, with a portable override
  (`--home` / `SMARTDRIVE_HOME`).
- Validated preferences (Pydantic), saved atomically. Corrupt files are quarantined and
  defaults are used.
- Rotating JSON-lines logging with VIN and registration-number redaction.
- An exception hierarchy that separates technical detail from user-facing messages.
- SQLite schema covering vehicles, driving sessions, telemetry readings, diagnostic results,
  diagnostic trouble codes, alerts, maintenance schedules and records, app settings, model
  metadata and export history, with foreign keys, check constraints and indexes.
- Alembic migration `0001`, applied automatically at startup.
- Timezone-safe datetime column type (stored as UTC, returned as aware UTC; naive values refused).
- Verified online database backup, rotating backups, and validated restore with a safety backup.
- Vehicle, driving-session and telemetry repositories, including batch telemetry insertion,
  privacy identifier removal and the retention purge.
- `smartdrive` command-line entry point with `info`, `db check|backup|restore` and
  `settings show|reset`.
- 100 pytest tests, Ruff, strict Mypy, a GitHub Actions CI workflow (Windows and Ubuntu),
  Dependabot, issue and PR templates.
- Documentation: README, ROADMAP, master specification, architecture, database and developer guides.
