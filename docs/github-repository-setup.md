# GitHub repository presentation (suggestions)

These settings are for the repository owner to apply by hand. Nothing here has been changed
on GitHub.

## About panel

* **Description:** An offline-first AI-powered vehicle diagnostics and maintenance desktop
  application featuring hybrid machine learning, read-only OBD-II integration, telemetry
  monitoring, trip replay and professional reporting.
* **Website:** leave empty until there is a release page to link.
* **Topics:** `python`, `pyside6`, `desktop-application`, `machine-learning`,
  `artificial-intelligence`, `random-forest`, `isolation-forest`, `explainable-ai`, `obd2`,
  `elm327`, `vehicle-diagnostics`, `automotive`, `predictive-maintenance`, `sqlite`,
  `sqlalchemy`, `pyinstaller`, `windows`, `github-actions`.
* **Social preview:** Settings → General → Social preview → upload
  `docs/branding/social-preview.png` (1280 × 640).

## Settings worth enabling

* **Private vulnerability reporting** (Settings → Code security) — `SECURITY.md` refers to it.
* **Dependabot alerts and security updates** (`.github/dependabot.yml` already proposes updates
  to `development`).
* **Branch protection** for `main` and `development`: require pull requests and the CI checks
  "Lint, types and tests (windows-latest)" and "Dependency vulnerability audit"; no force
  pushes.
* **Environment `release`** (Settings → Environments) with yourself as required reviewer; the
  release workflow's draft-creation job waits for this approval.
* **Actions → General → Workflow permissions:** "Read repository contents" (the workflows
  request write access only where needed).

## Repository hygiene review (Phase 5)

* `.gitignore` excludes virtual environments, databases, logs, settings, caches, `build/`,
  `dist/`, `release/` and generated datasets. The source archive was checked for these.
* Large binary files in Git: the two model artifacts (≈ 5.5 MB together) and screenshots, both
  needed by the application or documentation. Release binaries (executable, installer, ZIP) are
  never committed; they belong on the GitHub Releases page.
* Earlier commits were not inspected from this environment (it has no access to the
  repository's history). Before publishing, run `git log --all --stat` and a secret scanner
  such as `gitleaks detect` locally; if anything sensitive is found, do **not** rewrite history
  without a plan — rotate the secret first, then decide with the owner.
