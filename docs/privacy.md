# Data privacy

SmartDrive Guardian AI is offline-first. It has no account, no cloud service, no analytics or
telemetry collection and no advertising SDK, and it never uploads anything.

## What is stored, and where

Everything is stored locally in the application's data folder (shown in **Settings →
Database**), mainly in the SQLite database `smartdrive.db`:

| Data | Contains | Notes |
|---|---|---|
| Vehicles | Name, make, model, year, odometer, optional registration number, VIN, notes and photo | Registration and VIN are optional and can be erased from the garage ("Remove identifiers"). |
| Trips | Start/end time, data source, telemetry samples, statistics, diagnostic timeline | No GPS position, route or address is recorded. Distance is an estimate from speed. |
| Diagnostic history and alerts | Findings, health scores, model versions, evidence values | |
| OBD-II connections | Port name, adapter version, protocol, supported parameters, sample count | The VIN is never read (mode 09 is blocked). |
| Trouble codes | Codes, scan times, freeze-frame values | |
| Maintenance | Records, costs, providers, notes, schedules, odometer readings | |
| Notifications | Titles, messages, read/acknowledged times | Read notifications are removed after the retention period. |
| Export history | File names and locations of reports you created | |

`settings.json` holds preferences. The log file records technical events; vehicle identifiers
are redacted by default (**Settings → Data and privacy**).

Stored trips can reveal when a vehicle was used. Protect the computer accordingly, and keep
backups somewhere private.

## Reports and exports

- Registration number, VIN and the vehicle's garage notes are **left out of reports** unless
  you include them for a specific report or in Settings.
- Notes on maintenance records are never included in reports or CSV exports.
- PDF metadata contains only the report title, "SmartDrive Guardian AI" and the version; no
  user name, computer name or file path.
- CSV exports contain the data you selected. Check them before sharing.

## Voice and desktop notifications

Announcements and desktop notifications contain only the finding or reminder title, never
vehicle identifiers. Desktop notifications are shown by the operating system and may appear on
the lock screen depending on Windows settings.

## Deleting your data

- **Trip:** Trip History → Delete trip (removes its telemetry, summary and timeline).
- **Vehicle:** Garage → Delete (removes the vehicle and its trips, trouble codes, maintenance,
  thresholds, notifications and diagnostic history). Adapter connection history and export
  history are kept without the link to the vehicle.
- **Identifiers:** Garage → Remove identifiers.
- **Old telemetry:** Settings → Data and privacy → retention period.
- **Everything:** close the application and delete the data folder.
