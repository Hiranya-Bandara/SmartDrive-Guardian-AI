# User guide

SmartDrive Guardian AI is an **experimental** diagnostic and maintenance assistant. It is not a
certified vehicle safety system, an autonomous driving system or a replacement for a qualified
mechanic. A clean result never means the vehicle is safe to drive.

Install it with the Windows installer or the portable ZIP ([installation.md](installation.md)) and
start **SmartDrive Guardian AI** from the Start Menu. From a source checkout, run `smartdrive gui`
(or `smartdrive-gui`, which opens without a console window).

On the first start a short **welcome guide** explains simulation and live modes, what the AI
findings can and cannot tell you, and where your data is kept. Reopen it from **About → Show
welcome guide**. Problems: [troubleshooting.md](troubleshooting.md). Data and privacy:
[PRIVACY.md](../PRIVACY.md).

## Getting started

1. **Vehicle Garage → Add vehicle.** Only the name, manufacturer, model, year, fuel type and
   transmission are required. The VIN and registration number are optional; they are stored
   locally, masked on screen and in logs, and can be erased with **Remove identifiers**.
2. **Set active.** The first vehicle you add becomes active automatically. You can also switch
   vehicles from the selector in the top bar.
3. **Choose a source and start monitoring** (Dashboard, Live Monitoring, Vehicle Connection,
   Simulation Lab or AI Diagnostics, or press Ctrl+M). The source is either the **Simulator**
   or **Live vehicle (OBD-II)**; live monitoring needs an adapter connected on the Vehicle
   Connection page first (see [hardware.md](hardware.md)). Every page labels the data as
   simulated, live or replayed. With **Record session** ticked, the readings are saved as a
   trip.

Do not use the application while driving.

## Pages

| Page | Shortcut | What it is for |
|---|---|---|
| Dashboard | Ctrl+1 | Gauges, trends, AI summary, recent alerts, and a summary of connection, codes, trips, maintenance and notifications |
| Live Monitoring | Ctrl+2 | Charts for any sensor, a minimum/maximum/average table, refresh interval and time range |
| AI Diagnostics | Ctrl+5 | The hybrid assessment, model output, explanations, health score and diagnostic history |
| Vehicle Connection | Ctrl+8 | Choose a serial port, connect read-only to an OBD-II adapter, see supported parameters, link quality and diagnostics, and set vehicle-specific rule thresholds |
| Diagnostic Codes | Ctrl+9 | Scan stored, pending and permanent trouble codes; history, details and export. There is no clear-codes function. |
| Vehicle Garage | Ctrl+3 | Vehicles, images and identifiers |
| Trip History | Ctrl+Shift+T | Recorded trips with filters, statistics, timeline, charts, export, deletion and replay |
| Maintenance | Ctrl+Shift+M | Service records, your schedules and reminders, odometer, costs and AI-related observations |
| Simulation Lab | Ctrl+4 | 15 scenarios, seed, speed, noise, fault development; manual driver; sensor overrides |
| Reports | Ctrl+Shift+R | PDF reports and CSV exports, export history |
| Alert Centre | Ctrl+0 | Notifications and diagnostic alerts, filters, acknowledge and mark as read |
| Settings | Ctrl+6 | Appearance, monitoring, data and privacy, AI diagnostics, vehicle connection, notifications and voice, trips/maintenance/reports, backup |
| About | Ctrl+7 | Version, environment, models, licences |

## Trips and replay

A trip is saved when you monitor with **Record session** ticked. When it ends, SmartDrive
computes its statistics in the background: duration, completeness, average and maximum speed
and engine speed, coolant range, an **estimated distance** (speed integrated over time; gaps
longer than 5 s or without speed are not bridged, and the share of time that contributed is
shown) and the number of warning and critical events. No GPS position, route, fuel use or
odometer value is derived. A trip whose connection failed is marked *interrupted*.

**Replay** plays a trip's recorded samples at 0.5×, 1×, 2× or 4×, with pause, stop and seeking.
Gauges, charts and AI Diagnostics follow the replay, which is labelled as recorded data. The
analysis during a replay is recalculated now and is shown separately from the findings recorded
at the time of the trip; it is never saved, and a replay never contacts an adapter.

## Maintenance

- **Records:** what was done, when, at which odometer reading, by whom and at what cost
  (currency per record, default LKR). Notes stay private.
- **Schedules:** your own intervals by time, distance or both ("whichever comes first"). "Fill
  in example interval" offers illustrative values that are clearly marked as examples, not
  manufacturer schedules. Each schedule shows *Not scheduled*, *Up to date*, *Upcoming*,
  *Due*, *Overdue* or *Insufficient mileage information*.
