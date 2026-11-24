# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 2.0.x (in development) | Yes |
| 1.x | No (separate, retired codebase) |

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private vulnerability reporting
(**Security → Report a vulnerability**) on the repository. Include the version, the steps to
reproduce and the potential impact. You can expect an acknowledgement within 7 days.

## Security and privacy design

- **Offline-first.** The application makes no network requests and collects no telemetry
  about its users.
- **Local data only.** The database, settings, logs and backups live in per-user OS folders,
  never in the installation folder or the repository.
- **Personal identifiers are optional.** VIN and registration number can be left blank or
  removed later. They are masked in log files by default.
- **Safe database access.** All queries go through SQLAlchemy with bound parameters, and
  foreign keys and constraints are enforced.
- **Restore validation.** A file is checked for the SQLite header, passes an integrity check and
  has a known schema revision before it can replace the live database. A safety backup is always
  taken first.
- **Export paths.** User-chosen export paths are resolved and validated: only allowed file
  types, in an existing folder, and never a directory.
- **Model files** (from Phase 3). Only bundled models whose SHA-256 hashes are recorded in the
  model registry will be loaded. Untrusted pickle/joblib files will never be deserialised.
- **Vehicle safety.** OBD-II access will be strictly read-only: no ECU writes, no actuator
  commands and no automatic clearing of trouble codes.
- **Dependencies** are pinned and audited with `pip-audit` in CI, and Dependabot proposes updates.
- **Secrets.** There are no credentials in the codebase. `.env` and key files are git-ignored.
