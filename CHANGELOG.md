# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
