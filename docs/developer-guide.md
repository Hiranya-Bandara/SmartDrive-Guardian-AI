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
smartdrive                         # or: python -m smartdrive / python main.py
smartdrive --home .\.smartdrive-home info   # isolated data folder for experiments (git-ignored)
```

## Tests

```powershell
python -m pytest                        # all tests
python -m pytest -m "not integration"   # unit tests only
python -m pytest --cov                  # with coverage
```

The autouse fixture in `tests/conftest.py` points `SMARTDRIVE_HOME` at a temporary folder, so
tests can never touch your real data.

## Database migrations

```powershell
$env:SMARTDRIVE_DB_URL = "sqlite:///$((Get-Location).Path -replace '\\','/')/.smartdrive-home/dev.db"
alembic upgrade head
# edit src\smartdrive\database\models.py, then:
alembic revision --autogenerate -m "add trip notes"
```

Review the generated file. Replace `smartdrive.database.types.UtcDateTime()` with `sa.DateTime()`
and run `python -m pytest tests/integration/test_migrations.py`.

## Updating dependencies

Edit `pyproject.toml`, then:

```powershell
python -m pip install uv
.\scripts\lock-dependencies.ps1
python -m pip install -r requirements-dev.txt
```
