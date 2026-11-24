# Architecture

## Layers

| Layer | Package | Responsibility | May depend on |
|---|---|---|---|
| Presentation | `ui/` (Phase 2) | Widgets, pages, themes, Qt workers | services, models, config |
| Services | `services/` (Phase 2+) | Monitoring, data sources, maintenance, notifications | core, ai, repositories, models |
| Core | `core/` (Phase 2–3) | Diagnostics, safety rules, health score, events | models, config |
| AI | `ai/` (Phase 3) | Preprocessing, training, inference, explanations | models |
| Persistence | `database/` | Engine, schema, migrations, repositories | models, config, utils |
| Domain models | `models/` | Validated Pydantic types exchanged between layers | config, utils |
| Infrastructure | `config/`, `utils/` | Paths, settings, constants, logging, validators, errors | — |

Two rules keep the layers apart:

- Repositories return **domain models**, never ORM objects, so no layer above `database/` holds a
  SQLAlchemy session or a lazily loaded record.
- `ui/` must never import `database/`, `ai/training` or the OBD-II adapter directly.

## Startup sequence (`smartdrive.app.bootstrap`)

1. Resolve the directories: the explicit `--home`, then `SMARTDRIVE_HOME`, then the platformdirs
   defaults. Create them.
2. Load the preferences. A missing file gets defaults that are written to disk; a corrupt file is
   quarantined and replaced with defaults.
3. Configure logging from the preferences (level, redaction).
4. Open SQLite (foreign keys ON, WAL journal, `synchronous=NORMAL`, busy timeout) and run Alembic
   to `head`.
5. Apply the telemetry retention policy.

Shutdown checkpoints the WAL into the main database file, disposes the engine and flushes and
closes the log handlers.

## Operating modes and data integrity

`DataSource` (simulation, live, replay) is stored on every driving session. Telemetry belongs to
exactly one session, so data from different sources can't end up in one session. A replay
session must reference the recording it replays, and only a replay session may. A finished
session can't receive more telemetry. Every sensor value is nullable, and "not reported" is
stored as `NULL`, never zero.

## Decision log

| # | Decision | Rationale |
|---|---|---|
| 1 | Preferences in `settings.json`, not the database | Some preferences are needed before the database opens (logging level, data location). JSON is easy to inspect and reset. The `app_settings` table is kept for database-scoped state. |
| 2 | Migrations live in `src/smartdrive/database/migrations/` rather than a top-level `migrations/` | They must ship inside the installed package and the PyInstaller bundle so that end-user databases upgrade automatically. The specification's top-level folder could not be packaged. |
| 3 | Migrations never import application code | Old migrations must keep working after the code is refactored. The custom `UtcDateTime` type is written as `sa.DateTime` in migrations, which has the same storage. |
| 4 | Enums stored as strings with CHECK constraints (`native_enum=False`) | SQLite has no enum type. Readable values and database-level validation together. |
| 5 | Wide telemetry table with nullable typed columns plus a JSON `extra` column | Fast batch inserts and range queries for the core PIDs. Extra PIDs discovered on real vehicles go in `extra` without a migration. |
| 6 | All timestamps are timezone-aware UTC; naive datetimes are rejected | Prevents silent local/UTC mixing, which would corrupt trip timelines and retention. |
| 7 | Backups use SQLite's online backup API, then an integrity check | Consistent copies while the app is running (WAL-safe). Copying the file could capture a half-written state. |
| 8 | Restore validates the header, integrity and schema revision, and takes a safety backup first | A wrong file can't destroy data, and every restore can itself be undone. |
| 9 | Dependencies added per phase | The specification forbids unnecessary dependencies. Phase 1 needs only platformdirs, Pydantic, SQLAlchemy and Alembic. |
| 10 | `requires-python = ">=3.12,<3.13"` | The specification targets Python 3.12. Pinning one minor version keeps the PyInstaller build reproducible. |
| 11 | No GUI placeholder in Phase 1; the entry point is a maintenance CLI | The specification forbids placeholder screens. The CLI commands (backup, restore, check) stay useful after the GUI arrives. |
