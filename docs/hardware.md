# Vehicle hardware integration (OBD-II)

SmartDrive Guardian AI can read live data and trouble codes from a vehicle through an
ELM327-compatible OBD-II adapter. This document covers what is supported, how to set it up on
Windows, the read-only safety design, known limitations and troubleshooting.

> **Status.** The OBD-II layer is tested in software against a byte-level mock adapter. It has
> **not yet been tested with a physical adapter or vehicle**. Compatibility with real hardware is
> unverified until the [real-hardware checklist](hardware-verification-checklist.md) is completed.

## Supported adapters and connection methods

| Method | Supported | Notes |
|---|---|---|
| USB ELM327 adapters (CH340, FTDI, CP210x, PL2303 bridges) | Yes | Appear as a COM port. |
| Bluetooth **Classic** ELM327 adapters (SPP) | Yes | Pair in Windows first; Windows creates an outgoing COM port. |
| Other adapters exposed as a serial port that speak the ELM327 command set (for example STN11xx-based) | Expected | Only ELM327 commands are used. |
| Bluetooth **Low Energy** (BLE) adapters | **No** | They do not provide a serial port. |
| Wi-Fi adapters | **No** | They use a TCP socket, which SmartDrive does not open. |
| Manufacturer or proprietary interfaces (J2534, dealer tools, CAN interfaces) | **No** | |

Cheap ELM327 clones vary widely in quality. Some report a version string but do not implement
every command; SmartDrive reports what the adapter answers and does not assume more.

The adapter is opened at the baud rate set in `settings.json` (`obd.baudrate`) or, if none is
set, by trying 38400, 9600, 115200 and 57600 baud in turn.

## Windows setup

1. **USB adapter.** Plug it in. Windows installs a driver for common USB-serial chips; if not,
   install the driver from the chip vendor. In **Device Manager → Ports (COM & LPT)** note the
   port, for example `COM4`.
2. **Bluetooth Classic adapter.** Plug it into the vehicle, switch the ignition on and pair it
   in **Settings → Bluetooth & devices** (the PIN is often 1234 or 0000). Then open
   **More Bluetooth settings → COM Ports** and note the **Outgoing** port.
3. In SmartDrive open **Vehicle Connection** (Ctrl+8), press **Refresh**, choose the port and
   press **Connect**. Nothing connects until you press Connect; SmartDrive never opens a port
   on its own, including at start-up.
4. The page then shows two separate states: **Adapter** (the ELM327 answered) and **Vehicle
   ECU** (the vehicle answered through it). An adapter can be connected while the ignition is
   off; in that case switch the ignition on and press **Retry vehicle**.
5. To monitor, select **Live vehicle (OBD-II)** in the monitoring controls and press **Start
   monitoring**. Tick **Record session** to save the trip.

Do not operate the application while driving. Connect and start monitoring with the vehicle
parked; have a passenger watch the screen if you need to observe values on the move.

## What is read

Before polling, SmartDrive asks the vehicle which parameters it supports (mode 01 PIDs `00`,
`20`, `40`, …) and then requests only those. A parameter the vehicle does not report is shown
as **not supported** and is never estimated or filled in.

| PID | Parameter | Unit | Stored as |
|---|---|---|---|
| 01 04 | Calculated engine load | % | engine_load_pct |
| 01 05 | Engine coolant temperature | °C | coolant_temp_c |
| 01 06–09 | Short- and long-term fuel trims, banks 1 and 2 | % | extra values |
| 01 0B | Intake manifold absolute pressure | kPa | extra value |
| 01 0C | Engine speed | rpm | rpm |
| 01 0D | Vehicle speed | km/h | speed_kph |
| 01 0F | Intake air temperature | °C | intake_air_temp_c |
| 01 10 | Mass air flow rate | g/s | extra value |
| 01 11 | Throttle position | % | throttle_pct |
| 01 1F | Run time since engine start | s | extra value |
| 01 2F | Fuel tank level input | % | fuel_level_pct |
| 01 33 | Absolute barometric pressure | kPa | extra value |
| 01 42 | Control module voltage | V | control_module_voltage_v |
| 01 46 | Ambient air temperature | °C | extra value |
| 01 5C | Engine oil temperature | °C | oil_temp_c |
| 01 5E | Engine fuel rate | L/h | fuel_rate_lph |

**Engine oil pressure is not defined in generic OBD-II** and is therefore always unavailable
from a real vehicle. Many vehicles also do not report oil temperature, fuel rate or fuel level.

Values are decoded with the SAE J1979 formulas and converted to SmartDrive's metric units.
Values outside a sensor's physical range are discarded and counted as rejected, never
clamped. Each polling cycle records which parameters answered, which returned *NO DATA*, which
replies were malformed and which timed out; the Vehicle Connection page shows this per
parameter.

## Read-only safety design

All communication passes through one class (`Elm327Client`), and every request first passes an
**allowlist** of exact command strings (`src/smartdrive/obd/commands.py`). The allowlist
contains 65 entries:

- adapter set-up commands that only change how the adapter formats replies (`ATZ`, `ATE0`,
  `ATL0`, `ATS1`, `ATH0`, `ATSP0`, version and voltage queries, …);
- mode 01 current-data requests for the parameters above and the supported-PID and monitor
  status queries;
- mode 02 freeze-frame requests for the same parameters (frame 0);
- modes 03, 07 and 0A: stored, pending and permanent trouble codes.

Everything else is rejected before any byte is written, including:

