# Build guide (Windows)

Builds the PyInstaller distribution, portable ZIP, installer, SBOM, notices and checksums on a
Windows 10/11 x64 computer. All commands are PowerShell, run from the repository folder; paths
with spaces are fine (the project itself lives in `E:\3rd Year\...` on the developer's machine).

## Prerequisites (once)

* CPython 3.12 x64 from python.org, with the `py` launcher.
* Inno Setup 6 from <https://jrsoftware.org/isinfo.php> (free), default installation folder.
* The project's virtual environment with development **and** release tools:

  ```powershell
  cd "E:\3rd Year\SmartDrive-Guardian-AI-Phase1\SmartDrive-Guardian-AI"
  .\.venv\Scripts\Activate.ps1
  python -m pip install -r requirements-dev.txt -r requirements-release.txt
  python -m pip install --no-deps -e .
  python -m pip check
  ```

  (A new clone can use `.\scripts\setup-dev.ps1 -Release` instead.)

If PowerShell refuses to run scripts, allow them for this session only:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

## Build

```powershell
.\scripts\build-windows.ps1        # checks, PyInstaller, validation, smoke test, portable ZIP
.\scripts\build-installer.ps1      # Inno Setup installer
.\scripts\test-installer.ps1       # silent install, smoke test, reinstall, uninstall (per-user)
.\scripts\generate-checksums.ps1   # SBOM, notices, RELEASE_NOTES, BUILD_INFORMATION, SHA256SUMS
.\scripts\verify-release.ps1       # verifies everything in release\
```

`build-windows.ps1 -SkipChecks` skips Ruff, Mypy and Pytest when they have just been run.
Every step stops on the first failure; nothing is skipped silently.

Results:

```text
dist\SmartDrive-Guardian-AI\                      one-folder build (tested by smoke-test.ps1)
release\SmartDrive-Guardian-AI-Windows-x64.zip
release\SmartDrive-Guardian-AI-Setup-v2.0.0.exe
release\SmartDrive-Guardian-AI-v2.0.0-sbom.json
release\THIRD_PARTY_NOTICES.md, RELEASE_NOTES.md, BUILD_INFORMATION.json, SHA256SUMS.txt
build\smoke-test\self-test.json, build\installer-test\*.log, build\windows-version-info.txt
```

The scripts delete only `build\pyinstaller`, `dist\SmartDrive-Guardian-AI` and files they
replace in `release\`; they refuse to delete anything outside `build\`, `dist\` and `release\`.
These folders are git-ignored.

## Inspect the artifacts

```powershell
Get-ChildItem .\release | Format-Table Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
(Get-Item .\dist\SmartDrive-Guardian-AI\SmartDrive-Guardian-AI.exe).VersionInfo | Format-List ProductName, ProductVersion, FileVersion, LegalCopyright
Get-AuthenticodeSignature .\release\SmartDrive-Guardian-AI-Setup-v2.0.0.exe   # NotSigned expected
Get-FileHash .\release\* -Algorithm SHA256
Get-Content .\build\smoke-test\self-test.json
```

## Smoke-test any executable

```powershell
.\scripts\smoke-test.ps1 -Executable "$env:LOCALAPPDATA\Programs\SmartDrive Guardian AI\SmartDrive-Guardian-AI.exe"
```

## In GitHub Actions

`.github/workflows/windows-build.yml` runs the same five scripts on `windows-latest` (manually,
or for pushes and pull requests to `development` and `main`) and uploads `release\` as the
artifact `smartdrive-windows-release-candidate` (kept 30 days) and the logs (14 days). It
installs Inno Setup from Chocolatey when the runner image does not have it.
`.github/workflows/release.yml` repeats this for a version tag and creates a **draft
pre-release**; publishing it is a manual step on GitHub.

## Troubleshooting builds

* *"Python module 'PyInstaller' is missing"*: install `requirements-release.txt` into `.venv`.
* *"64-bit CPython 3.12 is required"*: recreate `.venv` with `py -3.12 -m venv .venv`.
* *Smoke test fails with a missing module*: add it to `hiddenimports` in
  `packaging\smartdrive.spec`, rebuild, and keep the self-test report for the issue.
* *ISCC.exe not found*: install Inno Setup 6 or pass `-Iscc "C:\path\to\ISCC.exe"`.
* *Antivirus quarantines the build*: unsigned PyInstaller executables are sometimes flagged by
  heuristics. Report the false positive to the vendor; do not disable protection.
