# SmartDrive Guardian AI

**Intelligent Vehicle Diagnostics & Predictive Maintenance**

SmartDrive Guardian AI is a Windows-first desktop application for vehicle telemetry monitoring,
hybrid rule-based and machine-learning diagnostics, anomaly detection and maintenance management.
It works fully offline, works without vehicle hardware through a built-in simulator, and can
optionally read live data from compatible ELM327 OBD-II adapters in a strictly read-only mode.

> **Project status: version 2.0.0 is in development. Phases 1 (Foundation) and 2 (Desktop
> Application) are implemented.** The AI diagnostic engine (Phase 3) and OBD-II, trips,
> maintenance and reports (Phase 4) are not built yet. In the app, their navigation entries are
> visible but disabled. See [ROADMAP.md](ROADMAP.md) for verified progress.

![Dashboard (dark theme) during a simulated overheating scenario](docs/screenshots/dashboard.png)

## Safety disclaimer

SmartDrive Guardian AI is an experimental diagnostic and maintenance assistant. It is not a
certified vehicle safety system, autonomous driving system or replacement for a qualified
mechanic. If no abnormality is detected, that does not prove a vehicle is safe to drive.

## Features available today

### Desktop application (Phase 2)

- **Dashboard.** Active vehicle, monitoring controls, source and connection status, last-update
  time, coolant and RPM gauges, a digital speedometer, fuel, load and voltage indicators, live
  speed and coolant trends, and recent alerts.
- **Live monitoring.** Charts for 11 telemetry parameters with sensor selection, start, stop,
  pause and resume, configurable refresh interval (100 ms – 5 s) and time range, plus a
  minimum/maximum/average table. History is held in a bounded buffer.
  - Status is shown per sensor: OK, Missing, Not supported, Rejected (implausible),
    No response, Stale or Stopped.
  - Missing readings appear as gaps and "—", never as zero.
- **Vehicle garage.**
  - Add, edit and delete vehicles; deleting asks for confirmation.
  - Search and fuel filter, active-vehicle selection and optional vehicle images.
  - Validated forms with inline errors.
  - VIN and registration number are masked on screen and can be erased.
  - Per-vehicle history of recorded sessions, with a chart for any sensor.
- **Simulation laboratory.**
  - 15 reproducible, time-dependent scenarios: normal, idle, highway, urban, heavy traffic,
    rapid acceleration, overheating, cooling, lubrication, electrical and fuel-system
    abnormalities, sensor failure, missing sensors, intermittent connection loss, and multiple
    simultaneous faults.
  - Controls for seed, simulation speed (0.5–10×), noise level, ambient temperature and
    abnormality development time.
  - A manual driver mode, plus sliders that override individual sensor values.
  - Live ground-truth labels showing which faults are active and how severe they are.
- **Settings.** Dark, light or follow-system theme, metric or imperial units, monitoring
  intervals, data retention, log privacy and log level. Includes backup, restore and reset.
  Every change is saved immediately.
- **About.** Version, safety disclaimer, environment details, feature availability and licences.
- **Background workers.**
  - Telemetry polling and database writes run on their own threads.
  - Widgets are only updated through Qt signals.
  - Stopping or quitting shuts the workers down cleanly.
- **Interface.**
  - Collapsible sidebar, keyboard shortcuts and original line icons.
  - WCAG AA text contrast in both themes (checked by tests).
  - High-DPI support, and layouts that fit 1366×768 and up.

### Foundation (Phase 1)

- **Storage location.** Data lives in per-user OS folders, with a portable `--home` mode.
- **Preferences.** Validated preferences are saved atomically.
- **Database.** SQLite with Alembic migrations, verified backups, and validated restore with a
  safety copy taken first.
- **Logging.** Rotating JSON-lines logs with VIN and registration redaction.

## Screenshots

These are real renders of the application, made with `scripts/capture_screenshots.py`.

| | |
|---|---|
| ![Live monitoring](docs/screenshots/monitoring.png) | ![Simulation laboratory](docs/screenshots/simulation.png) |
| ![Vehicle garage](docs/screenshots/garage.png) | ![Light theme, collapsed sidebar](docs/screenshots/garage-light-collapsed.png) |
| ![Settings](docs/screenshots/settings.png) | ![Dashboard, light theme](docs/screenshots/dashboard-light.png) |

## Architecture

```mermaid
flowchart TB
    subgraph GUI thread
      UI["Pages & widgets (PySide6, PyQtGraph)"] --> MC["MonitoringController"]
      UI --> SVC["Services: vehicles, telemetry, backup"]
    end
    MC -- "queued signals" --> MW["MonitoringWorker (QThread)"]
    MC -- "queued signals" --> PW["PersistenceWorker (QThread)"]
    MW --> SRC["TelemetrySource: SimulationSource (OBD-II & replay in Phase 4)"]
    SRC --> VAL["Shared validation pipeline"]
    PW --> SVC
    SVC --> REPO["Repositories"] --> DB[("SQLite via SQLAlchemy + Alembic")]
```

