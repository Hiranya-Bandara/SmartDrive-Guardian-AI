# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 2.0.x | Yes (security fixes) |
| Earlier 2.0 development builds | No — upgrade to the latest 2.0.x |
| 1.x | No (separate, retired codebase) |

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private vulnerability reporting on the
repository (**Security → Report a vulnerability**,
<https://github.com/Hiranya-Bandara/SmartDrive-Guardian-AI/security/advisories/new>). If that is
not available, open an issue that asks the maintainer to contact you, without any details of the
problem. Include the version, the steps to reproduce and the potential impact. This is a
one-person project: expect an acknowledgement within 7 days and no guaranteed fix time.

Reports about vehicle safety (anything that could send a non-read-only request to a vehicle)
are treated as the highest priority.

## Verifying downloads

Release artifacts are **not code-signed**. Compare the SHA-256 checksum of each download with
`SHA256SUMS.txt` on the GitHub release page:

```powershell
Get-FileHash .\SmartDrive-Guardian-AI-Setup-v2.0.0.exe -Algorithm SHA256
```

A matching checksum shows the file is the one published; it does not prove who published it in
the way a code signature would. See [docs/installation.md](docs/installation.md).

## Security and privacy design (summary)

- **Offline.** The application contains no network code and collects no usage data.
- **Read-only vehicle access.** A closed allowlist of 65 requests, enforced in the OBD client and
  again on the raw bytes at the serial boundary. No clearing of trouble codes, no ECU writes,
  actuator control, flashing, security access or user-typed commands. Never connects on its own.
- **Local data only**, in per-user folders, never in the installation folder.
- **Identifiers** (VIN, registration) are optional, masked in logs and left out of reports by
  default.
- **Bundled models only**, loaded after a SHA-256 check against the manifest. This detects
  corruption, not a deliberate replacement of both files (see the review).
- **Database**: bound parameters, enforced foreign keys, validated restores with a safety backup.
- **Exports**: user-chosen locations, atomic writes, CSV formula-injection protection.
- **Installer**: per-user, no administrator rights, no services, drivers or startup entries;
  user data is preserved on upgrade and uninstall.
- **Supply chain**: pinned dependencies audited with pip-audit in CI, Dependabot updates, GitHub
  Actions pinned to commit SHAs with least-privilege tokens, CycloneDX SBOM per release.

The full threat model, findings and residual risks are in
[docs/security-review.md](docs/security-review.md).
