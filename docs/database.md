# Database design

SQLite, accessed through SQLAlchemy 2 (typed ORM) and versioned with Alembic. Current schema
revision: **0001 (initial schema)**.

## Location

| Mode | Path |
|---|---|
| Installed (Windows) | `%LOCALAPPDATA%\SmartDriveGuardianAI\SmartDriveGuardianAI\smartdrive.db` |
| Portable / `--home X` | `X\data\smartdrive.db` |

Run `smartdrive info` to print the exact paths on your machine.

## Connection settings

`PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`.
Every write goes through `Database.session()`, which commits on success and rolls back on any
error. SQLAlchemy errors are re-raised as `DatabaseError`.

## Entities

| Table | Purpose | Key constraints |
|---|---|---|
| `vehicles` | Garage profiles | year ≥ 1886, mileage ≥ 0, engine capacity > 0 or NULL, unique VIN (nullable) |
| `driving_sessions` | One recording/simulation/replay run | FK vehicle (CASCADE), single `data_source`, end ≥ start, self-FK `replay_of_session_id` (SET NULL) |
| `telemetry_readings` | Time-series samples | FK session (CASCADE), index (session_id, timestamp), all sensors nullable, JSON `extra` |
| `diagnostic_results` | Rule/ML/anomaly findings | FK vehicle (CASCADE), FK session (SET NULL), confidence in [0, 1] or NULL |
| `diagnostic_trouble_codes` | DTCs read from the vehicle | unique (vehicle, code, status), code length 5 |
| `alerts` | Alert centre entries | dedup key index, occurrence_count ≥ 1, acknowledgement timestamp |
| `maintenance_schedules` | Recurring tasks | at least one of interval_km / interval_days, both positive |
| `maintenance_records` | Service history and planned work | FK schedule (SET NULL, so history survives deleting a schedule), cost ≥ 0 |
| `app_settings` | Database-scoped key/value state | key primary key |
| `model_metadata` | Registry of trusted ML models | unique (name, version), 64-character SHA-256 |
| `export_history` | Generated reports | FK vehicle (SET NULL) |

The naming convention for constraints is `pk_`, `fk_`, `uq_`, `ck_`, `ix_` followed by the table
and column. Stable names keep future batch migrations on SQLite predictable.

## Data retention

`retention.telemetry_retention_days` (default 365, `null` keeps everything) is applied at
startup. Finished sessions that started before the cut-off are deleted, and their telemetry goes
with them by cascade. Open sessions are never purged.

## Backup and restore

- `smartdrive db backup` writes `smartdrive-backup-<UTC timestamp>.db` to the backups folder and
  keeps the newest `retention.keep_backups` files (default 5).
- `smartdrive db restore <file>` checks that the file is a SQLite database, passes
  `PRAGMA integrity_check` and has a schema revision this version knows. It then writes a safety
  backup of the current database, copies the backup in and migrates it to the current revision.
