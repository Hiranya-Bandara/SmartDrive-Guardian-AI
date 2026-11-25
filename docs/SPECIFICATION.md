<!--
Master project specification. Maintained alongside ROADMAP.md.
Section 36 records implementation amendments agreed during development; the original
requirements above it are preserved verbatim.
-->

# SmartDrive Guardian AI 2.0 — Complete Software Development Specification

## 1. Role and objective

Act as a senior software architect, Python developer, machine learning engineer, UI/UX designer, database engineer, automotive software engineer, cybersecurity engineer, DevOps engineer and QA engineer.

Design and develop a complete, professional, production-style desktop application named **SmartDrive Guardian AI 2.0**.

**Tagline:** Intelligent Vehicle Diagnostics & Predictive Maintenance.

The application must provide intelligent vehicle monitoring, real-time telemetry visualization, machine learning-based diagnostics, anomaly detection, predictive maintenance assistance, vehicle management, trip analytics and optional real-world vehicle connectivity.

The objective is to create a professional software product suitable for GitHub distribution, software engineering portfolios, technical demonstrations and future commercial expansion.

Build the entire project from scratch.

## 2. New GitHub repository and project initialization

Create a completely new GitHub repository.

- GitHub account: Hiranya-Bandara
- Repository name: SmartDrive-Guardian-AI
- Intended repository URL: https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI
- Local project directory: E:\SmartDrive-Guardian-AI
- Initial application version: 2.0.0
- Repository visibility: Public, subject to owner approval.
- Default branch: main

Repository description:

An advanced AI-powered desktop application for intelligent vehicle diagnostics, real-time telemetry monitoring, anomaly detection and predictive maintenance assistance.

Suggested repository topics:

python, pyside6, machine-learning, artificial-intelligence, vehicle-diagnostics, obd2, predictive-maintenance, automotive, desktop-application, scikit-learn, sqlite, iot, data-visualization.

Important requirements:

- Do not use the previous SmartDriveGuardianAI repository.
- Do not clone, import or fork the previous repository.
- Do not reuse its source code.
- Do not import previous Git bundles.
- Do not reuse previous Git history or commits.
- Do not modify or delete the previous repository.
- Do not reuse the previous local project directory.
- Create a fresh Git repository and independent codebase.
- Verify that the new repository name is available before creating it.
- If authentication is required, provide clear instructions for the owner.
- Obtain approval before creating a public remote repository or pushing changes.
- Never fabricate a repository URL or claim successful creation without verification.

Create a clean initial commit and establish the development workflow.

## 3. General development requirements

Develop a fully functional, Windows-first desktop application.

Requirements:

- Python 3.12 as the primary language.
- Professional, scalable and maintainable architecture.
- Modular software design.
- Object-oriented programming where appropriate.
- SOLID principles.
- DRY principles.
- Separation of concerns.
- Meaningful class, variable and function names.
- Appropriate type hints.
- Reusable components.
- Consistent coding standards.
- Proper exception handling.
- Structured logging.
- Automated testing.
- Responsive user interface.
- Offline-first functionality.
- No mandatory paid APIs or cloud services.
- No hardcoded credentials.
- No hardcoded machine-specific file paths.
- No fake functionality.
- No unfinished buttons or placeholder screens in the release.
- No unnecessary tutorial comments or AI-generated filler.
- No fabricated model metrics or test results.
- No unnecessary dependencies.

Develop a complete working application, not simply a prototype interface.

Core functionality must work without internet access or physical vehicle hardware.

## 4. Technology stack

Use the following technologies where appropriate:

### Application development

- Python 3.12
- PySide6
- Qt Designer where beneficial
- Qt Style Sheets (QSS)
- PyQtGraph
- Platformdirs
- Pydantic or Python dataclasses for validated data models

### Database

- SQLite
- SQLAlchemy
- Alembic

### Artificial intelligence and machine learning

- Scikit-learn
- NumPy
- Pandas
- Random Forest
- Isolation Forest
- SHAP
- Joblib

### Hardware integration

- Python-OBD
- PySerial
- Compatible ELM327 OBD-II adapters

### Reports and notifications

- ReportLab
- CSV
- pyttsx3
- Native desktop notifications

### Development and testing

- Pytest
- pytest-qt
- Ruff
- Mypy
- Git
- GitHub Actions

### Application distribution

- PyInstaller
- Inno Setup
- GitHub Releases

Verify dependency compatibility using official documentation and package metadata.

Use reproducible dependency versions and avoid unnecessary libraries.

Use pyproject.toml as the authoritative project configuration and keep other dependency files synchronized or generated from the selected dependency-management workflow.

## 5. Professional project structure

Use a Python src-based architecture.

```text
SmartDrive-Guardian-AI/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── release.yml
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
├── src/
│   └── smartdrive/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       ├── core/
│       │   ├── monitoring.py
│       │   ├── diagnostics.py
│       │   ├── safety_engine.py
│       │   ├── health_score.py
│       │   └── event_manager.py
│       ├── ai/
│       │   ├── preprocessing.py
│       │   ├── training.py
│       │   ├── classifier.py
│       │   ├── anomaly_detector.py
│       │   ├── explainability.py
│       │   ├── evaluation.py
│       │   └── model_manager.py
│       ├── database/
│       │   ├── connection.py
│       │   ├── models.py
│       │   └── repositories/
│       ├── services/
│       │   ├── data_source.py
│       │   ├── simulator.py
│       │   ├── obd_service.py
│       │   ├── replay_service.py
│       │   ├── maintenance_service.py
│       │   └── notification_service.py
│       ├── models/
│       │   ├── vehicle.py
│       │   ├── telemetry.py
│       │   ├── diagnostic.py
│       │   └── alert.py
│       ├── ui/
│       │   ├── main_window.py
│       │   ├── navigation.py
│       │   ├── pages/
│       │   ├── widgets/
│       │   ├── dialogs/
│       │   ├── workers/
│       │   └── themes/
│       │       ├── dark.qss
│       │       └── light.qss
│       ├── reports/
│       │   ├── pdf_generator.py
│       │   └── csv_exporter.py
│       ├── config/
│       │   ├── settings.py
│       │   └── constants.py
│       ├── utils/
│       │   ├── logger.py
│       │   ├── validators.py
│       │   └── exceptions.py
│       └── assets/
│           ├── icons/
│           ├── images/
│           └── fonts/
├── migrations/
├── datasets/
├── trained_models/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── ui/
│   └── fixtures/
├── scripts/
├── installer/
├── docs/
├── main.py
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── ROADMAP.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
├── .gitignore
└── .editorconfig
```

Treat this as the target architecture. Create modules when required rather than creating dozens of unnecessary empty files.

Use a shared service layer to separate presentation, business logic, persistence and hardware communication.

GUI components must not directly implement database queries, model training or OBD-II communication.

## 6. Professional UI/UX design

Create a premium automotive technology interface inspired by modern vehicle instrument clusters and professional automotive diagnostic software.

The interface must not resemble an outdated Tkinter application.

Design requirements:

- Modern and clean appearance.
- Premium automotive aesthetic.
- Collapsible sidebar.
- Professional navigation.
- Rounded cards.
- Consistent spacing.
- Responsive window layout.
- Lightweight animations.
- Interactive digital gauges.
- Real-time data visualizations.
- Custom icons.
- Professional typography.
- Clear status indicators.
- Search and filtering controls.
- Tooltips.
- Loading states.
- Empty states.
- Disconnected states.
- Error states.
- Accessible keyboard navigation.
- High-DPI display support.
- Dark, light and system themes.
- Consistent styling throughout all pages.

### Dark theme colour palette

- Primary background: #0B1120
- Secondary background: #151E2D
- Elevated surface: #1E293B
- Primary accent: #06B6D4
- Secondary accent: #3B82F6
- Primary text: #F8FAFC
- Secondary text: #94A3B8
- Border: #334155
- Normal: #22C55E
- Warning: #F59E0B
- Critical: #EF4444
- Offline: #64748B

Typography:

- Inter where properly licensed and available.
- Segoe UI as a native Windows alternative.

Use appropriately licensed Lucide-style icons.

Do not rely exclusively on colours to communicate important statuses.

Design the interface for laptop and desktop resolutions, including 1366×768, 1920×1080 and higher-resolution displays.

## 7. Application navigation

Implement these fully functional pages:

1. Dashboard
2. Live Monitoring
3. AI Diagnostics
4. Vehicle Garage
5. Simulation Laboratory
6. Predictive Maintenance
7. OBD-II Diagnostics
8. Trip Analytics
9. Alert Centre
10. Reports
11. Settings
12. About

Use reusable UI components throughout the application.

## 8. Dashboard

Create a professional main dashboard displaying:

- Selected vehicle.
- Current connection status.
- Current operating mode.
- Experimental vehicle health score.
- Vehicle illustration.
- Engine temperature gauge.
- Engine RPM gauge.
- Digital speedometer.
- Fuel level indicator.
- Engine load.
- Battery voltage where supported.
- Active warning count.
- Diagnostic summary.
- Recent alerts.
- Maintenance summary.
- Real-time performance charts.
- Start monitoring button.
- Stop monitoring button.
- Last successful sensor update.
- Connection quality indicator where meaningful.

Clearly distinguish simulation, live vehicle and replay data.

Do not display invented values for unavailable sensors.

## 9. Live monitoring

Implement real-time monitoring of supported vehicle parameters.

Parameters:

- Engine coolant temperature.
- Engine RPM.
- Vehicle speed.
- Fuel level.
- Engine load.
- Throttle position.
- Intake air temperature.
- Control module voltage.
- Oil temperature where supported.
- Oil pressure where supported.
- Fuel consumption where supported or clearly estimated.
- Additional supported diagnostic parameters.

Features:

- Interactive live graphs.
- Configurable refresh interval.
- Minimum, maximum and average values.
- Sensor selection.
- Historical trend visualization.
- Zooming and chart navigation.
- Configurable time ranges.
- Pause and resume monitoring.
- Session recording.
- Missing sensor handling.
- Stale data indicators.
- Connection status.
- Unit conversion.
- CSV export.

Ensure chart history is bounded and monitoring does not cause continuous memory growth.

## 10. AI diagnostics

Develop an intelligent hybrid diagnostic system combining transparent rules with trained machine learning models.

Display:

- Detected abnormalities.
- Possible fault categories.
- Rule-based diagnostic findings.
- Machine learning predictions.
- Anomaly detection results.
- Severity classification.
- Model confidence only where supported.
- Contributing sensor values.
- Explainable AI results.
- Recommended next steps.
- Prediction timestamp.
- Model version.
- Data quality indicators.
- Diagnostic history.
- Prediction limitations.

Experimental fault categories:

- Cooling system abnormalities.
- Engine lubrication abnormalities.
- Transmission abnormalities.
- Fuel system abnormalities.
- Electrical system abnormalities.
- Sensor failures.
- Brake-related abnormalities when relevant sensor data exists.
- Unknown anomalies.

Support simultaneous findings rather than always forcing one fault category.

Provide an insufficient-data state.

## 11. Digital vehicle garage

Implement complete vehicle management.

Functions:

- Add vehicles.
- Edit vehicles.
- Delete vehicles with confirmation.
- Search vehicles.
- Filter vehicles.
- Select active vehicle.
- View individual vehicle history.
- Manage vehicle images.
- View vehicle maintenance information.

Vehicle information:

- Vehicle name.
- Manufacturer.
- Model.
- Manufacturing year.
- Fuel type.
- Engine capacity.
- Transmission type.
- Current mileage.
- Registration number, optional.
- VIN, optional.
- Purchase date, optional.
- Last service date.
- Next service date.
- Vehicle image, optional.
- Notes.

Store vehicle-specific information and history separately.

Protect personally identifying vehicle information and allow users to remove it.

## 12. Advanced simulation laboratory

Build a complete interactive vehicle simulator that works without physical hardware.

Simulation scenarios:

- Normal driving.
- Engine idling.
- Highway driving.
- Urban driving.
- Heavy traffic.
- Rapid acceleration.
- Engine overheating.
- Cooling system abnormalities.
- Simulated lubrication failure.
- Simulated brake abnormalities.
- Fuel system abnormalities.
- Electrical abnormalities.
- Sensor failures.
- Intermittent connection loss.
- Multiple simultaneous abnormalities.

Functions:

- Scenario selection.
- Adjustable sensor values.
- Manual input controls.
- Interactive sliders.
- Adjustable simulation speed.
- Reproducible random seeds.
- Gradual fault development.
- Measurement noise.
- Missing sensor data.
- Scenario reset.
- Automatic telemetry generation.
- Session recording.
- Session replay.
- Synthetic training dataset generation.
- Ground-truth simulation labels.

Generate coherent time-dependent telemetry instead of completely independent random values.

Clearly identify all simulation data throughout the application.

## 13. Predictive maintenance centre

Implement an intelligent maintenance management system.

Features:

- Maintenance scheduling.
- Service reminders.
- Mileage-based reminders.
- Date-based reminders.
- Maintenance history.
- Maintenance cost tracking.
- Upcoming service list.
- Overdue maintenance indicators.
- Recurring fault analysis.
- Historical sensor trends.
- Experimental maintenance risk estimates.
- Maintenance record editing.
- Completed service tracking.
- Maintenance reports.

Allow users to create, update, complete and delete maintenance records.

Do not invent reliable failure dates or remaining useful life estimates without appropriate longitudinal datasets and validation.

## 14. OBD-II vehicle connectivity

Integrate compatible ELM327-based OBD-II adapters using Python-OBD.

Support:

- Compatible USB serial connections.
- Compatible Bluetooth serial connections.
- Additional supported transports only after verification.
- COM port discovery.
- Manual port selection.
- Connection management.
- Connect and disconnect controls.
- Connection timeout handling.
- Automatic reconnection with bounded retries.
- Supported PID discovery.
- Live telemetry reading.
- Read-only DTC retrieval.
- Diagnostic trouble code descriptions.
- Adapter error handling.
- Unsupported sensor handling.
- Connection logging.

Important restrictions:

- Keep all vehicle communication read-only.
- Never modify ECU settings.
- Never execute actuator commands.
- Never automatically clear fault codes.
- Never interfere with vehicle control systems.
- Never fabricate hardware readings.
- Do not claim support for every vehicle.
- Mark hardware compatibility as experimental until physically tested.

Use mock adapters for automated testing when physical hardware is unavailable.

## 15. Trip analytics and replay

Implement a complete vehicle session recording and replay system.

Features:

