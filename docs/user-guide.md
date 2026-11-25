# User guide

SmartDrive Guardian AI is an **experimental** diagnostic and maintenance assistant. It is not a
certified vehicle safety system, an autonomous driving system or a replacement for a qualified
mechanic. A clean result never means the vehicle is safe to drive.

Launch it with `smartdrive gui` (or `smartdrive-gui`, which opens without a console window).

## Getting started

1. **Vehicle Garage → Add vehicle.** Only the name, manufacturer, model, year, fuel type and
   transmission are required. The VIN and registration number are optional; they are stored
   locally, masked on screen and in logs, and can be erased with **Remove identifiers**.
2. **Set active.** The first vehicle you add becomes active automatically. You can also switch
   vehicles from the selector in the top bar.
3. **Start monitoring** (Dashboard, Live Monitoring, Simulation Lab or AI Diagnostics, or press
   Ctrl+M). Telemetry currently comes from the simulator, which is labelled *Simulation*
   wherever it appears. With **Record session** ticked, the readings are saved to the vehicle's
   history.

## Pages

| Page | What it is for |
|---|---|
| Dashboard | Gauges, speed, fuel, load, voltage, two-minute trends, the AI diagnostics summary and recent alerts |
| Live Monitoring | Charts for any of the 11 sensors, a minimum/maximum/average table, refresh interval and time range |
| Vehicle Garage | Vehicles, images, identifiers, and recorded sessions with charts |
| Simulation Lab | Choose one of 15 scenarios, seed, speed, noise and fault development time; manual driver; sensor overrides; live ground truth |
| AI Diagnostics | The hybrid assessment, model output, explanations, health score and diagnostic history |
| Settings | Theme, units, monitoring, retention, privacy, AI diagnostics, backup and restore |
| About | Version, environment, installed models, feature availability and licences |

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

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+1 … Ctrl+7 | Open Dashboard, Live Monitoring, Garage, Simulation Lab, AI Diagnostics, Settings, About |
| Ctrl+M | Start or stop monitoring |
| Ctrl+P | Pause or resume |
| Ctrl+B | Collapse or expand the sidebar |
