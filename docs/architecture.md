# Architecture

## Layers

| Layer | Package | Responsibility | May depend on |
|---|---|---|---|
| Presentation | `ui/` | Widgets, pages, themes, Qt workers | services, models, config |
| Services | `services/` | Data sources and simulator, vehicles, telemetry sessions, backup | core, ai, repositories, models |
| Core | `core/` | Sensor metadata, units, validation pipeline, bounded buffers (diagnostics in Phase 3) | models, config |
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

## Desktop application (Phase 2)

### Threading model

```text
GUI thread                                   Worker threads
──────────                                   ──────────────
Pages ─► MonitoringController ── signal ──► MonitoringWorker (QThread)
  ▲            │  ▲                              │  QTimer tick → TelemetrySource.read()
  │            │  └──────── frame_ready ─────────┘
  │            └──── enqueue (signal) ─────────► PersistenceWorker (QThread)
  │                                                 batches → TelemetryService.append()
  └── refresh timers (200–250 ms) read the bounded TelemetryBuffer
```

- Widgets are created and updated only on the GUI thread. Workers communicate exclusively
  through queued signals.
- Configuration changes (overrides, speed, scenario, reset) are sent to the worker as callables
  and executed inside the worker thread, so the telemetry source needs no locks.
- Stopping uses a blocking queued `stop()` on each worker, followed by `quit()` and `wait()`.
  The persistence worker flushes its queue before the session is closed. Quitting the
  application runs the same path.
- Pages redraw on a timer only when new data has arrived and the page is visible, which keeps
  chart updates cheap at high refresh rates.
- Memory is bounded: the telemetry buffer holds at most `chart_history_seconds × 10` points per
  sensor (maximum 36,000), and the persistence queue holds at most 10,000 samples, dropping the
  oldest and counting the drops.
- Sessions left open by a crash are closed at the next startup, at their last recorded reading.

### Data integrity in the UI

Every telemetry source goes through `core.telemetry_processing.build_sample`. Values outside the
plausibility bounds of `TelemetrySample` become *missing* and are reported as *rejected*. Missing
data is drawn as a gap and shown as "—". When monitoring stops, gauges blank out, and the live
table keeps the last trace but marks it "Stopped". The simulator is labelled everywhere it
appears (banners, mode pill, session source).

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
| 12 | One QSS template plus typed palettes instead of separate `dark.qss`/`light.qss` | A single source of styling; palettes are unit-tested for WCAG contrast. |
| 13 | PySide6-Essentials instead of the PySide6 meta-package | Provides every module used (QtWidgets, QtSvg) without WebEngine and other add-ons, so installs and the Phase 5 bundle are much smaller. |
| 14 | Separate `MonitoringController` (GUI thread) and workers (QThreads) | Pages depend on one signal-based façade, workers stay UI-free, and the controller can be tested without pages. |
| 15 | Simulator uses seeded `random.Random` streams per concern (profile, noise, events, faults) | Runs are reproducible, and adding noise does not alter the driving profile, which suits Phase 3 dataset generation. |
| 16 | Fault effects are applied inside the vehicle dynamics, not painted onto outputs | Signatures emerge coherently (for example, coolant loss raises oil temperature too), giving more realistic training data. Only sensor faults alter readings directly. |
| 17 | Unimplemented modules are shown disabled with their phase | Honest navigation without placeholder screens (§7, §3). |
| 18 | PyQtGraph context menus are re-parented to their plot | PyQtGraph creates them without a parent; otherwise every closed chart leaked about 5 top-level menus. |

