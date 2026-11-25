# Architecture diagrams

Diagrams of what is implemented in 2.0.0, drawn from the source code (module and class names
are real). Narrative and decisions: [architecture.md](architecture.md).

## 1. High-level system

```mermaid
flowchart TB
  subgraph Desktop["Desktop application (PySide6, GUI thread)"]
    Pages["13 pages: Dashboard, Live Monitoring, AI Diagnostics, Vehicle Connection,<br/>Diagnostic Codes, Garage, Simulation Lab, Trip History, Maintenance,<br/>Reports, Alert Centre, Settings, About"]
    Controllers["Controllers: Monitoring, Diagnostics, VehicleConnection,<br/>Trip, Notification · TaskRunner"]
  end
  subgraph Workers["Worker threads (QThread)"]
    MW[smartdrive-monitoring]
    PW[smartdrive-persistence]
    IW[smartdrive-inference]
    OW[smartdrive-obd]
    VW[smartdrive-voice]
    TW[smartdrive-tasks]
  end
  subgraph Domain["Domain and services (pure Python)"]
    Sim[Simulator · 15 scenarios]
    Engine[Hybrid diagnostic engine]
    OBD["Read-only ELM327 client<br/>allowlist ×2"]
    Services["Telemetry, Trip, Maintenance, Notification,<br/>Report, OBD history, Replay services"]
  end
  DB[("SQLite<br/>SQLAlchemy + Alembic")]
  Files["Per-user folders:<br/>settings, logs, backups"]
  Res["Bundled read-only resources:<br/>models + SHA-256 manifest, migrations, themes, branding"]
  Adapter["ELM327 adapter (optional,<br/>user-selected COM port)"]

  Pages <--> Controllers
  Controllers <-->|signals / queued calls| Workers
  MW --> Sim
  OW --> OBD --> Adapter
  IW --> Engine
  PW & TW --> Services --> DB
  Engine --> Res
  Controllers --> Files
```

## 2. Telemetry processing

```mermaid
flowchart LR
  Sim["SimulationSource<br/>(monitoring thread)"] -->|TelemetryFrame| MC
  Rep["ReplaySource<br/>(monitoring thread, never stored)"] -->|TelemetryFrame| MC
  Obd["ObdWorker → VehicleConnectionController<br/>(live or mock adapter)"] -->|frame_received| MC
  MC["MonitoringController<br/>GUI thread"] --> Buf["Bounded buffer<br/>≤ 36,000 points"]
  Buf --> UI["Gauges, charts,<br/>source banner"]
  MC -->|if recording| PW["PersistenceWorker<br/>batched inserts"] --> DB[("telemetry_readings")]
  MC -->|every N s, 60 s window| IW["InferenceWorker"]
  MC -->|recording ended| TC["TripController → TaskRunner<br/>trip summary + timeline"]
```

Missing sensors stay `None` end to end; stale data stops assessment.

## 3. Hybrid AI diagnostics

```mermaid
flowchart TB
  W["TelemetryWindow (60 s, resampled to 1 s)"] --> Q{"Data quality:<br/>stale? insufficient?"}
  Q -->|stale| S[No assessment]
  Q --> Rules["Rule engine: 7 rules<br/>thresholds, persistence, hysteresis"]
  Q --> F["96 features + completeness"]
  F --> RF["Random Forest classifier<br/>(abstains on incompatible input)"]
  F --> IF["Isolation Forest anomaly detector"]
  RF --> X["Tree-path explanations"]
  Rules & RF & IF --> M["Merge policy: rules never overridden;<br/>model findings ≤ warning; anomaly-only = information"]
  M --> H["Experimental health score<br/>(withheld when data insufficient)"]
  M --> A["DiagnosticAssessment"] --> DS["DiagnosticService:<br/>history, alerts (dedup, cooldown, escalation)"]
  DS --> N["NotificationController:<br/>toast · Alert Centre · tray · voice"]
  Live{{"Live data + live ML disabled (default)"}} -.->|models skipped| RF
```

## 4. Application modules

```mermaid
flowchart LR
  cli[cli / launcher] --> app[app: bootstrap, shutdown]
  ui --> app
  app --> config & database & utils
  ui --> services & core & ai & obd & reporting
  services --> core & ai & obd & reporting & database & models
  core --> models
  ai --> core
  obd --> models
  reporting --> models
  selftest --> app & services & ai & obd
  resources -.-> ui & ai & database & reporting
```

| Package | Responsibility |
|---|---|
| `config` | constants, per-user paths, validated settings |
| `database` | engine, ORM models, repositories, Alembic migrations, backup/restore |
| `models` | pydantic domain models (vehicle, telemetry, diagnostics, maintenance, notifications) |
| `core` | sensors and units, telemetry windows, rule engine, health score, recommendations |
| `ai` | dataset, features, classifier, anomaly detector, explanations, trusted model registry |
| `obd` | allowlist, ELM327 client, transports, discovery, PIDs, DTC parsing, mock adapter |
| `services` | simulator, scenarios, diagnostic engine/service, telemetry, trips, replay, maintenance, notifications, reports, voice |
| `reporting` | report documents, PDF (ReportLab), CSV with formula-injection protection |
| `ui` | application shell, pages, widgets, dialogs, controllers, workers, themes |
| `resources`, `launcher`, `selftest` | bundled resources, packaged entry point, installation self-test |