- **Odometer:** distance reminders use the reading you record with its date. An old reading
  (default more than 60 days) is not treated as current.
- **Costs** are totalled per currency, per month, year and category. Different currencies are
  never added together.
- **AI-related observations** are cautious prompts based on repeated findings, anomalies,
  health-score trends and stored codes. They never predict when something will fail.

## Notifications

Notifications appear as in-app toasts and in the **Alert Centre**, optionally as Windows
desktop notifications, a sound, and offline voice announcements (Settings → Notifications and
voice). A repeated notification within its cooldown updates the existing entry instead of
creating a new one. Acknowledging or reading a notification never clears the vehicle condition
behind it; diagnostic alerts show separately whether the condition is still active. Voice and
desktop notifications supplement the screen; they are not a safety warning system.

## Using AI Diagnostics

Diagnostics run in the background roughly every 2 seconds while monitoring is running. Each
analysis looks at the last minute of telemetry.

**Status** shows one of the following: *Monitoring stopped*, *Loading models*, *Collecting
telemetry*, *Insufficient data*, *Telemetry stale*, *No abnormality detected*, *Information*,
*Warning* or *Critical finding*.

**Findings** have one of three sources:

- **Rule engine:** transparent checks such as "coolant above 105 °C for 10 s". These are always
  shown, and no model can hide or downgrade them.
- **Random Forest model:** a pattern the model learned from simulated faults. It appears only
  after two consecutive analyses agree, and it is at most a *warning*. "Agrees with" means a rule
  reports the same category. That agreement is evidence, not proof.
- **Anomaly detector:** telemetry that looks unlike normal simulated driving for several analyses
  in a row. It doesn't name a cause, so it is reported as *information* and raises no alert on
  its own.

**Random Forest bars** show the model's raw output for each category against its decision
threshold. *Positive* means at or above the threshold; *uncertain* means close to it. These are
scores from a model trained on simulated data, not the probability that something has failed.
*Not assessed* means the vehicle doesn't report the signal the category needs; for example,
lubrication can't be assessed without oil pressure.

**Why the model produced this output.** Pick a category to see which telemetry features pushed
the output up (orange) or down (blue). These numbers are an exact breakdown of that prediction. The
**global importance** chart next to it describes the model as a whole, not the current
prediction.

**Experimental health score** (0–100). Every deduction is listed next to the ring. It is
*unavailable* when there is too little data. It is an indicator, not a safety rating.

**Recommendations** are cautious and evidence-based. They never contain repair instructions, and
they point you to a qualified mechanic.

**Diagnostic history** stores findings for the active vehicle. You can filter by severity,
source and operating mode, or search. Select a row to see its evidence, model version and the
recommendation given at the time.

**Alerts.** Warning and critical findings create alerts, which appear under Recent alerts and as
notifications. If the same finding repeats within the cooldown (Settings → AI diagnostics), it
updates the existing alert instead of creating a new one.

### When the models are unavailable

If a model file is missing, fails its integrity check or was trained with an incompatible
scikit-learn version, the model shows as *unavailable*, *integrity check failed* or
*incompatible*. The rule engine keeps working. Reinstall the application, or regenerate the
models with `python scripts\train_models.py` (see `docs/ml/README.md`).

## Settings for diagnostics

| Setting | Effect |
|---|---|
| Run diagnostics while monitoring | Turns all background analysis on or off |
| Use machine-learning models | Off means only the rule engine runs |
| Analyse every | Seconds between analyses (1–10) |
| Anomaly sensitivity | Low gives fewer alarms; high gives more |
| Anomaly must persist for | Consecutive unusual analyses before a finding appears |
| Alert cooldown | How long repeats update an existing alert instead of creating a new one |

Rule thresholds are stored in `settings.json` under `diagnostics.thresholds`. They are
conservative simulation defaults, not manufacturer specifications.

## Live vehicle data and AI

On live data only the transparent rules run by default. The experimental models can be switched
on (Settings → AI diagnostics → Also on live vehicle data), but they run only if the vehicle
provides every sensor they were trained with; generic OBD-II never provides oil pressure, so on
real vehicles they report *incompatible*. See [hardware.md](hardware.md#machine-learning-on-live-data).

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+1 … Ctrl+7 | Dashboard, Live Monitoring, Garage, Simulation Lab, AI Diagnostics, Settings, About (unchanged from Phase 3) |
| Ctrl+8, Ctrl+9, Ctrl+0 | Vehicle Connection, Diagnostic Codes, Alert Centre |
| Ctrl+Shift+T / M / R | Trip History, Maintenance, Reports |
| Ctrl+M | Start or stop monitoring |
| Ctrl+P | Pause or resume |
| Ctrl+B | Collapse or expand the sidebar |
