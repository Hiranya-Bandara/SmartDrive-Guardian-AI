# SmartDrive Guardian AI 2.0 — Roadmap

This file is the authoritative progress tracker. A task is ticked only after the corresponding
functionality has been verified (tests executed, behaviour observed). The full requirements are in
[docs/SPECIFICATION.md](docs/SPECIFICATION.md).

**Progress: 32 / 38 tasks complete** · Current phase: **Phase 5 — release candidate prepared
and verified in the sandbox; Windows build, installer verification and publication pending** ·
Physical OBD-II hardware: not tested

Verification sources: *sandbox* = executed in the isolated Linux build environment (GUI
headless via Qt `offscreen`); *owner* = reported by the repository owner from their Windows machine.

Legend: `[x]` verified · `[ ]` not started or not yet verified · ⏳ waiting on the owner

---

## Phase 1 — Foundation & Architecture (target: days 1–5)

- [x] Create the new GitHub repository and fresh Git history. *(owner)*
  `Hiranya-Bandara/SmartDrive-Guardian-AI` created with an independent history.
- [x] Establish development and feature branch workflow. *(owner)*
  Workflow in [CONTRIBUTING.md](CONTRIBUTING.md); Phase 2 targets `feature/desktop-ui`.
- [x] Create professional project architecture.
  `src/` layout, layered packages (`config`, `utils`, `models`, `database`), strict typing,
  documented in [docs/architecture.md](docs/architecture.md).
- [x] Implement application configuration and entry point.
  Per-user data directories via platformdirs (portable `--home` / `SMARTDRIVE_HOME` override),
  validated JSON preferences with atomic save and corrupt-file quarantine, `smartdrive` CLI.
- [x] Implement database foundation and migrations.
  SQLite + SQLAlchemy 2 schema for all 11 entities, Alembic migration `0001` applied
  automatically at startup, verified backup/restore, retention purge, vehicle/session/telemetry
  repositories with batch insert.
- [x] Implement logging and error handling.
  Rotating JSON-lines log, VIN/registration redaction, typed exception hierarchy with
  user-safe messages.
- [ ] Configure initial testing and continuous integration. ⏳
  Testing is done and verified: 100 Phase 1 tests passed in the sandbox and on the owner's
  Windows machine (94% coverage), with ruff and mypy (strict) clean. `.github/workflows/ci.yml` (Windows + Ubuntu, ruff, mypy, pytest,
  smoke test, pip-audit) is written and each of its steps passes locally. This gets ticked after
  the first green run on GitHub.

## Phase 2 — Professional Desktop Application (target: days 6–11)

All eight tasks were verified in the *sandbox* (243 tests in total, 93% coverage; GUI exercised
headless with pytest-qt; screenshots in `docs/screenshots`) and by the *owner* on Windows
(all 243 tests passed, ruff and mypy clean).

- [x] Implement PySide6 application shell. `smartdrive gui` / `smartdrive-gui`, lifecycle
  manager, high-DPI policy, clean startup and shutdown, CLI preserved.
- [x] Build dashboard and sidebar navigation. Collapsible sidebar (persisted), top bar with
  vehicle selector, mode, connection and freshness; future modules shown disabled.
- [x] Create reusable UI components. Cards, metric cards, gauges, status pills, chart
  containers, nav buttons, form fields, dialogs, toasts and banners, loading/empty/error states.
- [x] Implement dark and light themes. Specification palette, light palette, system theme,
  persistence, WCAG AA text contrast tested, keyboard shortcuts.
- [x] Build interactive gauges and live charts. Animated gauges, PyQtGraph charts with NaN gaps,
  sensor selection, time ranges, min/max/avg, stale and missing indicators.
- [x] Implement digital vehicle garage. CRUD with validation and confirmation, search and
  filter, active vehicle, images, identifier masking and removal, per-vehicle session history.
- [x] Implement advanced simulation laboratory. 15 reproducible scenarios, gradual faults,
  noise, seeds, speed, manual driver and sensor overrides, ground-truth labels.
