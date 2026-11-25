# Portfolio materials — SmartDrive Guardian AI 2.0

Ready-to-use descriptions for a portfolio, LinkedIn, a résumé and interviews. Every figure is
taken from this repository's own measurements; keep the qualifiers ("simulated", "mock
adapter", "not yet verified on Windows") when reusing them. Repository:
<https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI>. There is no public release URL yet;
add it only after 2.0.0 has actually been published.

**On authorship.** The project was built by Hiranya Bandara with AI-assisted development
(code generation and review with an AI assistant, directed, reviewed, run and tested by the
developer). Say so if asked; do not claim that every component was written unaided.

## 1. Short portfolio card (≈ 50 words)

**SmartDrive Guardian AI** — an offline Windows desktop app for educational vehicle diagnostics.
A hybrid engine combines transparent rules with Random Forest and Isolation Forest models and
explains every prediction. Read-only OBD-II, trip replay, maintenance tracking and PDF/CSV
reports. Python 3.12, PySide6, scikit-learn, SQLite; 643 automated tests.

## 2. Detailed project description

**Problem.** Car owners and learners see warning lights and raw OBD-II numbers without context,
and many hobby tools either upload data to the cloud or allow risky write commands. Learning
how diagnostic data relates to faults needs a safe, offline environment — including when no car
or adapter is available.

**Solution.** SmartDrive Guardian AI is a desktop application that monitors engine telemetry from
a built-in simulator or (experimentally) from an ELM327 adapter, analyses one-minute windows with
seven transparent rules plus two machine-learning models, explains the evidence, and keeps the
results with trips, maintenance records and reports — entirely on the user's computer.

**Technology.** Python 3.12, PySide6 (Qt 6) and PyQtGraph for the interface; SQLite with
SQLAlchemy 2 and Alembic migrations; scikit-learn Random Forest and Isolation Forest with NumPy;
pySerial with an in-house ELM327 client; ReportLab for PDFs; pyttsx3 for offline speech;
pytest/pytest-qt, Ruff, strict Mypy and pip-audit; PyInstaller, Inno Setup and GitHub Actions
for distribution.

**Key features.** 13-page desktop interface with dark/light themes; 15 simulation scenarios;
hybrid diagnostics with tree-path explanations and an experimental health score; read-only
OBD-II with trouble codes and freeze frame; trip recording and 0.5–4× replay; maintenance
schedules and per-currency costs; 7 PDF and 8 CSV report types; Alert Centre with desktop and
voice notifications.

**Engineering challenges.**
- *Keeping the UI responsive*: six worker threads (monitoring, persistence, inference, OBD,
  voice, jobs) with queued signals, bounded queues and an ordered shutdown; Python's cyclic
  garbage collector restricted to the GUI thread after a worker-thread collection deadlocked
  the app in testing.
- *Data integrity*: SQLite table rebuilds in a migration silently cascade-deleted all telemetry;
  migrations now run with foreign keys off plus `foreign_key_check`, and databases are backed up
  before every upgrade.
- *Honest AI*: models trained on synthetic data abstain on incompatible live input instead of
  guessing; missing sensors are never filled with normal values; rules are never overridden.
- *Vehicle safety*: a closed allowlist of 65 read-only requests enforced in the client and again
  on the raw serial bytes; no code path can clear codes or write to an ECU.
- *Packaging*: a frozen-build smoke test caught a crash caused by a dynamic import inside
  pyqtgraph before any user saw it.

**Software architecture.** Layered: configuration → database/repositories → domain models →
core (rules, telemetry windows) → AI and OBD packages → services → Qt controllers and workers →
pages. Pages never touch the database or threads directly.

**Machine learning.** 324 simulated sessions (33,194 one-minute windows) split by session;
96 features from 1-second resampled windows with completeness indicators; Random Forest
multi-label classifier with precision-constrained thresholds; Isolation Forest trained on
normal driving. Synthetic test split: **89.05 % subset accuracy, 86.06 % macro F1** (rule-only
baseline 0.573 macro F1). Synthetic results only — real-world accuracy has not been measured.

**Explainable AI.** Exact additive tree-path contributions for every Random Forest prediction
(chosen over SHAP to avoid a large native dependency in the packaged app), plus global
permutation importance; shown as charts in the app and in reports.

**Database design.** 18 tables across vehicles, trips/telemetry, diagnostics/alerts,
OBD connections and trouble codes, maintenance, notifications and export history; three Alembic
revisions; foreign keys enforced; validated backup and restore.

**Hardware communication.** In-house ELM327 client (python-OBD's GPL licence was incompatible
with the MIT project); serial and Bluetooth COM transports; adapter vs ECU state; reconnection
with bounded back-off; byte-level mock adapter for tests. Physical hardware is not yet verified.

**Testing strategy.** 643 automated tests (unit, integration, GUI with pytest-qt,
end-to-end scenarios, mocked hardware, migrations, security), 91 % line-and-branch
coverage, strict Mypy, Ruff; CI on Windows and Ubuntu; a self-test command that runs inside the
packaged executable.