- Start trip recording.
- Stop trip recording.
- Trip duration.
- Estimated distance where supported.
- Average speed.
- Maximum speed.
- RPM analysis.
- Temperature analysis.
- Fuel usage analysis where supported.
- Alerts during trips.
- Trip comparison.
- Interactive graphs.
- Recorded session replay.
- Adjustable replay speed.
- Pause and resume.
- Timeline seeking.
- Historical session filtering.
- Trip reports.
- Trip deletion with confirmation.

Clearly label recorded and replayed telemetry.

Never present recorded data as current live vehicle data.

## 16. Alert centre and notification system

Implement a complete event and notification system.

Severity classifications:

- Information.
- Normal.
- Warning.
- Critical.
- Unknown or unavailable.

Functions:

- Timestamped alerts.
- Alert acknowledgement.
- Search.
- Filtering.
- Severity grouping.
- Alert history.
- Duplicate suppression.
- Configurable notification preferences.
- Optional desktop notifications.
- Optional notification sounds.
- Optional offline voice notifications.
- Alert cooldown periods.
- Persistent abnormality tracking.

Prevent repeated alerts from overwhelming the user.

Do not describe the absence of detected abnormalities as proof that a vehicle is safe to drive.

## 17. Reports and export system

Generate professionally designed reports.

Report types:

- Vehicle diagnostic report.
- Vehicle telemetry report.
- Vehicle condition report.
- Trip summary report.
- Maintenance history report.
- Alert history report.
- Machine learning evaluation report.

Export formats:

- PDF.
- CSV.

Features:

- Vehicle selection.
- Date-range selection.
- Report type selection.
- Report preview where practical.
- User-selected export location.
- Export history where useful.

PDF reports must include:

- SmartDrive Guardian AI branding.
- Vehicle information.
- Report date.
- Relevant telemetry.
- Charts.
- Diagnostic findings.
- Recommendations.
- Data-source identification.
- Model information where applicable.
- Safety and validation limitations.

Never generate misleading diagnostic claims.

## 18. Settings

Implement persistent application settings.

Include:

- Dark theme.
- Light theme.
- System theme.
- Measurement units.
- Monitoring frequency.
- Chart preferences.
- Alert preferences.
- Notification sounds.
- Voice notifications.
- OBD-II connection preferences.
- Data retention.
- Database backup.
- Database restoration.
- Application data location.
- Privacy preferences.
- Application version.
- Machine learning model information.
- Reset preferences.
- About application.

Persist user preferences across sessions.

Use safe defaults.

## 19. Operating modes

Implement three interchangeable telemetry sources using a common data-source interface.

### Simulation mode

Generate coherent and reproducible vehicle telemetry without hardware.

### Live vehicle mode

Read supported vehicle telemetry through compatible OBD-II hardware.

### Replay mode

Load and replay previously recorded telemetry sessions.

All operating modes must share the same:

- Telemetry model.
- Validation pipeline.
- Diagnostic engine.
- Database integration.
- Monitoring service.
- Visualization pipeline.
- Alert system.

Prevent accidental mixing of live, simulated and recorded datasets.

## 20. Artificial intelligence architecture

Use a hybrid architecture consisting of:

1. Telemetry data processing.
2. Feature engineering.
3. Rule-based diagnostic engine.
4. Random Forest classifier.
5. Isolation Forest anomaly detector.
6. Explainable AI module.
7. Diagnostic decision engine.
8. Experimental vehicle health score.
9. Recommendation engine.

The machine learning system must perform genuine trained-model inference.

Do not simulate machine learning results or use randomly generated confidence percentages.

### 20.1 Rule-based diagnostic engine

Implement:

- Configurable thresholds.
- Vehicle-specific configuration where available.
- Multiple sensor conditions.
- Persistence requirements.
- Hysteresis.
- Missing data handling.
- Severity classification.
- Transparent explanations.
- Simultaneous diagnostic findings.

Avoid universal threshold assumptions across different vehicle types.

### 20.2 Random Forest classifier

Develop a complete supervised learning pipeline.

Requirements:

- Dataset loading.
- Data cleaning.
- Data validation.
- Missing-value processing.
- Feature engineering.
- Feature selection.
- Label validation.
- Model training.
- Model evaluation.
- Hyperparameter optimization where justified.
- Model serialization.
- Model versioning.
- Reproducible training configuration.
- Inference integration.
- Probability calibration where practical.

Evaluate with:

- Accuracy.
- Precision.
- Recall.
- F1-score.
- Confusion matrix.
- Per-class performance.
- False-positive rates.
- False-negative rates.

Use session-based or vehicle-based train/test splits where appropriate to prevent data leakage.

Provide genuine evaluation results generated through executed training and evaluation scripts.

### 20.3 Isolation Forest anomaly detection

Implement:

- Baseline behaviour learning.
- Unsupervised anomaly detection.
- Anomaly scoring.
- Abnormal event tracking.
- Context-aware operating behaviour where possible.
- Missing data handling.
- Configurable anomaly thresholds.