- [x] Implement background monitoring workers. QThread polling and batch persistence workers,
  signal-only UI updates, bounded buffers and queues, cancellation, orphaned-session recovery.

## Phase 3 — Advanced AI Engine (target: days 12–18)

All seven tasks were verified in the *sandbox*. The models were trained and evaluated with
`scripts/train_models.py`; retraining reproduced bit-identical model files. The owner
confirmed Phase 3 on Windows (and applied a local Qt signal-lifecycle fix, carried into
Phase 4). **All data is synthetic; nothing here is real-world validation.**

- [x] Prepare and validate datasets. Dataset `sdg-ds-1.1.0`: 324 independent simulated
  sessions, 33,194 labelled windows. Sessions vary seed, driving pattern, length, noise,
  ambient and starting temperature, dropouts, unsupported sensors and connection loss, with
  gradual, intermittent, partial-severity and simultaneous faults. Splits are by whole session,
  there are leakage checks, and the dataset has metadata, fingerprint and dataset card.
- [x] Train Random Forest classifier. Multi-label (5 categories); model selection and
  precision-constrained thresholds on validation; trusted, versioned artefact; abstention on
  insufficient, stale or out-of-distribution data. Test macro-F1 0.861 (synthetic).
- [x] Implement Isolation Forest anomaly detection. Trained on normal windows; three
  sensitivity thresholds; persistence; test ROC AUC 0.729. Anomaly-only findings are
  information, never alerts.
- [x] Implement rule-based diagnostic engine. Seven transparent rules with configurable
  thresholds, persistence, hysteresis, missing/stale handling, simultaneous findings and
  vehicle context. Works without models.
- [x] Implement experimental vehicle health score. 0–100 with itemised deductions, an
  unavailable state, history and trend; labelled experimental everywhere.
- [x] Implement explainable AI. Exact tree-path contributions per prediction (additivity
  verified by tests), supporting and opposing evidence, and permutation importance, shown as
  charts. SHAP was not used, for documented packaging reasons.
- [x] Evaluate model predictions and false alarms. Per-category P/R/F1, FPR/FNR, confusion
  matrices, calibration, robustness, recall by driving pattern, rule-baseline comparison,
  anomaly metrics and a built-in scenario check through the full engine (0 alarms in 40 healthy
  drives; 35 of 35 fault drives detected). See `docs/ml/evaluation_report.md`.

Also delivered: the AI Diagnostics page, dashboard integration, background inference worker,
migration 0002 (diagnostic history), alert deduplication and cooldown, and model management.

## Phase 4 — Vehicle Integration (target: days 19–25)

All seven tasks were implemented and verified in the *sandbox* (automated tests, headless GUI,
generated sample reports). **Hardware status: tested only against the byte-level mock adapter;
no physical adapter or vehicle has been tested** — see
[docs/hardware-verification-checklist.md](docs/hardware-verification-checklist.md), all items
PENDING. *Owner (Windows, after Phase 4):* dependencies installed, Ruff and Ruff format passed,
one Mypy error in `voice.py` fixed locally (kept in Phase 5), application launched, a connection
attempt to COM9 ended in a handled serial timeout, nine Bluetooth serial ports were listed (none
confirmed to be an OBD-II adapter); the exact automated test output was not supplied.

- [x] Implement read-only OBD-II connectivity. In-house ELM327 client with a closed command
  allowlist (prohibited commands tested), serial/Bluetooth-Classic ports, discovery without
  auto-connect, adapter vs ECU states, supported-PID discovery, 19 parameters, Vehicle
  Connection page. *(Physical hardware: unverified.)*
- [x] Implement diagnostic trouble code reader. Stored, pending, permanent codes, MIL, freeze
  frame, scan history, sourced generic descriptions, unknown/manufacturer-specific states,
  Diagnostic Codes page, export; no clearing.
