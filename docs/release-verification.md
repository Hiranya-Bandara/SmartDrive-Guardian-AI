# Release verification (manual, Windows)

Checks that need a real Windows computer and a person. Automated results are recorded in
[release-checklist.md](release-checklist.md); physical vehicle checks are in
[hardware-verification-checklist.md](hardware-verification-checklist.md) and are **not**
required for the software release.

**Status legend:** PENDING = not yet performed · PASS / FAIL = performed, with date, Windows
version and tester initials in the Notes column. Every item below is PENDING until someone runs
it; no result has been filled in on anyone's behalf.

Record the environment for each session:

| Field | Value |
|---|---|
| Date | |
| Windows edition, version, build (`winver`) | |
| Account type (standard / administrator) | |
| Display scaling | |
| Build tested (version, `BUILD_INFORMATION.json` commit) | |

## A. Source installation

| # | Check | Status | Notes |
|---|---|---|---|
| A1 | `scripts\setup-dev.ps1` completes in a fresh clone (or existing `.venv` updated per build guide); `pip check` clean | PENDING | |
| A2 | `scripts\check.ps1` (Ruff, format, Mypy, Pytest) passes on Windows; record counts | PENDING | |
| A3 | `smartdrive gui` starts; welcome guide appears once | PENDING | |

## B. Application (installed build)

| # | Check | Status | Notes |
|---|---|---|---|
| B1 | Start from the Start Menu; dashboard appears; window icon and taskbar icon show the shield | PENDING | |
| B2 | Welcome guide: shown on first start, not again after "Get started"; reopened from About | PENDING | |
| B3 | Simulation Lab: run Normal, Overheating, Electrical and Missing sensors scenarios; values labelled simulated | PENDING | |
| B4 | Dashboard/Live Monitoring: gauges and charts update; pause/resume; source banner | PENDING | |
| B5 | AI Diagnostics: findings, experimental health score (or withheld when data insufficient), explanations chart, model status | PENDING | |
| B6 | Garage: add/edit vehicle with photo; remove identifiers | PENDING | |
| B7 | Trip recording during simulation; Trip History shows summary and timeline | PENDING | |
| B8 | Replay: play, pause, seek, 0.5×/1×/2×/4×, stop; no new trip created | PENDING | |
| B9 | Maintenance: record, schedule, reminder state, odometer, costs per currency | PENDING | |
| B10 | Reports: each PDF type opens in a PDF reader; CSV opens in Excel without formula warnings | PENDING | |
| B11 | Alert Centre: notifications, acknowledgement, unread count in sidebar | PENDING | |
| B12 | Desktop notification appears (Windows notification settings permitting) | PENDING | |
| B13 | Voice: Settings → Test voice speaks with a SAPI 5 voice; announcements respect the setting | PENDING | |
| B14 | Themes: dark, light and system (switch Windows theme while running) | PENDING | |
| B15 | Vehicle Connection without adapter: ports listed, nothing connects on its own; a wrong port times out with a clear message | PENDING | Owner reported earlier (source build, Phase 4): COM9 timeout handled; nine Bluetooth ports listed. Re-check on the packaged build. |
| B16 | Restart: vehicles, trips, settings and theme persist | PENDING | |
| B17 | Backup and restore (Settings → Database), including a restore of a pre-upgrade backup | PENDING | |
| B18 | Close during monitoring, recording, replay, report generation and speech: exits within a few seconds, no error dialog; trip is closed | PENDING | |
| B19 | Keyboard navigation: Ctrl+1…9/0, Ctrl+Shift+T/M/R, Tab order on dialogs | PENDING | |
| B20 | 125 % and 150 % display scaling; 1366 × 768 laptop screen (sidebar collapsed) | PENDING | |
| B21 | Log written to `%LOCALAPPDATA%\SmartDriveGuardianAI\SmartDriveGuardianAI\Logs` without VIN/registration | PENDING | |

## C. Packaged executable and portable ZIP

| # | Check | Status | Notes |
|---|---|---|---|
| C1 | `scripts\build-windows.ps1` completes (includes automated smoke test) | PENDING | |
| C2 | Portable ZIP extracted to a folder with spaces runs on a computer **without Python** | PENDING | |
| C3 | `self-test --report` passes on that computer | PENDING | |
| C4 | No missing DLL or "could not load the Qt platform plugin" error | PENDING | |
| C5 | File properties show product name, version 2.0.0, copyright | PENDING | |

## D. Installer

| # | Check | Status | Notes |
|---|---|---|---|
| D1 | `scripts\build-installer.ps1` compiles the installer | PENDING | |
| D2 | `scripts\test-installer.ps1` passes (silent install, smoke test, reinstall with data preserved, uninstall) | PENDING | |
| D3 | Interactive install as a **standard user**: no UAC prompt, licence and notice pages, folder with spaces, desktop shortcut option, launch at the end | PENDING | |
| D4 | Start Menu and desktop shortcuts start the application | PENDING | |
| D5 | Upgrade over an existing installation with data: data kept; older database backed up and migrated | PENDING | |
| D6 | Install while the application is running: Setup offers to close it (Restart Manager) | PENDING | |
| D7 | Uninstall: program files and shortcuts removed, message shows data folder, data kept | PENDING | |
| D8 | Reinstall after uninstall: previous data opens | PENDING | |
| D9 | All-users installation via the privileges dialog (UAC expected) | PENDING | |
| D10 | SmartScreen warning text noted; checksum verification instructions work | PENDING | |

## E. Release artifacts

| # | Check | Status | Notes |
|---|---|---|---|
| E1 | `scripts\generate-checksums.ps1` then `scripts\verify-release.ps1` pass | PENDING | |
| E2 | `Get-FileHash` of each artifact matches `SHA256SUMS.txt` after download from the draft release | PENDING | |
| E3 | SBOM lists 29 runtime packages for Windows; notices included in the ZIP and installation | PENDING | |