| Rejected | Why |
|---|---|
| Mode 04 | Clears trouble codes and freeze-frame data. SmartDrive has no clear-codes function. |
| Mode 08 | On-board system control (actuator tests). |
| Mode 09 | Vehicle identification (VIN, calibration IDs) — excluded for privacy. |
| UDS / KWP services (`10`, `27`, `2E`, `2F`, `31`, `3E`, …) | Diagnostic sessions, security access, writes, routines, tester present. |
| `AT SH`, `AT MA`, `AT CRA`, `STPX` and similar | Would allow arbitrary CAN frames or bus monitoring. |
| Anything with characters other than `0-9`, `A-Z`, `@` | Prevents command injection (for example `\r` sequences). |

There is no way to type a command in the application. Automated tests check that each
prohibited command is refused and never reaches the transport, and that a trouble-code scan
sends no clearing command.

Not implemented, by design: ECU programming, flashing or coding, actuator control, immobiliser
or security functions, emissions-system changes, arbitrary CAN transmission and code clearing.

## Connection lifecycle and failure handling

States: Disconnected → Searching → Connecting → Adapter connected → Vehicle ECU connected →
Monitoring, plus Reconnecting, Connection failed and Disconnecting.

| Situation | Behaviour |
|---|---|
| No adapter / no ports | Empty state with setup guidance; no readings are shown. |
| Invalid port name or port not found | Clear message; nothing is opened. |
| Port in use by another program | "The port is in use by another program" message. |
| Device is not an ELM327 | Reported after the baud-rate probe; the port is closed. |
| Adapter connected, vehicle silent (ignition off) | Adapter shown as connected, ECU as not responding; **Retry vehicle**. |
| Unsupported protocol | Reported with the protocol the adapter detected. |
| Unsupported PID, *NO DATA*, malformed reply, single timeouts | Parameter marked unavailable for that cycle; polling continues. |
| Every parameter times out, or the adapter disappears | Link lost: a bounded number of reconnection attempts with exponential back-off (default 3, starting at 2 s and doubling), then the connection is closed. |
| Link lost during a recorded trip | Connection lost/restored events are added to the trip timeline; if reconnection gives up, monitoring stops and the trip is marked **interrupted**. |
| Stale telemetry | Marked stale after the configured time; diagnostics report *Telemetry stale* instead of analysing old data. |
| Application closes during any of the above | Pending reads are cancelled, the port is closed and the trip is ended. |

All serial I/O runs on a dedicated worker thread; the window never waits for the adapter.
Timeouts, polling interval and reconnection attempts are in **Settings → Vehicle connection**.

## Trouble codes

**Diagnostic Codes** (Ctrl+9) reads stored (mode 03), pending (mode 07) and, where supported,
permanent (mode 0A) codes, the check-engine lamp state and, if enabled, the freeze frame. Each
scan is stored with its time, data source and protocol; codes keep their first and most recent
detection and are marked when they disappear from a later scan.

Descriptions come from a local reference of SmartDrive's own short paraphrases of the generic
SAE J2012 definitions (about 120 common codes, source recorded with every description).
**Manufacturer-specific codes (P1xxx, B1xxx, C1xxx, U1xxx and similar) are never given a
meaning**; they are shown as manufacturer-specific, and an unknown generic code is shown as
unknown. A code means a control unit detected a condition; it does not confirm that a part has
failed.

Generic OBD-II mostly reaches emissions-related powertrain modules. Body (B), chassis (C) and
network (U) modules often need manufacturer tools, so their absence from a scan does not mean
they have no codes.

## The mock adapter (development and testing only)

`Settings → Vehicle connection → Show the mock adapter` adds a **MOCK** port. It emulates an
ELM327 at the byte level (healthy vehicle, stored codes, partial sensors, ignition off, older
protocol) so the full connection, polling and scanning code can be exercised without hardware.
Data from the mock adapter is always labelled and recorded as **simulated**, never as live
vehicle data, and test results obtained with it are not evidence of hardware compatibility.

## Machine learning on live data

The Phase 3 models were trained on simulated data with every monitored sensor present. On live
data:

- Experimental model inference is **off by default** (`Settings → AI diagnostics → Also on
  live vehicle data`). When off, only the transparent rules run.
- When on, the models still run only if the vehicle provides every sensor they were trained
  with. Because engine oil pressure is not available over generic OBD-II, **in practice the
  models report "incompatible" on real vehicles and do not produce predictions**; rules still
  run on whatever is available. This is intentional: predicting from a different input
  distribution would be misleading.
- The rule thresholds are generic and conservative, not manufacturer specifications. Values
  for a particular vehicle can be entered on the Vehicle Connection page with their source.
- The absence of warnings never means the vehicle is safe to drive.

## Troubleshooting

| Symptom | Things to check |
|---|---|
| No ports listed | Driver installed? Bluetooth adapter paired? Press Refresh after plugging in. |
| "Port in use" | Close other OBD software (and phone apps paired to the same adapter). |
| Adapter connects, vehicle does not | Ignition on; try Retry vehicle; some vehicles need the engine running. |
| Many timeouts | Increase the response timeout; move closer (Bluetooth); some clones are slow — increase the polling interval. |
| Values missing | The vehicle does not support that PID; this is normal. |
| Connection drops repeatedly | Loose connector, weak Bluetooth link, or an adapter that resets under load. |

## Privacy

Connection history stores the port name, adapter version, protocol, supported PIDs and sample
counts — not the VIN (mode 09 is blocked). Everything stays in the local database. See
[PRIVACY.md](../PRIVACY.md).
