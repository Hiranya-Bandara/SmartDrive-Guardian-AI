# Architecture

## Layers

| Layer | Package | Responsibility | May depend on |
|---|---|---|---|
| Presentation | `ui/` | Widgets, pages, dialogs, themes, controllers and Qt workers | services, models, config, obd (connection controller only) |
| Services | `services/` | Data sources (simulator, replay), vehicles, telemetry sessions, trips, maintenance, notifications and voice queue, trouble-code history and reference, reports, thresholds, backup, hybrid diagnostic engine | core, ai, obd, reporting, repositories, models |
| Hardware | `obd/` | Read-only ELM327 client, command allowlist, transports (serial, mock), PID decoding, DTC parsing, capabilities, connection session | models, config, utils |
| Reporting | `reporting/` | Format-neutral report documents, PDF rendering (ReportLab), safe CSV writing | models, core, config |
| Core | `core/` | Sensor metadata, units, validation pipeline, bounded buffers, telemetry windows, rule engine, health score, recommendations | models, config |
| AI | `ai/` | Dataset generation and validation, features, training, classifier, anomaly detector, explanations, evaluation, trusted model registry | models, core |
| Persistence | `database/` | Engine, schema, migrations, repositories | models, config, utils |
| Domain models | `models/` | Validated Pydantic types exchanged between layers | config, utils |
| Infrastructure | `config/`, `utils/` | Paths, settings, constants, logging, validators, errors | — |

Two rules keep the layers apart:

- Repositories return **domain models**, never ORM objects, so no layer above `database/` holds a
  SQLAlchemy session or a lazily loaded record.
- `ui/` must never import `database/` or `ai/training`. Only the vehicle connection controller
  and its worker touch `obd/`; every byte to an adapter goes through `obd.elm327` and the
  allowlist in `obd.commands`.

## Startup sequence (`smartdrive.app.bootstrap`)

1. Resolve the directories: the explicit `--home`, then `SMARTDRIVE_HOME`, then the platformdirs
   defaults. Create them.
2. Load the preferences. A missing file gets defaults that are written to disk; a corrupt file is
   quarantined and replaced with defaults.
