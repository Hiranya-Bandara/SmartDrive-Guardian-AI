# SmartDrive Guardian AI 2.0 — Roadmap

This file is the authoritative progress tracker. A task is ticked only after the corresponding
functionality has been verified (tests executed, behaviour observed). The full requirements are in
[docs/SPECIFICATION.md](docs/SPECIFICATION.md).

**Progress: 4 / 38 tasks complete** · Current phase: **Phase 1 complete in code — awaiting owner
repository setup** · Next phase: Phase 2

Legend: `[x]` verified · `[ ]` not started or not yet verified · ⏳ waiting on the owner

---

## Phase 1 — Foundation & Architecture (target: days 1–5)

- [ ] Create the new GitHub repository and fresh Git history. ⏳
  Fresh, independent history is created by the commands in
  [docs/developer-guide.md](docs/developer-guide.md#first-time-repository-setup). Remote creation
  and pushing require the owner's GitHub authentication and approval; repository-name availability
  could not be checked from the build sandbox.
- [ ] Establish development and feature branch workflow. ⏳
  Workflow documented in [CONTRIBUTING.md](CONTRIBUTING.md); `main`, `development` and
  `feature/project-foundation` are created by the setup commands. Tick after the first push.
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
  Testing is done and verified: 100 pytest tests pass with 94% branch-aware coverage, and ruff
  and mypy (strict) are clean. `.github/workflows/ci.yml` (Windows + Ubuntu, ruff, mypy, pytest,
  smoke test, pip-audit) is written and each of its steps passes locally. This gets ticked after
  the first green run on GitHub.

## Phase 2 — Professional Desktop Application (target: days 6–11)

- [ ] Implement PySide6 application shell.
- [ ] Build dashboard and sidebar navigation.
- [ ] Create reusable UI components.
- [ ] Implement dark and light themes.
- [ ] Build interactive gauges and live charts.
- [ ] Implement digital vehicle garage.
- [ ] Implement advanced simulation laboratory.
- [ ] Implement background monitoring workers.

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
