# Licensing review

Engineering review of the licences that apply to the source code and to the Windows
distribution of SmartDrive Guardian AI 2.0.0. **This is not legal advice**; it records what was
checked and what remains open.

## Project licence

The repository has contained an MIT `LICENSE` (Copyright (c) 2026 Hiranya Bandara) since
Phase 1, and that decision is kept. Earlier planning documents recorded the choice as awaiting
the owner's confirmation; **confirming it is a release gate** (see
[release-checklist.md](release-checklist.md)). No other licence was considered or applied.

## Third-party components shipped in the Windows build

The full inventory with licence texts is generated from the lock file for Windows x64:
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) (repository) and the copy inside every
distribution. The CycloneDX SBOM lists the same 29 packages.

| Component | Licence | Obligations for this distribution | Status |
|---|---|---|---|
| Qt 6 / PySide6-Essentials / shiboken6 | LGPL-3.0 (chosen from LGPL/GPL options) | Provide licence text and notice; allow the user to replace the Qt libraries. The one-folder build keeps Qt as separate, unmodified DLLs in `_internal\PySide6`, which the user can replace; Qt's source is available from qt.io. No Qt code is modified or statically linked. | Satisfied by design; mention in notices ✔ |
| CPython 3.12 | PSF-2.0 | Include licence. | Listed in notices ✔ |
| PyInstaller bootloader | GPL-2.0-or-later with the Bootloader Exception | The exception allows distributing the frozen executable under the project's own licence. | ✔ |
| Inno Setup 6 | Inno Setup License | Free for commercial and non-commercial use; installers created with it may be distributed. Not part of the installed application. | ✔ |
| pyttsx3 | MPL-2.0 | File-level copyleft: distribute the licence; source of MPL files must be available (unmodified upstream on PyPI). | Listed; unmodified ✔ |
| NumPy, SciPy, scikit-learn, joblib, threadpoolctl, cloudpickle, MarkupSafe | BSD-3-Clause (NumPy also bundles 0BSD/MIT/Zlib/CC0 parts; SciPy and NumPy wheels bundle OpenBLAS/LAPACK runtime libraries under BSD-style licences) | Keep copyright notices. | Texts included as shipped in each wheel ✔ |
| pyqtgraph, SQLAlchemy, Alembic, Mako, Pydantic, pydantic-core, platformdirs, typing-inspection, annotated-types, narwhals, charset-normalizer, comtypes | MIT | Keep notices. | ✔ |
| ReportLab, pySerial, colorama | BSD | Keep notices. | ✔ |
| Pillow | MIT-CMU (HPND) | Keep notice. | ✔ |
| pywin32 (and the pypiwin32 shim) | PSF-style | Keep notice. | ✔ |
| typing-extensions | PSF-2.0 | Keep notice. | ✔ |

## Project assets

* **Logo, icons, installer artwork**: original, created for this project with
  `scripts/build_brand_assets.py` from hand-written SVG masters. No manufacturer logos or third
  party artwork. Not registered as trademarks.
* **Fonts**: none are bundled. The UI uses the operating system's fonts (Segoe UI on Windows).
  The wordmark in the logo images was rendered from DejaVu Sans (Bitstream Vera licence, which
  allows this use); no font file is distributed.
* **Models and datasets**: trained by this project on its own synthetic dataset; MIT.
* **Diagnostic trouble code descriptions**: about 123 generic SAE J2012 codes, described in the
  project's own words with a source note; manufacturer-specific meanings are not included.

## Open questions

1. Owner confirmation of the MIT licence (gate).
2. The DTC descriptions are paraphrases of commonly published generic definitions; a review by
   someone with access to SAE J2012 terms would confirm this is acceptable for redistribution.
3. If the project ever ships Qt statically linked or modified, the LGPL obligations change.