Do not present anomaly scores as verified failure probabilities.

### 20.4 Explainable AI

Use SHAP or another appropriate explanation method.

Display:

- Important model features.
- Features contributing to individual predictions.
- Supporting and opposing evidence.
- Human-readable explanations.
- Model limitations.

Explanations must originate from actual model outputs.

### 20.5 Experimental vehicle health score

Implement a transparent condition indicator ranging from 0 to 100.

Consider:

- Available telemetry.
- Persistent abnormalities.
- Diagnostic trouble codes.
- Maintenance status.
- Recent alerts.
- Data completeness.

Provide an explanation of score components.

Display an unavailable state when there is insufficient evidence.

Clearly label it as an experimental condition indicator rather than a certified safety rating.

### 20.6 Dataset management

Use appropriately licensed and documented automotive datasets when suitable.

If real-world datasets are unavailable:

- Generate reproducible synthetic data.
- Document generation methods.
- Include normal and abnormal scenarios.
- Include realistic operating variations.
- Include missing values and noise.
- Include different session conditions.
- Preserve ground-truth labels.
- Clearly label synthetic data.
- Separate training, validation and testing sessions.

Do not claim independent real-world validation when models are trained or evaluated only on simulated data.

Maintain dataset documentation, model cards, model versions and evaluation records.

## 21. Database architecture

Use SQLite, SQLAlchemy and Alembic.

Create appropriate database entities for:

- Vehicles.
- Driving sessions.
- Telemetry readings.
- Diagnostic results.
- Diagnostic trouble codes.
- Alerts.
- Maintenance records.
- Maintenance schedules.
- Application settings.
- Model metadata.
- Export history where useful.

Requirements:

- Primary keys.
- Foreign keys.
- Referential integrity.
- Database constraints.
- Appropriate indexes.
- Parameterized queries.
- Transaction management.
- Batch telemetry insertion.
- Safe migration procedures.
- Automatic database initialization.
- Database backup and restoration.
- Data retention policies.
- Safe shutdown.
- Database error recovery.

Use operating system-specific writable application data directories.

Do not store runtime databases, personal records, logs or settings inside application installation directories or Git repositories.

## 22. Performance and concurrency

Ensure the application remains responsive during continuous monitoring.

Implement:

- QThread or QThreadPool.
- Worker objects.
- Qt signals and slots.
- Thread-safe communication.
- Controlled polling.
- Background model inference where necessary.
- Background database writes.
- Bounded telemetry queues.
- Efficient chart updates.
- Resource cleanup.
- Graceful cancellation.
- Safe shutdown.

Never modify Qt widgets directly from background threads.

Avoid:

- UI freezing.
- Memory leaks.
- Unbounded buffers.
- Repeated unnecessary database queries.
- Blocking hardware operations on the UI thread.
- Unnecessary model reloads.

Measure and document application performance using reproducible tests.

## 23. Security, privacy and safety

Implement:

- Input validation.
- Safe database access.
- Exception handling.
- Secure file handling.
- Dependency vulnerability review.
- Trusted model loading.
- Privacy-conscious logging.
- Local data protection.
- Data retention controls.
- No hidden telemetry collection.
- No unnecessary network communication.
- No hardcoded secrets.
- Safe handling of user-selected export paths.

Do not deserialize untrusted model files.

Do not collect VINs, registration numbers or other personal data unless voluntarily supplied and needed for application functionality.

Include a visible safety disclaimer.

SmartDrive Guardian AI is an experimental diagnostic and maintenance assistant. It is not a certified vehicle safety system, autonomous driving system or replacement for a qualified mechanic.

All recommendations must be grounded in available evidence and must not create false assurances about vehicle safety.

## 24. Logging and error handling

Implement a centralized logging system.

Log levels:

- DEBUG
- INFO
- WARNING
- ERROR
- CRITICAL

Requirements:

- Rotating log files.
- Structured log messages.
- Application lifecycle logging.
- Hardware connection error logging.
- Database error logging.
- Machine learning error logging.
- Monitoring event logging.
- User-friendly error messages.
- Technical diagnostic details where appropriate.
- Protection of sensitive information.

Avoid exposing personal vehicle information unnecessarily.

## 25. Automated testing

Implement tests throughout development.

Test coverage must include:

- Application configuration.
- Vehicle data models.
- Telemetry data models.
- Database repositories.
- Database migrations.
- Database backup and restoration.
- Simulator behaviour.
- Reproducible simulation scenarios.
- Diagnostic rules.
- Severity classification.
- Missing sensor data.
- Stale telemetry.
- Machine learning preprocessing.
- Model training and inference.
- Anomaly detection.
- Health score calculation.
- Alert suppression.
- Maintenance scheduling.
- Trip recording.
- Replay functionality.
- Report generation.
- OBD-II adapter mocking.
- Connection timeouts.
- User interface smoke tests.
- Application startup.
- Application shutdown.

Use Pytest and pytest-qt.

