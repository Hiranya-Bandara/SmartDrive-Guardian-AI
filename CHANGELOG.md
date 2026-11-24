# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