- [x] Handle hardware failures and unsupported sensors. Typed errors for every listed failure,
  per-parameter cycle status, bounded back-off reconnection, interrupted trips, stale data,
  cancellable reads and clean shutdown; ML abstains on incompatible live input.
- [x] Implement trip recording and replay. Summaries with estimated distance, timelines,
  filters, charts, export, safe deletion; replay 0.5–4× with seek, never persisted.
- [x] Implement maintenance centre. Records, user schedules (date, mileage, combined),
  reminder states, odometer freshness, per-currency costs, observations.
- [x] Implement PDF and CSV reports. Seven PDF types, eight CSV datasets, injection
  protection, privacy options, background generation, export history, samples.
- [x] Implement desktop and voice notifications. Notification centre with deduplication,
  cooldown, retention, acknowledgement separate from condition state; desktop, sound and
  offline voice (fake speech backend in tests; *not yet exercised on Windows*).

Also delivered: database revision 0003 with automatic pre-upgrade backup, dashboard
integration, settings, background job runner, GUI-thread garbage collection, and fixes for a
migration data-loss defect and a worker-thread deadlock found during development.

## Phase 5 — Professional Release (target: days 26–30)

Implemented in the *sandbox* (Linux, headless Qt). Windows artifacts cannot be built there: the
Windows build, installer and their verification are configured and scripted but **not yet
executed**. Details: [docs/release-checklist.md](docs/release-checklist.md).

- [x] Perform integration, regression and performance testing. End-to-end scenarios A–H,
  hardware-safety and release regression tests, sustained 20-minute monitoring run and
  component benchmarks ([docs/performance.md](docs/performance.md)) — *sandbox*; Windows
  re-run ⏳.
- [x] Review security, privacy and safety. Threat model, findings fixed (transport-level
  allowlist, COM release), pip-audit of all lock files, SBOM, licensing review
  ([docs/security-review.md](docs/security-review.md)).
- [ ] ⏳ Configure automated release builds. `ci.yml`, `windows-build.yml`, `release.yml`
  written and checked with actionlint; **not yet run on GitHub**.
- [ ] ⏳ Build Windows executable. PyInstaller spec and scripts complete; spec validated with a
  Linux build (frozen self-test and GUI pass); Windows build and smoke test pending.
- [ ] ⏳ Build Windows installer. Inno Setup script and automated install/upgrade/uninstall
  test written; not yet compiled or tested on Windows.
- [x] Create application branding and icon. Original logo, ICO 16–256 px, installer artwork,
  integrated in window, sidebar, About, PDF reports and README.
- [ ] Create actual screenshots and demonstration video. Screenshots recaptured from the real
  application (*sandbox*, offscreen); installer screenshot and the video are pending (storyboard
  and narration in [docs/demo/storyboard.md](docs/demo/storyboard.md)).
- [x] Finalize documentation. README, user/developer/build/installation guides, privacy,
  security, licensing, packaging, release verification, known limitations, portfolio.
- [ ] Publish Version 2.0.0 after approval. Release notes, tag and draft-release workflow
  prepared; **publication requires the owner's approval** and should be a pre-release until the
  Windows gates pass.

---

## Owner decisions pending

| Decision | Proposal | Status |
|---|---|---|
| Open-source licence | MIT (`LICENSE` present since Phase 1; kept in Phase 5) | Confirmation before publication |
| Public repository creation | `Hiranya-Bandara/SmartDrive-Guardian-AI`, public | Awaiting approval |
| Inter font bundling | Not bundled; the UI uses Segoe UI on Windows | Closed (no font is distributed) |
| Release designation | Publish 2.0.0 as a GitHub **pre-release** until the Windows gates pass | Proposed |
| Code signing | Unsigned for 2.0.0; see `docs/code-signing.md` | Proposed |

## Schedule note

The day targets are development goals for a portfolio-quality application. Physical vehicle
testing and real-world validation may take longer and will not be shortened to meet a date.