## 5. Database relationships

```mermaid
erDiagram
  vehicles ||--o{ driving_sessions : has
  vehicles ||--o{ maintenance_records : has
  vehicles ||--o{ maintenance_schedules : has
  vehicles ||--o{ obd_connections : has
  vehicles ||--o{ vehicle_thresholds : has
  vehicles ||--o{ alerts : raises
  vehicles ||--o{ diagnostic_assessments : has
  vehicles ||--o{ diagnostic_results : has
  vehicles ||--o{ diagnostic_trouble_codes : has
  vehicles ||--o{ dtc_scans : has
  vehicles ||--o{ notifications : has
  vehicles ||--o{ export_history : has
  driving_sessions ||--o{ telemetry_readings : records
  driving_sessions ||--o| trip_summaries : summarised_by
  driving_sessions ||--o{ trip_events : timeline
  driving_sessions ||--o{ diagnostic_assessments : assessed_in
  driving_sessions ||--o{ diagnostic_results : found_in
  driving_sessions ||--o{ alerts : during
  driving_sessions ||--o{ dtc_scans : during
  driving_sessions ||--o{ diagnostic_trouble_codes : during
  driving_sessions ||--o{ driving_sessions : replay_of
  diagnostic_assessments ||--o{ diagnostic_results : contains
  maintenance_schedules ||--o{ maintenance_records : fulfilled_by
  obd_connections ||--o{ dtc_scans : produced
  dtc_scans ||--o{ diagnostic_trouble_codes : last_seen_in
  alerts ||--o{ notifications : announced_by
```

Plus `app_settings` and `model_metadata` (no relationships). Schema revisions: 0001 (Phase 1),
0002 (Phase 3), 0003 (Phase 4). Details: [database.md](database.md).

## 6. Workers and threading

```mermaid
sequenceDiagram
  participant GUI as GUI thread (controllers, pages)
  participant MON as smartdrive-monitoring
  participant PER as smartdrive-persistence
  participant INF as smartdrive-inference
  participant OBD as smartdrive-obd
  participant VOI as smartdrive-voice
  participant TSK as smartdrive-tasks
  GUI->>MON: start(simulation | replay)
  MON-->>GUI: frame_ready (queued signal)
  GUI->>PER: batch of samples (recording)
  GUI->>INF: window every N s (latest-only, stale results discarded)
  INF-->>GUI: assessment
  GUI->>OBD: connect / poll / scan (user action only)
  OBD-->>GUI: frames, scan results, link events
  GUI->>VOI: announcement (bounded, de-duplicated queue)
  GUI->>TSK: job (trip summary, replay load, export, retention; queue ≤ 16)
  Note over GUI: Python cyclic GC runs only here (gc_guard)
  GUI->>MON: shutdown order: monitoring → inference → OBD → voice → tasks
```

## 7. Hardware communication

```mermaid
flowchart LR
  User["User selects port<br/>and clicks Connect"] --> VCC["VehicleConnectionController"] --> OW["ObdWorker (thread)"]
  OW --> Sess["ObdSession<br/>adapter + ECU state, reconnect policy"]
  Sess --> Client["Elm327Client.send()<br/>validate(request) — allowlist #1"]
  Client --> T["SerialTransport.write()<br/>ensure_allowed_frame(bytes) — allowlist #2"]
  T --> Port["pySerial COM port"] --> A["ELM327 adapter"] --> ECU["Vehicle ECUs"]
  A -->|"reply text (untrusted)"| Parse["responses / pids / dtc parsers"] --> Sess
  Disc["discovery.list_serial_ports()<br/>list only, never opens"] --> VCC
```

Allowed: 14 adapter set-up commands, mode 01 (27 requests), mode 02 frame 0 (21), modes
03/07/0A. Everything else — including 04, 08, 09 and all UDS/KWP services — is rejected before
any byte is written.

## 8. Packaging

See [packaging.md](packaging.md#packaging-architecture) for the build flow diagram.

## 9. Continuous integration and release

```mermaid
flowchart LR
  Push["push / pull request"] --> CI["ci.yml<br/>Windows + Ubuntu: pip check, Ruff,<br/>Mypy, Pytest + coverage, self-test,<br/>GUI smoke · pip-audit"]
  Dev["push to development/main,<br/>PR, or manual"] --> WB["windows-build.yml (windows-latest)<br/>build → smoke test → ZIP → installer →<br/>install/upgrade/uninstall test → SBOM,<br/>notices, checksums → verify"]
  WB --> Art["Workflow artifacts<br/>(30 days)"]
  Tag["maintainer pushes tag v2.0.0"] --> RW["release.yml<br/>tag = __version__? → windows-build →<br/>verify checksums"]
  RW --> Env{{"'release' environment<br/>(required reviewer)"}} --> Draft["Draft pre-release<br/>with artifacts"]
  Draft --> Pub["Maintainer publishes manually"]
```