Use temporary databases and deterministic test fixtures.

Mock unavailable hardware.

Never claim that physical hardware testing has passed unless it has actually been performed.

Run relevant tests after every major implementation.

## 26. Git and GitHub workflow

Initialize a completely new Git repository.

Do not use any previous repository history.

Use:

- main — stable application releases.
- development — integration and testing.

Keep main as the default branch.

Create feature branches only when necessary:

- feature/project-foundation
- feature/desktop-ui
- feature/database
- feature/vehicle-simulation
- feature/vehicle-garage
- feature/live-monitoring
- feature/ai-engine
- feature/obd-integration
- feature/maintenance
- feature/trip-analytics
- feature/reports
- feature/notifications
- feature/testing
- feature/packaging

Use meaningful conventional commits.

Examples:

```text
chore: initialize SmartDrive Guardian AI repository
feat: implement modular application architecture
feat: establish database persistence layer
feat: implement professional desktop dashboard
feat: add interactive vehicle simulation laboratory
feat: implement machine learning diagnostics
feat: integrate read-only OBD-II telemetry
test: add automated diagnostic engine tests
fix: handle vehicle connection timeouts
docs: add application installation guide
build: configure Windows installer
```

Development rules:

- Never develop unfinished features directly on main.
- Keep commits logically organized.
- Use pull requests for major feature integration.
- Run automated tests before merging.
- Never force-push.
- Never rewrite existing history unnecessarily.
- Never commit secrets, databases or virtual environments.
- Do not push or merge remote changes without approval.
- Do not create unnecessary empty feature branches.

## 27. Continuous integration and delivery

Configure GitHub Actions to:

- Install dependencies.
- Verify Python compatibility.
- Validate project configuration.
- Run Ruff linting.
- Check code formatting.
- Execute automated tests.
- Run configured static type checks.
- Generate test coverage reports.
- Perform appropriate dependency checks.
- Build Windows application artifacts.
- Verify packaged application startup where feasible.

Configure release workflows for approved version tags.

Use secure permissions for GitHub Actions.

## 28. Windows packaging and distribution

Create a professional downloadable Windows application.

Deliverables:

- Windows 64-bit application.
- Portable application distribution.
- Professional Windows installer.
- Application icon.
- Version information.
- Start Menu shortcut.
- Optional desktop shortcut.
- Uninstaller.
- Bundled runtime dependencies.
- Bundled application assets.
- Bundled trusted trained models.
- Correct application data paths.

Use PyInstaller and Inno Setup.

Users must not need to install Python manually.

Test the packaged application independently of the development environment.

Target release files:

```text
SmartDriveGuardianAI-2.0.0-Windows-x64-Setup.exe
SmartDriveGuardianAI-2.0.0-Windows-x64-Portable.zip
```

Do not claim the application is digitally signed unless valid signing has actually been performed.

Publish verified release artifacts through GitHub Releases after approval.

## 29. Professional documentation

Create a professional README.md containing:

- Project branding.
- Project name and tagline.
- Overview.
- Key features.
- Actual application screenshots.
- Demonstration video when available.
- Technology stack.
- Architecture diagram.
- Installation instructions.
- Developer setup.
- Usage instructions.
- Operating modes.
- Machine learning methodology.
- Actual model evaluation results.
- Supported hardware information.
- Project structure.
- Testing instructions.
- Known limitations.
- Safety disclaimer.
- Future roadmap.
- Developer information.
- License information.

Create supporting documentation:

- ROADMAP.md
- CHANGELOG.md
- CONTRIBUTING.md
- SECURITY.md
- Architecture documentation.
- Database documentation.
- Machine learning documentation.
- Dataset documentation.
- Hardware integration documentation.
- User guide.
- Developer guide.
- Build and release guide.

Propose an appropriate open-source license and obtain owner approval.

Do not create fake screenshots, download links, test results, performance metrics or badges.

## 30. Development roadmap

Maintain ROADMAP.md as the authoritative project progress tracker.

### Phase 1 — Foundation & Architecture

Target: Days 1–5.

- [ ] Create the new GitHub repository and fresh Git history.
- [ ] Establish development and feature branch workflow.
- [ ] Create professional project architecture.
- [ ] Implement application configuration and entry point.
- [ ] Implement database foundation and migrations.
- [ ] Implement logging and error handling.
- [ ] Configure initial testing and continuous integration.

### Phase 2 — Professional Desktop Application

Target: Days 6–11.

- [ ] Implement PySide6 application shell.
- [ ] Build dashboard and sidebar navigation.
- [ ] Create reusable UI components.
- [ ] Implement dark and light themes.
- [ ] Build interactive gauges and live charts.
- [ ] Implement digital vehicle garage.
- [ ] Implement advanced simulation laboratory.
- [ ] Implement background monitoring workers.

### Phase 3 — Advanced AI Engine

Target: Days 12–18.