**Security.** Threat model and self-review; offline by design; checksum-verified model loading;
parameterised SQL; CSV formula-injection protection; per-user installer without elevation;
pinned, audited dependencies, CycloneDX SBOM and SHA-pinned GitHub Actions.

**Deployment.** PyInstaller one-folder build, Inno Setup installer, portable ZIP, SHA-256
checksums, SBOM and third-party notices produced by PowerShell scripts and a GitHub Actions
workflow; tagged releases become draft pre-releases that the maintainer publishes.

**Results (measured).** 643 tests passing; 91 % coverage; 48 ms median AI
assessment per window; window visible ≈ 3.4 s after launch; memory stable at ≈ 394 MB over a
20-minute monitoring run (Linux development container measurements).

**Known limitations.** Synthetic-only training data; physical OBD-II adapters unverified;
Windows packaged build and installer not yet verified at the time of writing; unsigned binaries;
English only.

**Future improvements.** Physical adapter testing; code signing; collecting consented real
vehicle data to evaluate (and possibly retrain) the models; Wi-Fi/BLE adapters; localisation.

## 3. GitHub repository description (≤ 350 characters)

> An offline-first AI-powered vehicle diagnostics and maintenance desktop application featuring
> hybrid machine learning, read-only OBD-II integration, telemetry monitoring, trip replay and
> professional reporting.

Suggested topics: see [github-repository-setup.md](github-repository-setup.md).

## 4. LinkedIn launch caption

> I've finished **SmartDrive Guardian AI 2.0**, an offline Windows desktop app for learning
> about vehicle diagnostics. 🚗🛡️
>
> It monitors engine telemetry from a built-in simulator (or, experimentally, a read-only OBD-II
> adapter), and a hybrid engine of transparent rules plus Random Forest and Isolation Forest
> models explains why it flags something. Trips can be replayed, maintenance tracked and
> reports exported as PDF or CSV.
>
> What I learned most from: keeping a Qt app responsive with six worker threads, finding a
> migration bug that would have deleted user data, making ML models abstain instead of guessing,
> and enforcing a read-only command allowlist so the app can never write to a car.
>
> Honest limits: the models were trained on simulated data, and physical adapters are still to
> be tested. Python · PySide6 · scikit-learn · SQLite · PyInstaller · GitHub Actions. Built with
> AI-assisted development.
>
> Code: https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI
>
> #Python #MachineLearning #ExplainableAI #DesktopApp #Automotive #OBD2 #SoftwareEngineering

## 5. Résumé entry

**SmartDrive Guardian AI — Offline vehicle diagnostics desktop app** · Python, PySide6,
scikit-learn, SQLite · github.com/Hiranya-Bandara/SmartDrive-Guardian-AI
- Built a 13-page PySide6 application with six worker threads for real-time telemetry,
  background ML inference, persistence, OBD-II communication and offline speech.
- Designed a hybrid diagnostic engine (7 rules + Random Forest + Isolation Forest, 96 features)
  with tree-path explanations; 86.06 % macro F1 on a synthetic test set vs 57.3 % for rules
  alone.
- Implemented a read-only ELM327 OBD-II client with a 65-request allowlist enforced at two
  layers, and 7 PDF / 8 CSV report types.
- Shipped with 643 automated tests (91 % coverage), strict typing, CI on
  Windows/Linux, PyInstaller + Inno Setup packaging, SBOM and threat model.

## 6. Technical interview talking points

1. **Why hybrid?** Rules are explainable and safe for known thresholds; the classifier finds
   multi-signal patterns; the anomaly detector catches the unknown. A documented merge policy
   prevents a model from ever silencing a rule.
2. **Synthetic data honesty.** How the dataset was split by session to avoid leakage, why the
   metrics don't transfer to real cars, and why live ML is off by default.
3. **Explainability trade-off.** Exact tree-path contributions vs SHAP (dependency size in a
   frozen app), and what each tells a user.
4. **Threading in Qt.** Queued signals, latest-only inference requests, bounded queues, shutdown
   ordering, and the garbage-collector deadlock and its fix.
5. **The migration data-loss bug.** How SQLite batch migrations rebuild tables, why foreign keys
   cascaded, how the regression test reproduces it.
6. **Safety by construction.** Allowlist design, why the VIN mode is excluded, why there is no
   clear-codes button, tests that try to bypass every layer.
7. **Packaging lessons.** One-folder vs one-file, dynamic imports PyInstaller misses, resource
   loading in frozen apps, per-user installers, single-source versioning, SBOMs.
8. **What I'd do next.** Real adapter testing, code signing, evaluation on consented real data.

## 7. Demonstration script

Use [demo/storyboard.md](demo/storyboard.md) (90 seconds, eight scenes, narration and
on-screen text). For a live interview demo (≈ 5 minutes): start the Overheating scenario at
10× speed, show the critical coolant finding and its explanation chart, open Trip History and
replay, generate a vehicle overview PDF, then show the Vehicle Connection page in its "no
adapter" state and explain the allowlist.