3. Configure logging from the preferences (level, redaction).
4. Open SQLite (foreign keys ON, WAL journal, `synchronous=NORMAL`, busy timeout). If the schema
   is older than the application, copy the database to a pre-upgrade backup, then run Alembic to
   `head` with foreign keys off (see [database.md](database.md#upgrading-an-existing-database)).
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

## AI diagnostics (Phase 3)

```text
GUI thread                                       Inference thread
──────────                                       ────────────────
DiagnosticsController ── every N s, if idle ──► InferenceWorker
  snapshot of the bounded buffer (60 s)            TelemetryWindow → features
  generation counter                               RuleEngine (stateful) ┐
  ▲                                                RandomForest          ├► DiagnosticEngine
  │                                                IsolationForest       ┘   (hybrid policy)
  │                                                explanations, health score, recommendations
  └──────────── finished(result) ◄───────────────  DiagnosticService → SQLite (history, alerts)
Pages: AI Diagnostics, Dashboard summary, alerts toast
```

- **One engine, one thread.** The rule engine and anomaly persistence are stateful, so the
  `DiagnosticEngine` lives only in the inference thread. The GUI sends immutable
  `InferenceRequest` snapshots and receives immutable `DiagnosticAssessment` results.
- **No queue.** A tick is skipped (and counted) while a job is in flight, so slow inference can
  never accumulate work. Stopping monitoring or switching vehicle increments a generation counter,
  and late results from the previous run are discarded.
- **Models load once, off the GUI thread**, through the trusted registry (SHA-256 against the
  bundled manifest, scikit-learn and feature-schema compatibility) and are reused for every
  analysis.
- **Persistence** happens in the worker: assessments are throttled (every `history_interval_s`, or
  immediately when the status or set of findings changes). Alerts are deduplicated per vehicle
  and finding, and their cooldown is applied on top.
- Full methodology: [docs/ml/README.md](ml/README.md); results:
  [docs/ml/evaluation_report.md](ml/evaluation_report.md).

## Vehicle integration (Phase 4)

```text
GUI thread                                         Worker threads
──────────                                         ──────────────
VehicleConnectionController ── queued signals ──► ObdWorker (QThread, owns the serial port)
  status, report, quality, scans ◄──────────────    ObdSession → Elm327Client → allowlist → Transport
  live frame producer ──► MonitoringController       polling QTimer, bounded reconnect QTimer
MonitoringController ─► buffer ─► pages, DiagnosticsController (unchanged pipeline)
  sources: SimulationSource | adapter frames | ReplaySource (all via MonitoringWorker or push)
TripController ── jobs ──────────────────────────► TaskRunner (QThread, bounded FIFO)
ReportsPage, exports ── jobs ────────────────────►   trip summaries, replay loading, PDF/CSV,
NotificationController ── jobs ──────────────────►   maintenance checks, retention
NotificationController ── queued signals ───────► VoiceWorker (QThread, speech engine)
  in-app toasts, Alert Centre, system tray
```

- **One telemetry pipeline, three sources.** Simulation and replay are polled by the existing
  `MonitoringWorker`; live frames are pushed by the connection controller, because the OBD
  worker thread owns the serial port. Starting, stopping, seeking or switching source clears
  the buffer and resets diagnostic state, so a window never mixes sources or spans a seek.
- **Provenance.** Mock-adapter data is labelled simulated; replays never write diagnostic
  history or trips, and never contact an adapter.
- **Bounded everything.** Reconnection attempts (back-off), the job queue (16), the
  announcement queue (8, deduplicated, cooldown), buffers and chart points are all limited.
- **Shutdown order:** monitoring (ends any recording) → inference → adapter (cancels pending
  reads, closes the port) → voice → job thread (a running job finishes; queued jobs are dropped
  and trip summaries are recomputed at the next start).
- **Garbage collection on the GUI thread.** Automatic cyclic GC is disabled while the GUI runs
  and performed by a GUI-thread timer instead (decision 31).

## Professional release (Phase 5)

Diagrams of every part of the system: [architecture-diagrams.md](architecture-diagrams.md).

* **Packaging.** PyInstaller one-folder build from `packaging/smartdrive.spec`; entry point
  `smartdrive.launcher` (windowed, `freeze_support`, null or parent-console streams, GUI by
  default). Read-only resources are resolved by `smartdrive.resources` through
  `importlib.resources`; writable data only in per-user folders. Details:
  [packaging.md](packaging.md).
* **Installer.** Inno Setup 6, per-user without elevation, user data kept on upgrade and
  uninstall.
* **Self-test.** `smartdrive self-test` runs 13 checks in a temporary data folder with simulated
  data; the Windows smoke test runs it against the frozen executable.
* **Release pipeline.** `ci.yml` (quality gate), `windows-build.yml` (build and verify),
  `release.yml` (tag → draft pre-release behind an approval environment).
* **Defence in depth for vehicle safety.** The allowlist is checked in `Elm327Client.send` and
  again on the raw bytes in every transport (`ensure_allowed_frame`).

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
| 19 | Hybrid policy: rules are never overridden, model findings are at most WARNING, anomaly-only findings are INFORMATION | Models trained on synthetic data cannot confirm faults; an unexplained anomaly is weak evidence (measured false alarms on healthy aggressive driving). Agreement is shown as evidence, never as proof. |
| 20 | Exact tree-path decomposition instead of SHAP | SHAP's tree explainer pulls in `numba`/`llvmlite` (>100 MB, hard to bundle with PyInstaller). The path decomposition is exact and additive for a Random Forest (verified by tests). Its limitation (not Shapley values) is documented. |
| 21 | Models ship as package data with a SHA-256 manifest; scikit-learn pinned to the training minor version | Joblib files are pickles; only artefacts listed in the bundled manifest with a matching hash are loaded. Pickles are not portable across scikit-learn minor versions, so the registry refuses mismatches instead of risking silent errors. |
| 22 | 60 s window resampled to 1-second bins | Features become independent of the refresh interval, so data recorded at 1 Hz (training) and polled at 100 ms (runtime) are comparable. |
| 23 | Dataset 1.1.0 with healthy sessions spread evenly over every driving pattern and cold-to-warm starts | The first models raised cooling false alarms on healthy idling; the catalogue scenario check now runs on every training run. |
| 24 | Lubrication omitted ("not assessed") when the vehicle reports no oil pressure | The model must not report a confident negative for a fault it cannot observe. |
| 25 | NumPy `.npz` + JSON for datasets; no pandas | Avoids an unnecessary runtime dependency; the dataset is a numeric matrix with metadata. |

| 26 | In-house read-only ELM327 client on PySerial instead of python-OBD | python-OBD is GPL-2.0-only, which would constrain the MIT-licensed application and its Phase 5 installer, and its API lets callers build arbitrary commands. A small client lets every byte pass one closed allowlist. Trade-off: less field-tested protocol handling; covered by byte-level mock tests, real hardware still to be verified. |
| 27 | Mode 09 (VIN) is not on the allowlist | The VIN is not needed for diagnostics; not reading it avoids storing an identifier. |
| 28 | Mock adapter emulates the ELM327 byte protocol and its data is always "simulated" | Exercises the real client, parser and allowlist without hardware, and can never be mistaken for a vehicle. |
| 29 | ML on live data off by default; models report INCOMPATIBLE when trained sensors are unavailable | Models trained on synthetic data with oil pressure cannot be applied to vehicles without it; abstaining is more honest than predicting from a different input distribution. |
| 30 | Migrations run with SQLite foreign keys off, then `foreign_key_check` | Batch table rebuilds would otherwise cascade-delete child rows (found in testing: all telemetry lost when upgrading to 0003). |
| 31 | Cyclic garbage collection only on the GUI thread | A collection triggered on a worker thread can destroy a Qt object there and deadlock with the GUI thread (observed in testing while models loaded). Same approach as PyQtGraph's `GarbageCollector`. |
| 32 | ReportLab for PDF, standard library `csv` for CSV | ReportLab is BSD-licensed, offline and pure Python; documents are built as format-neutral blocks, so content can be tested without parsing PDFs. |
| 33 | pyttsx3 for offline speech, on its own thread, behind a `SpeechBackend` protocol | Uses the operating system's synthesiser (SAPI 5 on Windows) without downloads; failure falls back to visual notifications; tests use a fake backend. |
| 34 | Report findings grouped into episodes; CSV keeps every record | Persisting findings are stored every few seconds; listing each would hide the timeline. |
| 35 | Maintenance intervals entered by the user; examples labelled as examples | No universal manufacturer intervals exist; inventing them would be misleading. |
| 36 | Notification severity separate from diagnostic severity | "Trip recorded" (success) or "report failed" (warning) are application events, not vehicle conditions; acknowledging a notification never resolves a condition. |
| 37 | PyInstaller **one-folder**, not one-file | Several hundred MB of Qt and scientific libraries would be unpacked to a temporary folder on every start; one-folder starts faster, is scanned less by antivirus and keeps Qt DLLs replaceable (LGPL). |
| 38 | Inno Setup with `PrivilegesRequired=lowest` | Standard users can install and upgrade; no system-wide changes; all-users remains available through the privileges dialog. |
| 39 | Version written once (`smartdrive.__version__`) | `pyproject.toml`, the Windows version resource, Inno Setup, About page, CLI, PDF metadata, SBOM and build information all read it; tests reject hard-coded versions in packaging files. |
| 40 | Release tools in a separate lock file constrained by the development lock | Building needs PyInstaller and SBOM tools, users do not; constraining keeps runtime versions identical. |
| 41 | SBOM and notices generated from the lock file evaluated for Windows x64 | Describes what the Windows build ships rather than the developer's environment; Windows-only packages can be read from wheels when generating elsewhere. |
| 42 | Allowlist enforced a second time at the transport boundary | The client was the only writer, but nothing stopped a future code path from writing bytes directly; the second check costs microseconds. |
| 43 | Draft pre-release created by CI, published manually | Publication is an owner decision; the automation cannot publish by itself. |
| 44 | Unsigned 2.0.0 with published SHA-256 checksums | No certificate is available; checksums plus documentation are the honest alternative, and signing steps are documented for later. |