- [ ] Prepare and validate datasets.
- [ ] Train Random Forest classifier.
- [ ] Implement Isolation Forest anomaly detection.
- [ ] Implement rule-based diagnostic engine.
- [ ] Implement experimental vehicle health score.
- [ ] Implement explainable AI.
- [ ] Evaluate model predictions and false alarms.

### Phase 4 — Vehicle Integration

Target: Days 19–25.

- [ ] Implement read-only OBD-II connectivity.
- [ ] Implement diagnostic trouble code reader.
- [ ] Handle hardware failures and unsupported sensors.
- [ ] Implement trip recording and replay.
- [ ] Implement maintenance centre.
- [ ] Implement PDF and CSV reports.
- [ ] Implement desktop and voice notifications.

### Phase 5 — Professional Release

Target: Days 26–30.

- [ ] Perform integration and performance testing.
- [ ] Review security, privacy and safety.
- [ ] Configure automated release builds.
- [ ] Build Windows executable.
- [ ] Build Windows installer.
- [ ] Create application branding and icon.
- [ ] Create actual screenshots and demonstration video.
- [ ] Finalize documentation.
- [ ] Publish Version 2.0.0 after approval.

Total: 38 development tasks.

Treat this schedule as a development target for a portfolio-quality application.

Real-world validation and physical vehicle testing may require additional time.

Do not sacrifice reliability to satisfy an arbitrary deadline.

## 31. Future expansion

Design the architecture so future versions can support:

- FastAPI backend.
- Cloud synchronization.
- Web dashboard.
- Mobile applications.
- Remote vehicle monitoring.
- Fleet management.
- Advanced time-series forecasting.
- Additional automotive communication protocols.
- Advanced predictive maintenance.
- Optional AI diagnostic assistant.

Do not implement unnecessary cloud or mobile functionality in the initial desktop release.

## 32. Development agent operating instructions

You must implement the actual application in the new project directory rather than simply provide explanations or code snippets.

Before starting:

1. Verify the available development environment.
2. Verify Python 3.12 availability.
3. Verify Git availability.
4. Verify GitHub authentication.
5. Check that the proposed new directory does not contain unrelated files.
6. Verify that the proposed GitHub repository name is available.
7. Establish the fresh project directory.
8. Initialize the new Git repository.
9. Establish an implementation plan.
10. Create ROADMAP.md.

During development:

- Create complete and functional implementations.
- Execute actual development commands.
- Create and edit real project files.
- Install compatible dependencies.
- Run automated tests.
- Run application smoke tests.
- Resolve errors before proceeding.
- Maintain professional code quality.
- Keep the roadmap updated.
- Keep documentation synchronized.
- Avoid fake features.
- Avoid unnecessary tutorial comments.
- Make reasonable technical decisions independently.
- Document architectural decisions.
- Report limitations transparently.
- Never access or modify the previous project repository.
- Never perform destructive operations on unrelated files.
- Obtain approval before remote repository creation, pushes, merges or public releases.

When operating in a sandbox or remote coding environment without access to my Windows computer:

- Work in a fresh isolated project directory.
- Do not claim to have modified E:\SmartDrive-Guardian-AI.
- Provide the complete source code as an actual downloadable archive or another supported transfer mechanism.
- Include exact local PowerShell setup instructions.
- Include dependency installation instructions.
- Include testing instructions.
- Include Git initialization and remote setup instructions.
- Do not create an incremental Git bundle that depends on the previous repository.

## 33. Phase completion reporting

After every development phase, report:

- Completed tasks.
- Remaining tasks.
- Files created.
- Files modified.
- Architectural decisions.
- Commands executed.
- Dependencies installed.
- Tests executed.
- Actual test results.
- Known issues.
- Unverified functionality.
- Application launch instructions.
- Git status.
- Recommended next phase.

Mark roadmap tasks complete only after verifying the corresponding functionality.

## 34. Final acceptance criteria

The application is ready for release when:

- A completely new GitHub repository is established.
- The previous repository remains untouched.
- The application launches successfully.
- All included pages function.
- The interface is professional and responsive.
- Dark and light themes function.
- Vehicle profiles persist correctly.
- Simulation mode works independently of hardware.
- Live charts display incoming telemetry.
- Fault simulation scenarios work.
- Trained machine learning models perform genuine inference.
- Evaluation results are reproducible.
- Diagnostic explanations are grounded in model outputs.
- Alerts operate without excessive duplication.
- Database operations function reliably.
- Maintenance management works.
- Trip recording and replay work.
- PDF and CSV exports work.
- OBD-II integration handles connection failures and unsupported sensors.
- Application settings persist.
- Automated tests pass.
- No sensitive information is committed.
- Windows packaging is verified.
- Users can install the application without installing Python manually.
- Documentation matches implemented functionality.
- Experimental features and hardware limitations are clearly identified.

## 35. Start implementation

Begin building SmartDrive Guardian AI 2.0 from scratch.

Use the new project directory:

E:\SmartDrive-Guardian-AI

Use the new proposed GitHub repository:

https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI

Do not use, clone, import, modify or delete the previous repository.

Start with Phase 1: Foundation & Architecture.

Create the actual project files, configure the Python environment, establish the modular architecture, implement application configuration, initialize the database, configure logging and establish automated testing.

Complete and verify each phase before progressing to the next.

The final result must be a complete, modern, professional and maintainable AI-powered automotive intelligence desktop application.

## 36. Implementation amendments

Recorded as development proceeds. Each amendment explains why the implementation differs from the
letter of the specification while preserving its intent. The full rationale is in
docs/architecture.md (decision log).

| Date | Section | Amendment |
|---|---|---|
| 2026-11-24 | §5 project structure | Alembic migrations live in `src/smartdrive/database/migrations/` (not top-level `migrations/`) so they ship inside the installed package and PyInstaller bundle. A developer `alembic.ini` sits at the root. |
| 2026-11-24 | §5 project structure | Package folders (`core/`, `ai/`, `services/`, `ui/`, `reports/`, `assets/`) and root `datasets/`, `trained_models/`, `installer/` are created in the phase that adds real content to them, per §5's instruction not to create unnecessary empty files. |
| 2026-11-24 | §18, §21 settings | User preferences persist in a validated `settings.json` in the per-user config folder; the `app_settings` table holds database-scoped state. Preferences such as the log level are needed before the database opens. |
| 2026-11-24 | §4 dependencies | Runtime dependencies are declared in the phase that first imports them. Phase 1 uses platformdirs, Pydantic, SQLAlchemy and Alembic. |
| 2026-11-24 | §27 CI | `release.yml` is added in Phase 5 with the packaging work, so the workflow is not a non-functional placeholder. `ci.yml` is active from Phase 1. |
| 2026-11-24 | §32 entry point | Phase 1's entry point is a maintenance CLI (`info`, `db check/backup/restore`, `settings show/reset`), not a placeholder window. From Phase 2 the default command launches the GUI. |
| 2026-11-24 | §5 themes | `ui/themes/dark.qss` and `light.qss` are replaced by one `stylesheet.qss` template filled from typed palettes (`palette.py`), so the themes cannot drift apart (DRY). |
| 2026-11-24 | §4 dependencies | `PySide6-Essentials` is used instead of the `PySide6` meta-package. It contains every module the application uses (QtWidgets, QtSvg) without the large add-ons, which reduces install and bundle size. |
| 2026-11-24 | §7 navigation | Pages planned for later phases appear in a "Coming later" sidebar section, disabled and labelled with their phase, so no placeholder screens exist. |
| 2026-11-24 | §8 dashboard | No health score or diagnostic summary is shown until the Phase 3 engine exists. Recent alerts lists stored alerts only and states that an empty list is not proof of safety. Gauge colour bands are generic display ranges, not diagnoses. |
| 2026-11-24 | §32 entry point | `smartdrive` with no command still prints `info` (keeps the Phase 1 CLI and tests stable). The GUI is launched with `smartdrive gui` or the windowless `smartdrive-gui` entry point. |
| 2026-11-25 | Phase 3 §6 structure | Implemented as `ai/dataset.py` (generation, splitting, validation, storage), `ai/features.py`, `ai/training.py`, `ai/classifier.py`, `ai/anomaly_detector.py`, `ai/explainability.py`, `ai/evaluation.py`, `ai/reporting.py`, `ai/model_registry.py` (model management); `core/telemetry_window.py`, `core/rule_engine.py` (diagnostic rules; there is no separate `safety_engine.py`), `core/health_score.py`, `core/recommendations.py`; `services/diagnostic_engine.py` (hybrid engine), `services/diagnostic_service.py`; `ui/diagnostics_controller.py`, `ui/workers/inference_worker.py`, `ui/pages/ai_diagnostics.py`, `ui/widgets/{health_score,diagnostic_card,explanation_chart}.py`. |
| 2026-11-25 | Phase 3 §13 explainability | Exact tree-path decomposition (Saabas / treeinterpreter method) plus permutation importance instead of SHAP. SHAP's compiled dependencies (numba, llvmlite) add packaging complexity for the Phase 5 Windows build. The decision and the method's limitation are documented in `docs/ml/README.md`. |
| 2026-11-25 | Phase 3 §17, §5 | Trained models live in `src/smartdrive/ai/artifacts/` (package data) instead of a top-level `trained_models/`, so they ship with the installed application. Datasets are stored as NumPy `.npz` + JSON; pandas is not needed. Matplotlib is a training-only extra. |
| 2026-11-25 | Phase 3 §8 categories | Classified categories: cooling, lubrication, fuel, electrical, sensor. Transmission and brake are not modelled (no telemetry exists for them). "Unknown" conditions are covered by the anomaly detector and by model abstention, not by a class. |
| 2026-11-25 | Phase 3 §11 | An Isolation Forest anomaly on its own is reported as INFORMATION and raises no alert; see the evaluation report for the measured false alarms that motivated this. |

