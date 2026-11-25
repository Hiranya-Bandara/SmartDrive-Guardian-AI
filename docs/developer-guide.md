# Developer guide

All commands are for **Windows PowerShell**, run from the project root `E:\SmartDrive-Guardian-AI`.

## Prerequisites

- Python **3.12** (64-bit) from python.org, including the `py` launcher.
  Check with `py -3.12 --version`.
- Git for Windows. Check with `git --version`.
- GitHub CLI (`winget install --id GitHub.cli`) for creating the remote. This is optional; the
  web interface works too.

## Environment setup

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-dev.ps1
.\.venv\Scripts\Activate.ps1
```

If activation is blocked, run
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once.

## First-time repository setup

This creates a brand-new, independent history. It never touches the previous repository.

```powershell
git init -b main
git config core.autocrlf false
git add .gitignore .gitattributes .editorconfig LICENSE README.md
git commit -m "chore: initialize SmartDrive Guardian AI repository"
git switch -c development
git switch -c feature/project-foundation
git add .
git status            # confirm: no .venv, *.db, logs or settings.json listed
git commit -m "feat: establish Phase 1 foundation and architecture"
git switch development
git merge --no-ff feature/project-foundation -m "merge: Phase 1 foundation into development"
```

Create the remote (only after you approve making it public):

```powershell
gh auth login
gh repo view Hiranya-Bandara/SmartDrive-Guardian-AI   # should report "Could not resolve" if the name is free
gh repo create Hiranya-Bandara/SmartDrive-Guardian-AI --public `
  --description "An advanced AI-powered desktop application for intelligent vehicle diagnostics, real-time telemetry monitoring, anomaly detection and predictive maintenance assistance." `
  --source . --remote origin
git push -u origin main
git push -u origin development
git push -u origin feature/project-foundation
gh repo edit Hiranya-Bandara/SmartDrive-Guardian-AI --default-branch main `
  --add-topic python,pyside6,machine-learning,artificial-intelligence,vehicle-diagnostics,obd2,predictive-maintenance,automotive,desktop-application,scikit-learn,sqlite,iot,data-visualization
```

Then check that the **CI** workflow is green under the repository's **Actions** tab.

## Daily workflow

```powershell
git switch development; git pull
git switch -c feature/desktop-ui
# ...work...
.\scripts\check.ps1
git commit -m "feat: implement PySide6 application shell"
git push -u origin feature/desktop-ui
gh pr create --base development --fill
```

## Running

```powershell
smartdrive gui                               # desktop application
smartdrive-gui                               # same, without a console window
smartdrive --home .\.smartdrive-home gui     # isolated data folder for experiments (git-ignored)
smartdrive                                   # CLI info; also db / settings commands
```

## GUI development notes

- Pages receive a `UiContext` (services, state, theme, monitoring controller, notifier). They
  must not import `smartdrive.database` or create threads.
- Anything custom-painted implements `apply_palette(palette)`. The main window calls it on
  every widget when the theme changes.
- Combo boxes return `StrEnum` item data as plain `str`; read them with
  `widgets.base.combo_enum(combo, EnumType)`.
- To render real screenshots: `python scripts\capture_screenshots.py` (writes `docs\screenshots`).

## Tests

```powershell
python -m pytest                        # all tests
python -m pytest -m "not integration and not ui"   # fast unit tests only
python -m pytest tests/ui               # GUI tests (pytest-qt, headless by default)
python -m pytest --cov                  # with coverage
```

The autouse fixture in `tests/conftest.py` points `SMARTDRIVE_HOME` at a temporary folder, so
tests can never touch your real data. `tests/conftest.py` also defaults `QT_QPA_PLATFORM` to
`offscreen`. To watch the GUI tests on screen, set `$env:QT_QPA_PLATFORM = "windows"` first.

## Database migrations

```powershell
$env:SMARTDRIVE_DB_URL = "sqlite:///$((Get-Location).Path -replace '\\','/')/.smartdrive-home/dev.db"
alembic upgrade head
# edit src\smartdrive\database\models.py, then:
alembic revision --autogenerate -m "add trip notes"
```

Review the generated file. Replace `smartdrive.database.types.UtcDateTime()` with `sa.DateTime()`
and run `python -m pytest tests/integration/test_migrations.py tests/integration/test_vehicle_integration_db.py`.
Test an upgrade against a database that contains child rows (telemetry under trips, codes under
vehicles): a batch rebuild that drops rows is only caught that way. The application runs
migrations with foreign keys off and checks `PRAGMA foreign_key_check` before committing; the
Alembic CLI engine does not enable foreign keys at all.

## Updating dependencies

Edit `pyproject.toml`, then:

```powershell
python -m pip install uv
.\scripts\lock-dependencies.ps1
python -m pip install -r requirements-dev.txt
```

## Machine-learning models

The trained models ship in `src\smartdrive\ai\artifacts\`. The application never trains at
startup. To regenerate the dataset, models, evaluation report and figures:

```powershell
python -m pip install -e ".[training]"          # matplotlib, only needed for the figures
python scripts\train_models.py                  # full run: dataset 1.1.0, both models, all reports
python scripts\train_models.py --profile small --artifacts-dir out\models --reports-dir out\ml --datasets-dir out\ds
```

A full run takes about 20 minutes on a 2-core machine; most of that is the built-in scenario
check. It writes:

- `datasets\sdg-ds-1.1.0\` (`dataset.npz` is git-ignored; `metadata.json` and `sessions.json` are tracked)
- `src\smartdrive\ai\artifacts\` (models and `manifest.json` with SHA-256 hashes)
- `docs\ml\` (metrics, model card, dataset card, evaluation report, figures)

Commit the artefacts and the reports together: the registry refuses any model whose hash does
not match the manifest. Changing the feature extraction requires bumping
`FEATURE_SCHEMA_VERSION` in `ai\features.py` and retraining. Upgrading scikit-learn to a new minor
version requires retraining, because the registry refuses models from another minor version.

AI tests use a tiny dataset and small forests, so they run in seconds:

```powershell
python -m pytest tests\unit\test_diagnostics_core.py tests\integration\test_ai_pipeline.py tests\integration\test_diagnostic_persistence.py tests\ui\test_ai_diagnostics.py
```

