# Real-hardware verification checklist

Use this checklist to verify SmartDrive Guardian AI with a physical ELM327-compatible adapter
and a real vehicle. Until each item is completed with recorded evidence, physical hardware
support is **unverified**. Automated tests use a mock adapter and do not count as evidence.

**Overall status: PENDING — no physical adapter or vehicle has been tested.**

Owner observation (Windows, source build, after Phase 4 — not a checklist result): PySerial
listed nine Bluetooth serial ports; none was confirmed to be an OBD-II adapter. A connection
attempt to COM9 ended in a handled serial timeout. This shows the timeout handling works; it does
not show compatibility with any adapter or vehicle. Version 2.0.0 does not depend on this
checklist for its software release; live mode stays labelled experimental until it is done.

## Safety rules for testing

- Test with the vehicle **parked**, on level ground, parking brake on, in a ventilated area
  (never run the engine in a closed garage).
- Do not operate the laptop while driving. Driving tests need a second person to operate the
  application, and only on private ground or where it is lawful and safe.
- Only use a vehicle you own or are authorised to connect to.
- SmartDrive is read-only. If any other tool is used during testing, do not clear codes before
  the trouble-code checks are recorded.

## Record of the test setup

| Item | Value |
|---|---|
| Date | |
| Tester | |
| SmartDrive version / commit | |
| Windows version | |
| Adapter (brand, model, chip, firmware version shown by SmartDrive) | |
| Connection method (USB / Bluetooth Classic) and COM port | |
| Vehicle (make, model, year, fuel type) — do not record VIN or registration | |
| OBD protocol shown by SmartDrive | |

## Checklist

| # | Check | How | Expected | Result | Evidence |
|---|---|---|---|---|---|
| 1 | Compatible adapter identification | Plug in / pair; Vehicle Connection → Refresh | Port listed with a sensible method (USB serial / Bluetooth Classic) | PENDING | |
| 2 | Serial port verification | Compare with Device Manager / Bluetooth COM ports | Same COM port | PENDING | |
| 3 | No automatic connection | Restart SmartDrive with the adapter plugged in | Nothing connects until Connect is pressed | PENDING | |
| 4 | Adapter connection, ignition **off** | Connect | Adapter connected; Vehicle ECU "not responding"; no readings | PENDING | |
| 5 | ECU connection, ignition **on** | Retry vehicle | Vehicle ECU connected; protocol shown | PENDING | |
| 6 | Supported PID discovery | Parameters table | Supported / not supported per PID; oil pressure "not defined in generic OBD-II" | PENDING | |
| 7 | Engine speed | Engine idling; compare with the instrument cluster | Within ±50 rpm of the tachometer | PENDING | |
| 8 | Coolant temperature | Warm engine; compare with gauge or another scan tool | Plausible and stable | PENDING | |
| 9 | Vehicle speed | Only under safe conditions (passenger operating, lawful) | Within a few km/h of the speedometer | PENDING | |
| 10 | Missing sensor handling | Parameters the vehicle lacks | Shown as unavailable; never as 0 or invented | PENDING | |
| 11 | Live monitoring | Source "Live vehicle (OBD-II)", Start | Gauges and charts update; banner says live, read-only | PENDING | |
| 12 | Link quality | Connection details | Success ratio and latency are plausible | PENDING | |
| 13 | Read-only trouble code scan | Diagnostic Codes → Scan | Stored/pending (and permanent if supported) codes listed; MIL state matches the dashboard lamp | PENDING | |
| 14 | No code clearing | Compare codes with another tool after the scan | Codes unchanged | PENDING | |
| 15 | Freeze frame | With a stored code, if supported | Values shown for the triggering code | PENDING | |
| 16 | Connection interruption | Unplug the adapter (USB) or switch off Bluetooth while monitoring | "Connection lost", bounded reconnect attempts, then closed; window stays responsive | PENDING | |
| 17 | Reconnection | Replug within the reconnect window | "Connection restored"; monitoring continues | PENDING | |
| 18 | Live AI compatibility | AI Diagnostics with live ML off, then on | Off: models "turned off"; On: models "incompatible" (oil pressure unavailable); rules run | PENDING | |
| 19 | Trip recording | Record a short stationary or safe trip, then stop | Trip appears in Trip History with statistics, distance marked estimated | PENDING | |
| 20 | Interrupted trip | Repeat 16 while recording, let reconnection give up | Trip marked interrupted with an event | PENDING | |
| 21 | Graceful disconnect | Disconnect button | Port released (another program can open it) | PENDING | |
| 22 | Application shutdown | Close the window while monitoring | Closes within a few seconds; trip saved; port released | PENDING | |
| 23 | Reports | Generate a trip report of the live trip | PDF states "live vehicle" data and the limitations | PENDING | |

## Sign-off

Record which checks passed, which failed (with the message shown and the log file
`smartdrive.log`), and which could not be performed. Update `ROADMAP.md` only for items with
evidence.
