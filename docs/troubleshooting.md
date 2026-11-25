# Troubleshooting

Start with the self-test, which checks the installation with simulated data in a temporary
folder:

```powershell
$exe = "$env:LOCALAPPDATA\Programs\SmartDrive Guardian AI\SmartDrive-Guardian-AI.exe"
Start-Process -FilePath $exe -ArgumentList 'self-test', '--report', "`"$env:TEMP\st.json`"" -Wait -NoNewWindow
Get-Content "$env:TEMP\st.json"
```

Maintenance commands run the same way, for example
`Start-Process -FilePath $exe -ArgumentList 'db', 'check' -Wait -NoNewWindow`.

The log file is `%LOCALAPPDATA%\SmartDriveGuardianAI\SmartDriveGuardianAI\Logs\smartdrive.log`
(also shown on the About page). Include the relevant lines — without vehicle identifiers — when
reporting a problem.

| Symptom | What to do |
|---|---|
| SmartScreen: "Windows protected your PC" | The installer is unsigned. Verify the SHA-256 checksum ([installation.md](installation.md)); if it matches, choose More info → Run anyway. |
| Antivirus removes the program | Unsigned PyInstaller programs are sometimes flagged by heuristics. Verify the checksum, restore the file from quarantine and report the false positive to the vendor. Do not turn protection off. |
| The program does not start, nothing appears | Run the self-test above. For the portable ZIP, make sure `_internal` is next to the executable and the ZIP was extracted (not run from inside the archive). |
| "The application data folder could not be created" | The folder is not writable (policy, full disk). Start with `--home "<writable folder>"`. |
| The database could not be opened or upgraded | The previous database was saved in `backups\smartdrive-pre-upgrade-*.db` before an upgrade. The `db check` command checks integrity and `db restore <file>` restores a backup (a safety copy is taken first); run them with `Start-Process ... -Wait -NoNewWindow` as above. |
| AI Diagnostics says the models are unavailable / integrity failed | The bundled model files are damaged or modified. Reinstall. Rule-based diagnostics keep working. |
| Machine-learning shows "not assessed" on live data | Expected: experimental live ML is off by default, and the models abstain when the vehicle does not report sensors they were trained with (most cars report no oil pressure). |
| No COM port is listed | Pair the Bluetooth adapter in Windows first (it then appears as "Standard Serial over Bluetooth link"), or plug in the USB adapter and install its driver. Press Refresh. |
| Several Bluetooth COM ports are listed | Windows creates incoming and outgoing ports. Choose the **outgoing** port of the adapter (Bluetooth settings → More Bluetooth options → COM Ports). |
| Connection fails with a timeout (for example on COM9) | The port did not answer like an ELM327 adapter: wrong port, adapter not powered (ignition on), or another program is using it. Try the other COM port of the pair. The application never retries a port you did not choose. Physical adapters are not yet verified — please report results with the [hardware checklist](hardware-verification-checklist.md). |
| Adapter connects but the vehicle ECU does not | Turn the ignition on (engine running is not required for most readings); some vehicles need a moment after the ignition is switched on. |
| Some readings show "Not supported" | The vehicle does not report that parameter. Values are never invented. |
| Voice announcements are silent | Voice is optional and off by default (Settings → Notifications and voice). Use Test voice; install a Windows voice if none is listed. |
| No desktop notifications | Check Windows notification settings and Focus Assist; in-app notifications and the Alert Centre still work. |
| Text is too small or cut off | Use Windows display scaling; the sidebar can be collapsed (button at the bottom). |
| A report cannot be saved | Choose a folder you can write to; existing files are replaced only after you confirm. |
