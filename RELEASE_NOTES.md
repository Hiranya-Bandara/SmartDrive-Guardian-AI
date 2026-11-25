# SmartDrive Guardian AI 2.0.0 — Intelligent Vehicle Diagnostics

*Intelligent Diagnostics. Smarter Maintenance.*

SmartDrive Guardian AI is an offline-first Windows desktop application for **educational**
vehicle diagnostics and maintenance: real-time telemetry monitoring, a hybrid rule-based and
machine-learning diagnostic engine with explanations, strictly read-only OBD-II access, trip
recording and replay, a maintenance centre and professional PDF/CSV reports.

> **Pre-release.** This release is recommended as a GitHub *pre-release*: the software is
> complete and tested on the development side, but vehicle hardware has not been verified and
> the machine-learning models were trained on simulated data only. It is not a certified
> automotive diagnostic or safety system. Do not use it while driving.

## Highlights

**AI diagnostics**
- Seven transparent rules plus a Random Forest fault classifier and an Isolation Forest anomaly
  detector over 96 features from 60-second telemetry windows.
- Tree-path explanations for every prediction, an experimental health score with itemised
  deductions, abstention on stale, incomplete or out-of-distribution data.
- Rules are never overridden by a model; model-only findings are capped at "warning".
- Synthetic test-split results: 89.05 % subset accuracy, 86.06 % macro F1 (324 simulated
  sessions). **These say nothing about accuracy on real vehicles.**

**Desktop interface**
- 13 pages: Dashboard, Live Monitoring, AI Diagnostics, Vehicle Connection, Diagnostic Codes,
  Garage, Simulation Lab, Trip History, Maintenance, Reports, Alert Centre, Settings, About.
- Dark, light and system themes; keyboard shortcuts; background workers keep the interface
  responsive; first-run guide.

**Vehicle integration (read-only, experimental)**
- In-house ELM327 client for USB and Bluetooth (COM port) adapters; 19 standard parameters;
  stored, pending and permanent trouble codes, MIL and freeze frame.
- A closed allowlist of 65 read-only requests, enforced twice (client and raw serial bytes). No
  clearing of codes, no ECU writes, actuator control, flashing or security access, no typed
  commands, and no automatic connection to any port.
- **Tested only with a software mock adapter.** Physical adapters and vehicles are unverified.

**Trips, maintenance, reports, notifications**
- Trip recording with summaries, estimated distance and diagnostic timelines; replay at
  0.5–4× with seek (never stored).
- Maintenance records, user-defined schedules and reminders, odometer readings, costs per
  currency.
- Seven PDF report types and eight CSV datasets; identifiers excluded by default; CSV
  formula-injection protection.
- Alert Centre with de-duplication and acknowledgement; optional Windows desktop notifications
  and offline voice (SAPI 5).

**Privacy and security**
- No account, no internet requirement, no telemetry or analytics; data stays in
  `%LOCALAPPDATA%\SmartDriveGuardianAI` and is kept on upgrade and uninstall.
- Trusted, checksum-verified model files only; pinned and audited dependencies; CycloneDX SBOM.

## Downloads

| File | Purpose |
|---|---|
| `SmartDrive-Guardian-AI-Setup-v2.0.0.exe` | Installer (per-user, no administrator rights) |
| `SmartDrive-Guardian-AI-Windows-x64.zip` | Portable version (extract and run) |
| `SHA256SUMS.txt` | Checksums of all files |
| `SmartDrive-Guardian-AI-v2.0.0-sbom.json` | Software bill of materials (CycloneDX 1.6) |
| `THIRD_PARTY_NOTICES.md` | Third-party licences |
| `BUILD_INFORMATION.json` | Build environment, commit, model versions |

The files are **not code-signed**. Windows SmartScreen may warn about an unknown publisher.
Verify the checksum before running:

```powershell
Get-FileHash .\SmartDrive-Guardian-AI-Setup-v2.0.0.exe -Algorithm SHA256
```

and compare it with `SHA256SUMS.txt`. Installation guide:
[docs/installation.md](https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI/blob/main/docs/installation.md).

## Supported platform

Windows 10 and 11, 64-bit. Windows versions on which the packaged build was tested are listed
in `docs/release-checklist.md` in the tagged source.

## Known limitations

- Physical OBD-II hardware not verified; Wi-Fi/BLE adapters unsupported.
- Models trained on synthetic data; experimental live ML is off by default and usually abstains
  (most vehicles do not report oil pressure).
- No GPS, route, fuel-consumption or odometer data from the vehicle; distance is estimated.
- Unsigned binaries; English only.

Full list: [docs/known-limitations.md](https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI/blob/main/docs/known-limitations.md).
Changes: [CHANGELOG.md](https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI/blob/main/CHANGELOG.md).

Developed by Hiranya Bandara · MIT License.
