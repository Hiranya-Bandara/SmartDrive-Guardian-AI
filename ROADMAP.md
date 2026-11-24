# SmartDrive Guardian AI 2.0 — Roadmap

This file is the authoritative progress tracker. A task is ticked only after the corresponding
functionality has been verified (tests executed, behaviour observed). The full requirements are in
[docs/SPECIFICATION.md](docs/SPECIFICATION.md).

**Progress: 14 / 38 tasks complete** · Current phase: **Phase 2 complete (verified headless) —
awaiting owner's Windows run** · Next phase: Phase 3

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
headless with pytest-qt; screenshots in `docs/screenshots`). A Windows run by the owner is still
pending.

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

- [ ] Prepare and validate datasets.
- [ ] Train Random Forest classifier.
- [ ] Implement Isolation Forest anomaly detection.
- [ ] Implement rule-based diagnostic engine.
- [ ] Implement experimental vehicle health score.
- [ ] Implement explainable AI.
- [ ] Evaluate model predictions and false alarms.

## Phase 4 — Vehicle Integration (target: days 19–25)

- [ ] Implement read-only OBD-II connectivity.
- [ ] Implement diagnostic trouble code reader.
- [ ] Handle hardware failures and unsupported sensors.
- [ ] Implement trip recording and replay.
- [ ] Implement maintenance centre.
- [ ] Implement PDF and CSV reports.
- [ ] Implement desktop and voice notifications.

## Phase 5 — Professional Release (target: days 26–30)

- [ ] Perform integration and performance testing.
- [ ] Review security, privacy and safety.
- [ ] Configure automated release builds.
- [ ] Build Windows executable.
- [ ] Build Windows installer.
- [ ] Create application branding and icon.
- [ ] Create actual screenshots and demonstration video.
- [ ] Finalize documentation.
- [ ] Publish Version 2.0.0 after approval.

---

## Owner decisions pending

| Decision | Proposal | Status |
|---|---|---|
| Open-source licence | MIT (permissive, standard for portfolio projects) | Awaiting approval |
| Public repository creation | `Hiranya-Bandara/SmartDrive-Guardian-AI`, public | Awaiting approval |
| Inter font bundling | Use Segoe UI by default; bundle Inter (SIL OFL 1.1) in Phase 2 with its licence file | Proposed |

## Schedule note

The day targets are development goals for a portfolio-quality application. Physical vehicle
testing and real-world validation may take longer and will not be shortened to meet a date.
