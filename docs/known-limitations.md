# Known limitations — version 2.0.0

## Diagnostics and AI

* **Synthetic training only.** The Random Forest classifier and Isolation Forest were trained and
  evaluated on the project's simulated dataset (324 sessions, 33,194 windows). The reported
  89.05 % subset accuracy and 86.06 % macro F1 are test-split results on that synthetic data.
  Accuracy on real vehicles is **unknown**.
* **Live machine learning is off by default** and experimental when enabled. Most vehicles do not
  report oil pressure over OBD-II, so the classifier abstains on almost all live data; rules and
  the anomaly detector still run.
* The health score is experimental and is withheld when data is insufficient.
* Rule thresholds are conservative simulation defaults, not manufacturer specifications.
* A trouble code or finding does not confirm a failed component. Only generic SAE J2012 codes are
  described; manufacturer-specific codes are listed without interpretation.
* No guarantee of breakdown prevention, failure prediction or safe vehicle operation.

## Vehicle hardware

* **Physical OBD-II adapters and vehicles are not verified.** All automated tests use a software
  mock adapter. See the [hardware checklist](hardware-verification-checklist.md).
* USB serial and Bluetooth Classic (COM port) adapters only; no Wi-Fi or BLE adapters.
* 19 standard parameters; no manufacturer-specific data, no GPS, route, fuel consumption or
  odometer reading. Trip distance is an estimate from speed.
* Strictly read-only: trouble codes cannot be cleared from the application (by design).

## Platform and packaging

* Windows 10/11 x64 only. Linux CI runs are development checks, not platform support.
* **The Windows executable and installer have not yet been built or tested on Windows by the
  project** at the time of writing; the PyInstaller configuration was validated with a Linux
  build. See [release-checklist.md](release-checklist.md).
* Not code-signed: SmartScreen warnings are expected; verify SHA-256 checksums.
* Desktop notifications and offline voice depend on Windows settings and installed SAPI 5
  voices, and have not been verified on the packaged build.
* The packaged application is large (hundreds of MB) because it contains Qt and the scientific
  Python stack.

## Data

* Data is stored unencrypted in the user's profile; protect the computer accordingly.
* Long recordings grow the database; old telemetry is removed after the retention period
  (365 days by default).
* Model integrity checks detect corruption, not a deliberate replacement of both the model and
  its manifest.

## Accessibility and UI

* Critical states use text and icons as well as colour, but a full screen-reader review has not
  been done.
* English only.
