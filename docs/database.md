# Database design

SQLite, accessed through SQLAlchemy 2 (typed ORM) and versioned with Alembic. Current schema
revision: **0003 (vehicle integration)**. Revision 0001 is the initial schema and 0002 added
diagnostic history.

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
| `diagnostic_assessments` | One stored hybrid analysis (prediction history, health-score history) | FK vehicle (CASCADE), FK session (SET NULL), indexes on vehicle/time and session, data source, status, severity, health score, completeness, model run states, anomaly score, model output per category (JSON), model versions (JSON), inference time |
| `diagnostic_results` | Individual findings (rule, model, anomaly), including anomaly events | FK vehicle (CASCADE), FK session (SET NULL), FK assessment (SET NULL), `finding_key`, data source, confidence in [0, 1] or NULL, explanation and evidence (JSON), model version |
| `diagnostic_trouble_codes` | DTCs read from the vehicle | unique (vehicle, code, status), code length 5 |
| `alerts` | Diagnostic alerts (deduplicated) | dedup key index, occurrence_count ≥ 1, acknowledgement timestamp, diagnostic `source` |
| `maintenance_schedules` | Recurring tasks | at least one of interval_km / interval_days, both positive |
| `maintenance_records` | Service history and planned work | FK schedule (SET NULL, so history survives deleting a schedule), cost ≥ 0 |
| `app_settings` | Database-scoped key/value state | key primary key |
| `model_metadata` | Registry of trusted ML models | unique (name, version), 64-character SHA-256 |
| `export_history` | Generated reports and exports: report ID, status (success/failed), message, file path and size | FK vehicle (SET NULL) |
| `obd_connections` *(0003)* | One adapter connection: port, method, mock flag, adapter version, ECU connected, protocol, supported PIDs, missing sensors, samples, end reason | FK vehicle (SET NULL), index (vehicle, started) |
| `dtc_scans` *(0003)* | One trouble-code scan: data source, mock flag, protocol, MIL, counts per status (permanent NULL when unsupported), codes, freeze frame, notes | FK vehicle (CASCADE), FK connection and session (SET NULL), index (vehicle, scanned) |
| `trip_summaries` *(0003)* | Statistics computed when a trip ends: completeness, speed/rpm/coolant figures, estimated distance and its coverage, event counts, model versions | PK = FK session (CASCADE) |
| `trip_events` *(0003)* | Trip timeline: findings, anomalies, codes, connection lost/restored, interruptions | FK session (CASCADE), index (session, time) |
| `notifications` *(0003)* | Application notifications: severity (information/success/warning/critical, separate from diagnostic severity), category, dedup key, occurrences, read and acknowledged times | FK vehicle (CASCADE), FK alert (SET NULL), indexes on time and dedup key |
| `vehicle_thresholds` *(0003)* | User-entered rule thresholds for one vehicle, with their source | PK = FK vehicle (CASCADE) |

Revision 0003 also adds: `driving_sessions.name` and `status` (recording / completed /
interrupted); `alerts.read_at`, `resolved_at` and `evidence`; `diagnostic_trouble_codes`
`last_scan_id`, `detection_count`, `is_active` and `description_source`;
`maintenance_records.category`, `next_due_date`, `next_due_km`;
`maintenance_schedules.category`, `reminder_days_before`, `reminder_km_before`,
`interval_source` (user / example), `notes`; `vehicles.mileage_updated_at`.

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

## Upgrading an existing database

Migrations run automatically when the application or the CLI starts.

- **Automatic safety backup.** If the database is at an older revision, it is first copied to
  `backups/smartdrive-pre-upgrade-<revision>-<UTC timestamp>.db` (these copies are not removed
  by backup rotation).
- **0001 → 0002** adds the `diagnostic_assessments` table and nullable columns.
- **0002 → 0003** adds the Phase 4 tables and columns listed above. Existing trips get status
  *completed* (or *recording* if they never ended); existing maintenance rows get a category.
  No rows are deleted or changed otherwise (covered by
  `tests/integration/test_vehicle_integration_db.py`, including telemetry readings and trouble
  codes).
- **Foreign keys during migrations.** SQLite rebuilds a table to change it (copy, drop,
  rename). With foreign keys on, dropping the original would delete every child row through
  `ON DELETE CASCADE` — for example all telemetry when `driving_sessions` is rebuilt. Migrations
  therefore run with `PRAGMA foreign_keys=OFF`, must pass `PRAGMA foreign_key_check` before
  they are committed, and foreign keys are switched back on afterwards. (This defect was found
  and fixed during Phase 4 development, before any release; migration 0002, which Phase 3
  users have already run, rebuilds only tables that nothing references and was not affected.)

Recommended procedure before upgrading an important database (Windows PowerShell):

```powershell
smartdrive db backup                 # verified copy in the backups folder
smartdrive info                      # shows "Schema revision: 0003 (latest 0003)" after upgrade
smartdrive db check                  # integrity check
```

### Recovery

- **Upgrade failed.** The application reports "The database could not be upgraded" and does not
  start. Restore the backup taken above with `smartdrive db restore <file>`. It is validated,
  a safety copy of the current file is taken first, and it is then migrated forward.
- **Going back to a Phase 3 build** requires a database at revision 0002. Restore the automatic
  `smartdrive-pre-upgrade-0002-…` backup (safe route). A developer can also downgrade (see the
  developer guide); that drops the Phase 4 tables and columns (trip summaries and events, scans,
  notifications, connection history, vehicle thresholds) but keeps vehicles, trips, telemetry
  and codes.
- **Going back to a Phase 2 build** requires revision 0001, similarly.
- **Backups from a newer version** are refused rather than opened with an older schema.

