# Dataset card — sdg-ds-1.1.0

All results are from **synthetic data produced by the SmartDrive simulator**. They show how well the models recover the simulator's own fault signatures on unseen simulated sessions. They are **not** evidence of real-world diagnostic accuracy.

- **Source:** SmartDrive Guardian AI vehicle simulator (no real-vehicle data)
- **Fingerprint (SHA-256 of arrays):** `0127b6cc6e2046dab27d67aee4dcab4a6dc11bbe26dbb81918b5a15d31267d45`
- **Feature schema:** fs-1 (96 features)
- **Master seed:** 20261124
- **Generated:** 2026-11-25T05:23:37+00:00

## Generation method

Independent sessions of 300–900 simulated seconds,
sampled at 1.0 s. Each session picks a random driving pattern (mixed, idle,
highway, urban, heavy traffic or rapid acceleration), measurement noise (0.5–2.0×), ambient
temperature (15–40 °C) and a background dropout rate (0–3 %). Sessions belong to groups:
120 healthy, 30 per single-fault category,
30 with two simultaneous faults, and
24 healthy sessions with degraded data (heavy dropouts, connection
loss or unsupported oil sensors). Faults start at a random time, grow over 30–180 s to a random
maximum severity (0.4–1.0), and in 25 % of cases are intermittent.

Rows are 60-second feature windows taken every 5 s. A label is
positive when the fault's severity reached 0.3 within the last
20 s. Windows in which a fault had started but stayed below that
level are **excluded** as ambiguous (1977 windows). Windows with
insufficient data (see the data-quality rules) are not included.

## Splits (by whole session, stratified by session group)

| Split | Sessions | Rows | Normal rows | Multi-label rows | Positive rows per category |
|---|---|---|---|---|---|
| train | 232 | 23656 | 13450 | 1490 | cooling 2560, lubrication 2436, fuel 2643, electrical 2365, sensor 1692 |
| validation | 46 | 4535 | 2740 | 175 | cooling 268, lubrication 435, fuel 433, electrical 407, sensor 427 |
| test | 46 | 5003 | 3169 | 229 | cooling 487, lubrication 298, fuel 477, electrical 304, sensor 497 |

No session appears in more than one split (checked by `validate_dataset`).

## Missing values

Overall missing feature fraction: 0.31%.
Most-missing features: {"oil_pressure_per_krpm": 0.0184, "coolant_minus_oil": 0.0184, "oil_pressure_kpa__max": 0.0184, "oil_pressure_kpa__slope_per_min": 0.0184, "oil_pressure_kpa__mean": 0.0184, "oil_pressure_kpa__recent_mean": 0.0184, "oil_pressure_kpa__std": 0.0184, "oil_pressure_kpa__min": 0.0184}.

## Categories not covered

- **transmission**: No transmission telemetry (gear, slip, fluid temperature) exists.
- **brake**: No brake telemetry exists.
- **unknown conditions** are not a class; the Isolation Forest flags unusual patterns instead.

## Limitations

- The simulator is a simplified physical model; real vehicles differ in sensor behaviour,
  calibration, PID support and failure modes.
- Fault signatures are designed, not recorded. A model that recognises them may not recognise
  real faults.
- Some injected faults are physically hard to observe (for example, mild cooling degradation
  at highway speed); such windows are labelled positive and limit achievable recall.
