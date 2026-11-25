# System requirements

## Packaged application (installer or portable ZIP)

| | Requirement |
|---|---|
| Operating system | Windows 10 or Windows 11, 64-bit (x64). Windows on ARM and 32-bit Windows are not supported. The installer refuses Windows versions older than 10. |
| Tested Windows versions | **None yet for the packaged build** — see [release-verification.md](release-verification.md). The source version has been run by the developer on Windows (version not recorded). |
| Disk space | About 500 MB for the application (measured size of the build is in the release notes) plus your data. |
| Memory | 4 GB RAM or more recommended; the application itself uses roughly 0.4 GB after start-up in measurements on Linux ([performance.md](performance.md)). |
| Display | 1280 × 720 or larger; high-DPI scaling supported by Qt. |
| Python | Not needed. |
| Internet | Not needed (only for downloading and for the optional documentation link). |
| Administrator rights | Not needed (per-user installation). |
| Offline voice | Uses the Windows speech engine (SAPI 5) and its installed voices; optional. |
| OBD-II (optional) | An ELM327-compatible adapter that appears as a COM port (USB or Bluetooth Classic). Physical adapters are **not yet verified**; Wi-Fi and BLE adapters are not supported. Simulation needs no hardware. |

## From source

* Windows 10/11 x64 with CPython **3.12** (3.12.10 used by the developer) from python.org.
* About 2 GB for the virtual environment with development tools.
* Optional: Inno Setup 6 to build the installer.

The automated test suite also runs on Ubuntu in CI. That is a development check, not Linux
support: Linux and macOS are not supported platforms for 2.0.0.