Pages never query the database or touch a worker thread directly. Details and the decision log
are in [docs/architecture.md](docs/architecture.md).

## Technology stack

| Area | In use | Later phases |
|---|---|---|
| Language | Python 3.12 | — |
| Desktop UI | PySide6-Essentials 6.12, PyQtGraph 0.14, QSS themes | — |
| Configuration | Pydantic 2, platformdirs | — |
| Persistence | SQLite, SQLAlchemy 2, Alembic | — |
| Quality | pytest, pytest-qt, pytest-cov, Ruff, Mypy (strict), pip-audit, GitHub Actions | — |
| ML | — | scikit-learn, pandas, SHAP, joblib (Phase 3) |
| Hardware | — | python-OBD, pySerial (Phase 4) |
| Output | — | ReportLab, pyttsx3 (Phase 4) |
| Distribution | — | PyInstaller, Inno Setup (Phase 5) |

## Installation (Windows PowerShell)

Prerequisites: [Python 3.12 (64-bit)](https://www.python.org/downloads/) with the `py` launcher, and Git.

```powershell
cd "E:\3rd Year\SmartDrive-Guardian-AI-Phase1\SmartDrive-Guardian-AI"   # your project folder
powershell -ExecutionPolicy Bypass -File .\scripts\setup-dev.ps1
.\.venv\Scripts\Activate.ps1
```

The setup script creates `.venv`, installs the pinned dependencies, installs the app in editable
mode and runs every quality gate.

## Usage

```powershell
smartdrive gui                    # launch the desktop application
smartdrive-gui                    # same, without a console window
python -m smartdrive gui          # same, without the installed entry point

smartdrive                        # CLI: version, data locations, schema revision
smartdrive db backup | db check | db restore <file>
smartdrive settings show | settings reset
smartdrive --home .\portable-data gui   # portable mode: keep everything in one folder
```

Keyboard shortcuts:

| Shortcut | Action |
|---|---|
| Ctrl+1 … Ctrl+6 | Open Dashboard, Live Monitoring, Garage, Simulation Lab, Settings, About |
| Ctrl+M | Start or stop monitoring |
| Ctrl+P | Pause or resume |
| Ctrl+B | Collapse or expand the sidebar |
| Tab | Move between controls |

## Testing

```powershell
.\scripts\check.ps1                       # ruff, format check, mypy, pytest + coverage
python -m pytest -m "not ui"              # skip the GUI tests
python scripts\capture_screenshots.py     # regenerate docs/screenshots
```

GUI tests run headless (`QT_QPA_PLATFORM=offscreen` is set automatically) and use temporary data
folders. They never touch your real data.

## Project structure

```text
src/smartdrive/
├── app.py, cli.py              bootstrap/shutdown, command line (info, gui, db, settings)
├── config/                     constants, per-user paths, validated settings
├── core/                       sensor metadata, units, validation pipeline, bounded buffers
├── models/                     Pydantic domain models (vehicle, session, telemetry, alert)
├── database/                   engine, ORM schema, repositories, migrations/
├── services/                   data-source interface, simulator & scenarios, vehicle,
│                               telemetry and backup services
├── ui/
│   ├── application.py          Qt lifecycle and service wiring
│   ├── main_window.py, navigation.py, top_bar.py, monitoring_controller.py
│   ├── pages/                  dashboard, live monitoring, garage, simulation lab, settings, about
│   ├── widgets/                cards, gauges, charts, status, states, notifications, inputs
│   ├── dialogs/                confirmation and vehicle dialogs
│   ├── workers/                monitoring and persistence workers
│   └── themes/                 palettes, stylesheet template, theme manager
└── utils/                      logging, validators, exceptions
tests/{unit,integration,ui}/    pytest and pytest-qt suites
```

## Known limitations

- There is no machine-learning diagnostics, health score or automatic alert generation yet
  (Phase 3). The Recent alerts card shows stored alerts only, so for now it is empty.
- All telemetry currently comes from the simulator. Simulated faults are illustrative and not
  calibrated to any real vehicle.
- No OBD-II hardware support or testing yet (Phase 4).
- The GUI has been tested headless on Linux. It has not been run on Windows by the developer.
  The pinned Windows wheels are standard PySide6 builds.

## Documentation

- [Master specification](docs/SPECIFICATION.md) · [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)
- [Architecture](docs/architecture.md) · [Database](docs/database.md) · [Developer guide](docs/developer-guide.md)
- [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)

## Licence

MIT has been proposed (see [LICENSE](LICENSE)) and is awaiting the repository owner's approval.

## Developer

Developed by [Hiranya-Bandara](https://github.com/Hiranya-Bandara).
