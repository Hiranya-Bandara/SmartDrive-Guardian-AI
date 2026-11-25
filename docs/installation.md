# Installation guide

Three ways to run SmartDrive Guardian AI 2.0.0. The packaged downloads exist only once a GitHub
release has been published; until then use the source installation or build them yourself
([build-guide.md](build-guide.md)).

> Read first: educational software, not a certified diagnostic or safety system. Models were
> trained on simulated data only. OBD-II access is read-only and physical adapters are not yet
> verified. Do not use the application while driving.

## 1. Installer (recommended)

1. Download `SmartDrive-Guardian-AI-Setup-v2.0.0.exe` and `SHA256SUMS.txt` from the GitHub
   release.
2. Check the download (PowerShell, in your Downloads folder):

   ```powershell
   Get-FileHash .\SmartDrive-Guardian-AI-Setup-v2.0.0.exe -Algorithm SHA256
   Select-String -Path .\SHA256SUMS.txt -Pattern 'Setup-v2.0.0.exe'
   ```

   The two hashes must be identical (letter case does not matter). If they differ, delete the
   file and download it again.
3. Run the installer. Because it is **not code-signed**, Windows SmartScreen may show "Windows
   protected your PC". Only if the checksum matched, choose **More info → Run anyway**. Do not
   disable SmartScreen or your antivirus.
4. Follow the wizard. By default it installs for your user only, into
   `%LOCALAPPDATA%\Programs\SmartDrive Guardian AI`, without administrator rights. You can
   choose another folder, a desktop shortcut and whether to launch the application at the end.

**Upgrading:** run the newer installer; your data is kept. A database from an older version is
backed up automatically before it is upgraded (`backups\smartdrive-pre-upgrade-*.db`).

**Uninstalling:** Settings → Apps → SmartDrive Guardian AI → Uninstall (or Start Menu). Program
files and shortcuts are removed; **your data is kept**. To remove it too, delete
`%LOCALAPPDATA%\SmartDriveGuardianAI` afterwards.

## 2. Portable ZIP

1. Download `SmartDrive-Guardian-AI-Windows-x64.zip` and verify it as above.
2. Extract it (right-click → Extract All). Keep the `_internal` folder next to the executable.
3. Run `SmartDrive-Guardian-AI\SmartDrive-Guardian-AI.exe`.

Data goes to the same per-user folder as the installed version. To keep it next to the program
instead, start it with `--home ".\data"` (for example from a shortcut).

## 3. From source (developers)

Requires CPython 3.12 x64 and Git.

```powershell
git clone https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI.git
cd SmartDrive-Guardian-AI
powershell -ExecutionPolicy Bypass -File .\scripts\setup-dev.ps1
.\.venv\Scripts\Activate.ps1
smartdrive gui
```

## Check an installation

```powershell
$exe = "$env:LOCALAPPDATA\Programs\SmartDrive Guardian AI\SmartDrive-Guardian-AI.exe"
Start-Process -FilePath $exe -ArgumentList 'self-test', '--report', "`"$env:TEMP\st.json`"" -Wait -NoNewWindow
Get-Content "$env:TEMP\st.json"
```

The self-test uses a temporary folder and simulated data; it never touches your own data. The
executable is a windowed program, so PowerShell would not wait for it without `Start-Process
-Wait`; other commands (`info`, `db check`) print to the console they are started from in the
same way.

## First start

The welcome guide explains simulation and live modes, the limits of the AI findings and where
data is kept. Start in **Simulation Lab** — no hardware is needed. See the
[user guide](user-guide.md).
