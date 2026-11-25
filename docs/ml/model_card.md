# Model card — SmartDrive Guardian AI diagnostic models

All results are from **synthetic data produced by the SmartDrive simulator**. They show how well the models recover the simulator's own fault signatures on unseen simulated sessions. They are **not** evidence of real-world diagnostic accuracy.

## Fault classifier `fault_classifier` v1.1.0

- **Type:** multi-label Random Forest (scikit-learn 1.9.1), one binary output
  per category: cooling, lubrication, fuel, electrical, sensor. Several categories can be positive at once.
- **Input:** feature schema fs-1 (96 features from a 60 s window).
  Scenario names, labels and future readings are never used as inputs.
- **Pre-processing:** median imputation inside the pipeline (identical at training and runtime).
- **Class imbalance:** `class_weight="balanced_subsample"`.
- **Selected parameters:** `{"n_estimators": 150, "max_depth": 18, "min_samples_leaf": 2, "max_features": "sqrt", "class_weight": "balanced_subsample"}`
- **Decision thresholds (tuned on validation):** `{"cooling": 0.55, "lubrication": 0.2, "fuel": 0.3, "electrical": 0.4, "sensor": 0.55}`
- **Trained:** 2026-11-25T05:24:56+00:00 on dataset sdg-ds-1.1.0
  (`0127b6cc6e2046da…`)
- **Artifact SHA-256:** `b199092390c38fc1258c8084e65b7ad3dbcc74258c11e52cdffa7f627a22ff6b`

### Hyper-parameter selection (validation macro-F1)

| Parameters | Validation macro-F1 |
|---|---|
| `{"max_depth": 12, "min_samples_leaf": 2}` | 0.7814 |
| `{"max_depth": 18, "min_samples_leaf": 2}` | 0.9130 |
| `{"max_depth": 18, "min_samples_leaf": 5}` | 0.7975 |
| `{"max_depth": null, "min_samples_leaf": 5}` | 0.8822 |

### Test results (independent simulated sessions)

Macro-F1 **0.861**, micro-F1 0.864, subset accuracy
0.890, Hamming loss 0.022.

| Category | Precision | Recall | F1 | FPR | FNR | Support |
|---|---|---|---|---|---|---|
| cooling | 0.964 | 0.542 | 0.694 | 0.002 | 0.458 | 487 |
| lubrication | 0.726 | 0.970 | 0.830 | 0.023 | 0.030 | 298 |
| fuel | 0.922 | 0.847 | 0.883 | 0.007 | 0.153 | 477 |
| electrical | 0.935 | 1.000 | 0.967 | 0.004 | 0.000 | 304 |
| sensor | 0.877 | 0.988 | 0.929 | 0.015 | 0.012 | 497 |

### Runtime behaviour

The model **abstains** when data quality is insufficient, when more than 25 % of inputs lie
outside the training range, or when the feature schema differs. Probabilities shown in the app
are the model's `predict_proba` output; a value between 60 % of the threshold and the threshold
is reported as *uncertain*, not as a finding. Probabilities are not recalibrated (see the
calibration section of the evaluation report).

## Anomaly detector `anomaly_detector` v1.1.0

- **Type:** Isolation Forest (200 trees) trained on
  13450 normal windows from training sessions only.
- **Input:** 16 features (key sensor levels, trends, ratios and operating context).
- **Thresholds:** 99.5th / 98th / 95th percentile of validation normal-window scores for
  low / standard / high sensitivity: `{"low": 0.596050403880242, "standard": 0.5644250866327188, "high": 0.5372235451147588}`.
- **Test ROC AUC (normal vs any fault):** 0.729
- The anomaly score is **not** a probability of failure.

## Intended use and limitations

Experimental decision support inside SmartDrive Guardian AI, trained and evaluated only on
synthetic data. Not a certified diagnostic tool and not a replacement for a qualified mechanic.
