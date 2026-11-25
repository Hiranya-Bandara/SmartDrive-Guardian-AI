SmartDrive Guardian AI - portable Windows distribution
======================================================

Start the application by double-clicking SmartDrive-Guardian-AI.exe in this folder. Keep the
_internal folder next to it: the program needs the files inside it. No installation and no
Python are needed.

Requirements: Windows 10 or 11, 64-bit. Tested Windows versions are listed in the release notes.

Where your data is kept
  %LOCALAPPDATA%\SmartDriveGuardianAI\SmartDriveGuardianAI   (database, settings, logs, backups)
  Exported reports go where you choose (default: Documents\SmartDriveGuardianAI).
Deleting this folder removes the program but not your data.

To keep all data next to the program instead (for example on a USB drive), start it with:
  SmartDrive-Guardian-AI.exe --home ".\data"

Check this copy
  Start-Process .\SmartDrive-Guardian-AI.exe -ArgumentList 'self-test','--report','self-test.json' -Wait -NoNewWindow
(PowerShell, in this folder) runs a self-check with simulated data in a temporary folder and
writes the results to self-test.json.

Important
  * Educational software, not a certified diagnostic or safety system.
  * The machine-learning models were trained on simulated data only.
  * OBD-II access is read-only; physical adapters and vehicles are not yet verified.
  * Do not use the application while driving.
  * The executable is not code-signed. Compare its SHA-256 checksum with SHA256SUMS.txt from
    the official GitHub release:  Get-FileHash .\SmartDrive-Guardian-AI-Windows-x64.zip -Algorithm SHA256

Licences: LICENSE.txt (MIT) and THIRD_PARTY_NOTICES.md.
Source code and issue tracker: https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI
