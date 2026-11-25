# Release checklist — SmartDrive Guardian AI 2.0.0

Status of every release gate, with the evidence behind it. Results are separated by execution
environment: **sandbox** = the isolated Linux development container used for Phase 5 (Python
3.12.3, Qt `offscreen`); **Windows** = the owner's computer or the GitHub-hosted Windows runner.
A gate is ✔ only when it was actually executed and passed.

## Automated results — sandbox (Linux), 25 November 2026

| Check | Result |
|---|---|
| Python / dependency consistency | CPython 3.12.3 · `pip check`: no broken requirements (dev + release locks installed together) |
| Ruff lint / format | All checks passed · all files formatted |
| Mypy (strict) | No issues in 155 source files; also clean with `--platform win32` and comtypes 1.5.0 installed (the Windows `voice.py` fix) |
| Pytest | **643 collected · 643 passed · 0 failed · 0 skipped · 0 errors** in 514 s (331 unit, 188 integration, 112 GUI, 12 end-to-end) |
| Coverage (line + branch) | **91 %** (16,987 statements) |
| Installation self-test (source) | 13 / 13 checks passed |
| PyInstaller build (Linux, same spec) | Built; frozen self-test 13 / 13 from a path with spaces without the virtual environment; frozen GUI started and exited with code 0, no errors logged |
| SBOM | CycloneDX 1.6, 29 Windows runtime components, schema-valid |
| Dependency audit (pip-audit 2.10.1) | 0 known vulnerabilities in runtime (26 + 3 Windows-only), dev (70) and release (63) packages |
| GitHub workflows | actionlint 1.7.12: no problems (not executed on GitHub) |
| Performance | [performance.md](performance.md) (20-minute sustained run) |

## Windows results

| Check | Status |
|---|---|
| Source: `scripts\check.ps1` on the owner's computer | ⏳ PENDING (Phase 4: owner reported Ruff/format/Mypy passing after the `voice.py` fix and a successful launch; exact pytest output not supplied) |
| GitHub Actions `ci.yml` on `windows-latest` | ⏳ PENDING — not yet run (workflows validated with actionlint only) |
| PyInstaller build (`build-windows.ps1`) | ⏳ PENDING |
| Packaged smoke test (`smoke-test.ps1`) | ⏳ PENDING |
| Installer compile (`build-installer.ps1`) | ⏳ PENDING |
| Automated installer test (`test-installer.ps1`) | ⏳ PENDING |
| Manual verification ([release-verification.md](release-verification.md)) | ⏳ PENDING — all items |
| Windows versions tested | None yet |
| Performance on Windows (`scripts\benchmark.py`) | ⏳ PENDING |

## Release gates

| Gate | Status | Evidence |
|---|---|---|
| Source quality checks pass (Ruff, format, Mypy strict, pip check) | ✔ sandbox · ⏳ Windows | Results above |
| Existing meaningful tests pass | ✔ sandbox · ⏳ Windows | Results above |
| Critical regression tests pass (lifecycle, COM, allowlist, migrations, shutdown) | ✔ sandbox | `tests/unit/test_release_regressions.py`, `test_hardware_safety.py`, `test_voice_backend.py`, `tests/e2e` |
| No unresolved blocking defects | ✔ none known | Defects found in Phase 5 were fixed (see CHANGELOG) |
| Windows distribution built | ⏳ | — |
| Windows distribution smoke-tested | ⏳ (Linux frozen build of the same spec passed the self-test and GUI start) | [packaging.md](packaging.md) |
| Installer built | ⏳ | — |
| Installer verified (automated + manual) | ⏳ | — |
| Licence notices included | ✔ | `THIRD_PARTY_NOTICES.md` (29 runtime packages + non-Python components), copied into every build by `build-windows.ps1` |
| Security limitations documented | ✔ | [security-review.md](security-review.md), [SECURITY.md](../SECURITY.md) |
| Privacy behaviour documented | ✔ | [PRIVACY.md](../PRIVACY.md) |
| AI limitations documented | ✔ | README, About page, welcome guide, [known-limitations.md](known-limitations.md), model card |
| Hardware limitations documented | ✔ | [hardware.md](hardware.md), [hardware-verification-checklist.md](hardware-verification-checklist.md) |
| Release checksums generated | ⏳ (script ready; requires the built artifacts) | `generate-checksums.ps1` |
| Documentation matches the software | ✔ sandbox review | — |
| Owner confirms MIT licence | ⏳ owner decision | [licensing.md](licensing.md) |
| **Owner approves public publication** | ⏳ owner decision | — |

**Readiness assessment.** The source release is complete and verified in the sandbox. Version
2.0.0 is **not ready for public release** until the Windows build, smoke test and installer have
been run and verified and the owner has approved publication. Recommended designation once those
pass: **pre-release** (physical OBD-II hardware unverified; models trained on synthetic data).
Physical vehicle testing is a separate track and is not a gate for the software release.

## Release procedure (owner, after review)

```powershell
cd "E:\3rd Year\SmartDrive-Guardian-AI-Phase1\SmartDrive-Guardian-AI"
git switch feature/professional-release
git status
# 1. Commit (after copying the Phase 5 files in, see the completion report)
git add -A
git commit -m "chore: prepare SmartDrive Guardian AI v2.0.0 release"
# 2. Push the feature branch (approval required)
git push origin feature/professional-release
# 3. On GitHub: check "CI" and run "Windows build" (Actions → Windows build → Run workflow on
#    feature/professional-release); download the release-candidate artifact and verify it.
# 4. Pull request feature/professional-release → development; merge after review.
# 5. Pull request development → main; merge only after explicit approval.
# 6. Tag on main (approval required):
git switch main
git pull --ff-only
git tag -a v2.0.0 -m "SmartDrive Guardian AI 2.0.0"
git push origin v2.0.0
# 7. "Release (draft)" workflow builds, verifies and creates a draft pre-release
#    (approve the 'release' environment when asked). Review it, then publish on GitHub.
```
