# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.0.0] - 2026-11-25 (release candidate; not yet published)

First complete release of the second-generation SmartDrive Guardian AI: Phases 1–4 below plus
the release work of Phase 5. Version 2.0.0 is intended to be published as a GitHub
**pre-release** until it has been verified on Windows (see `docs/release-checklist.md`).

### Added — Phase 5: Professional Release

- **Windows packaging**: PyInstaller one-folder specification (`packaging/smartdrive.spec`)
  with the Windows version resource generated from `smartdrive.__version__`, windowed launcher
  (`smartdrive.launcher`) that opens the desktop application by default, supports
  `freeze_support()` and attaches to a parent console for CLI commands.
- **Inno Setup 6 installer** (`packaging/installer.iss`): per-user installation without
  administrator rights, optional all-users installation, Start Menu and optional desktop
  shortcuts, licence and safety notice pages, Restart Manager, clean upgrades, uninstaller that
  keeps user data and says where it is.
- **Build and release scripts** (Windows PowerShell 5.1/7): `build-windows.ps1`,
  `build-installer.ps1`, `smoke-test.ps1`, `test-installer.ps1`, `generate-checksums.ps1`,
  `verify-release.ps1`, shared `_common.ps1`; `setup-dev.ps1 -Release`.
- **Installation self-test** (`smartdrive self-test [--report file.json]`): 13 checks with
  simulated data in a temporary folder, used by the packaged smoke tests.
- **Release metadata** (`scripts/release_metadata.py`): CycloneDX 1.6 SBOM of the Windows
  runtime dependencies (schema-validated), generated `THIRD_PARTY_NOTICES.md` with licence texts,
  `BUILD_INFORMATION.json`.
- **GitHub Actions**: CI extended (pinned action SHAs, test results, self-test, audit of all
  lock files); new `windows-build.yml` (build, smoke test, installer, automated install/upgrade/
  uninstall test, SBOM, checksums, verification, artifacts) and `release.yml` (tag must match
  the version; draft pre-release behind the `release` environment).
- **Branding**: original shield-car-pulse logo (SVG masters, ICO 16–256 px, PNGs, logos for dark
  and light backgrounds, monochrome mark, social preview, installer wizard images), reproducible
  with `scripts/build_brand_assets.py`; used for the window and taskbar icon, sidebar, About
  page, PDF page headers, installer and README. New tagline: "Intelligent Diagnostics. Smarter
  Maintenance."
- **First-run welcome guide** (simulation vs live mode, AI limitations, not while driving, data
  location), reopenable from About; About page with developer, repository, licence, limitations,
  privacy and model information.
- **Tests**: end-to-end release scenarios A–H (first installation and restart, AI workflow to
  report, trips and replay, maintenance, no hardware and failed connection, notifications,
  database upgrade from 0002 with backup and restore, shutdown during all background work),
  hardware-safety tests (prohibited requests and frame injection at every layer), release
  regression tests (lifecycle rule, launcher, resources, version single source, SBOM), COM
  pairing tests for the voice backend.
- **Performance suite** (`scripts/benchmark.py`) and measured report (`docs/performance.md`).
- **Documentation**: `PRIVACY.md`, rewritten `SECURITY.md`, `THIRD_PARTY_NOTICES.md`,
  `RELEASE_NOTES.md`, security review and threat model, licensing review, installation, build,
  release verification, release checklist, troubleshooting, packaging, system requirements,
  known limitations, code signing, architecture diagrams, demo storyboard, portfolio materials.

### Changed — Phase 5

- The OBD-II read-only allowlist is now enforced a second time on the raw bytes at the
  transport boundary (serial and mock), in addition to the client.
- Single source for the version: `pyproject.toml` reads `smartdrive.__version__`.
- Release tools are locked separately in `requirements-release.txt` (constrained by the
  development lock, so runtime versions are unchanged).
- Development status classifier: Beta.

### Fixed — Phase 5

- Windows: `comtypes.CoInitialize()` type-check error (owner's local fix kept, now also clean on
  Linux) and COM now released with `CoUninitialize()` when the speech engine closes or fails to
  start.
