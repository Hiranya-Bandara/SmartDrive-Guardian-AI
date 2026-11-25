# Contributing

## Branching model

| Branch | Purpose |
|---|---|
| `main` | Stable, released code only. Default branch. |
| `development` | Integration branch; every feature merges here first. |
| `feature/<area>` | One branch per roadmap area (for example `feature/desktop-ui`). Created only when work starts. |

1. Branch from `development`: `git switch development; git switch -c feature/desktop-ui`.
2. Commit in small, logical steps using Conventional Commits.
3. Run `.\scripts\check.ps1` before pushing.
4. Open a pull request into `development`. CI must pass.
5. Release merges from `development` into `main` happen only with the owner's approval and are tagged `vX.Y.Z`.

Never force-push, never rewrite published history, and never develop unfinished work on `main`.

## Commit messages

```text
feat: add interactive vehicle simulation laboratory
fix: handle vehicle connection timeouts
test: add automated diagnostic engine tests
docs: add application installation guide
build: configure Windows installer
chore: update pinned dependencies
```

## Code standards

- Python 3.12 with full type hints. `mypy` runs in strict mode on `src/`.
- `ruff check .` and `ruff format .` must be clean.
- Layering: the UI calls services, services call repositories and the core, and repositories own
  SQL. The UI never queries the database, trains models or communicates with the adapter.
- Raise subclasses of `SmartDriveError` for expected failures. Give each one a `user_message` that
  is safe to display.
- Never fabricate sensor values, model metrics, test results or hardware compatibility claims.
- Vehicle communication must stay read-only: no ECU writes, no actuator tests, no automatic DTC clearing.
- Do not log VINs, registration numbers or other personal data unredacted.

## Database changes

1. Edit `src/smartdrive/database/models.py`.
2. Generate a migration (see [docs/developer-guide.md](docs/developer-guide.md#database-migrations)).
3. Review it. Migrations must not import application code, so replace custom types with their
   plain SQLAlchemy equivalents.
4. `tests/integration/test_migrations.py` must pass. It checks that the migrated schema matches the models.

## Dependencies

Add the dependency to `pyproject.toml` in the phase that first uses it, then run
`.\scripts\lock-dependencies.ps1` and commit both requirements files.

## Releases

Releases are prepared on a `feature/*` branch, merged into `development`, verified as a release
candidate (the **Windows build** workflow and the manual checks in
`docs/release-verification.md`), then merged into `main` with the owner's approval. Only the
owner creates the version tag (`v2.0.0`); the **Release (draft)** workflow then builds and
verifies everything again and creates a draft pre-release, which the owner publishes by hand.
Never force-push, rewrite published history or publish from a feature branch. The full gate list
is in `docs/release-checklist.md`.

Pull requests that touch vehicle communication must keep `tests/unit/test_hardware_safety.py`
passing and must not add requests to the allowlist that write, clear, control or flash anything.