- The packaged GUI would not start: pyqtgraph imports `PySide6.QtOpenGL` dynamically (found by
  the frozen smoke test; hidden imports added).
- Build-environment packages no longer leak into the bundle through optional imports.

### Added — Phase 4: Vehicle Integration

- **Read-only OBD-II** (`obd/`): in-house ELM327 client over PySerial; a closed allowlist of 65
  exact requests (adapter set-up, mode 01 current data, mode 02 freeze frame, modes 03/07/0A
  codes) through which every byte passes; SAE J1979 decoding for 19 parameters; CAN
  multi-frame reassembly; supported-PID discovery; baud-rate probing; serial and Bluetooth
  Classic (COM port) transports; a byte-level mock adapter with five behaviours, always
  labelled simulated.
- **Connection management**: separate adapter and ECU states, ECU retry, measured link quality,
  typed errors with user messages, bounded exponential-back-off reconnection, cancellable reads,
  connection history; Vehicle Connection page with port discovery, parameters table, diagnostics
  log, setup guidance and vehicle-specific rule thresholds with their source.
- **Trouble codes**: stored, pending and permanent codes, MIL, freeze frame, scan history with
  first/most recent detection; local reference of paraphrased generic SAE J2012 descriptions with
  source; manufacturer-specific codes never interpreted; Diagnostic Codes page with filters,
  details, related findings and CSV export. No clear-codes function exists.
- **Telemetry modes**: live frames from the adapter and trip replay join the simulator in the
  one monitoring pipeline, with a source selector and per-mode labels and banners.
- **Trips**: names, recording status (completed/interrupted), summaries computed in the
  background (time-aware estimated distance with coverage), timeline events (findings,
  escalations, connection lost/restored, interruption), Trip History page with filters,
  charts, export, safe deletion and replay (0.5–4×, pause, seek; never persisted).
- **Maintenance centre**: records with costs per currency, user-defined date/mileage schedules,
  reminder states, dated odometer readings, monthly/yearly/category costs, example intervals
  labelled as examples, AI-related observations; Maintenance page and dialogs.
- **Reports**: seven PDF report types (ReportLab), eight CSV datasets, privacy options, export
  history, Reports page with background generation; sample reports from simulated data in
  `docs/samples/` (`scripts/generate_sample_reports.py`).
- **Notifications**: notification records with deduplication, cooldown, escalation and
  retention; Alert Centre (notifications and diagnostic alerts, read/acknowledged/condition
  states); optional desktop notifications (system tray), sounds and offline voice (pyttsx3) on
  a dedicated thread with a bounded, deduplicated queue; maintenance reminders.
- **Dashboard** summary of connection, trouble codes, recent trips, maintenance and unread
  notifications; grouped sidebar with new shortcuts; Phase 4 settings.
- **Database revision 0003** (six tables, new columns) with an automatic pre-upgrade backup.
- **Background job runner** (one bounded thread) for trip summaries, replay loading, exports,
  maintenance checks and retention.
- Documentation: `docs/hardware.md`, `docs/hardware-verification-checklist.md`,
  `docs/reports.md`, `docs/privacy.md`; updated architecture, database, user and developer
  guides, specification amendments and ML documentation (live-data behaviour).

### Fixed — found during Phase 4 development

- **Data loss in migrations**: SQLite table rebuilds ran with foreign keys on and would have
  cascade-deleted child rows (all telemetry readings when upgrading to 0003). Migrations now run
  with foreign keys off and must pass `PRAGMA foreign_key_check`. Not released; migration 0002
  was not affected.
- **Deadlock with worker threads**: Python's cyclic garbage collector could free a Qt object on a
  worker thread and deadlock with the GUI thread. Collection now runs only on the GUI thread.
- Remaining lambda signal connections in the dashboard and AI Diagnostics page replaced by
  bound methods (matches the owner's local Phase 3 lifecycle fix).
- Trip timelines dropped an escalation from warning to critical of the same condition.

### Changed

- Navigation: all pages are built; the "Coming later" section is gone.
- Diagnostic alerts are announced through the notification system (stored, deduplicated) instead
  of direct toasts.

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
