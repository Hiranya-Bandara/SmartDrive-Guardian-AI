"""Evaluation artefacts: figures (matplotlib, training-time only) and Markdown cards.

This module is used by ``scripts/train_models.py``; the desktop application never imports it,
so matplotlib is a development dependency only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from smartdrive.ai.dataset import LABELS, UNSUPPORTED_CATEGORIES
from smartdrive.ai.training import ANOMALY_PERCENTILES

SYNTHETIC_NOTICE = (
    "All results are from **synthetic data produced by the SmartDrive simulator**. They show how "
    "well the models recover the simulator's own fault signatures on unseen simulated sessions. "
    "They are **not** evidence of real-world diagnostic accuracy."
)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def plot_confusion_matrices(metrics: dict[str, Any], path: Path) -> None:
    per_label = metrics["all_rows_model_output"]["per_label"]
    fig, axes = plt.subplots(1, len(LABELS), figsize=(3.2 * len(LABELS), 3.4))
    for axis, category in zip(axes, LABELS, strict=True):
        m = per_label[category.value]
        matrix = np.array([[m["tn"], m["fp"]], [m["fn"], m["tp"]]])
        axis.imshow(matrix, cmap="Blues")
        for (row, col), value in np.ndenumerate(matrix):
            axis.text(
                col,
                row,
                str(value),
                ha="center",
                va="center",
                color="white" if value > matrix.max() / 2 else "black",
                fontsize=11,
            )
        axis.set_xticks([0, 1], ["pred 0", "pred 1"])
        axis.set_yticks([0, 1], ["true 0", "true 1"])
        axis.set_title(f"{category.value}\nF1 {m['f1']:.2f}", fontsize=10)
    fig.suptitle("Random Forest confusion matrices — synthetic test sessions", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_feature_importance(importance: list[dict[str, Any]], path: Path, top: int = 20) -> None:
    rows = importance[:top][::-1]
    fig, axis = plt.subplots(figsize=(8, 0.32 * top + 1.2))
    axis.barh(
        [r["feature"] for r in rows],
        [r["permutation_mean"] for r in rows],
        xerr=[r["permutation_std"] for r in rows],
        color="#0E7490",
    )
    axis.set_xlabel("Decrease in validation macro-F1 when the feature is shuffled")
    axis.set_title("Global permutation feature importance (validation split)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_anomaly_scores(
    normal: np.ndarray, abnormal: np.ndarray, threshold: float, path: Path
) -> None:
    fig, axis = plt.subplots(figsize=(8, 3.6))
    bins = np.linspace(min(normal.min(), abnormal.min()), max(normal.max(), abnormal.max()), 50)
    edges = [float(b) for b in bins]
    axis.hist(normal, bins=edges, alpha=0.6, label="normal windows", color="#15803D")
    axis.hist(abnormal, bins=edges, alpha=0.6, label="fault windows", color="#B91C1C")
    axis.axvline(threshold, color="black", linestyle="--", label="standard threshold")
    axis.set_xlabel("Isolation Forest anomaly score (higher = more unusual)")
    axis.set_ylabel("windows")
    axis.set_title("Anomaly scores on synthetic test sessions")
    axis.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_calibration(calibration: dict[str, Any], path: Path) -> None:
    fig, axis = plt.subplots(figsize=(5.5, 5))
    axis.plot([0, 1], [0, 1], "k--", linewidth=1, label="perfect calibration")
    for category in LABELS:
        bins = calibration[category.value]["bins"]
        axis.plot(
            [b["mean_probability"] for b in bins],
            [b["observed_rate"] for b in bins],
            marker="o",
            label=category.value,
        )
    axis.set_xlabel("Mean predicted probability")
    axis.set_ylabel("Observed positive rate")
    axis.set_title("Reliability diagram (test split)")
    axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def classification_report(metrics: dict[str, Any]) -> dict[str, Any]:
    output = metrics["all_rows_model_output"]
    report: dict[str, Any] = {
        c: {k: v[k] for k in ("precision", "recall", "f1", "support")}
        for c, v in output["per_label"].items()
    }
    report["macro avg f1"] = output["macro_f1"]
    report["micro avg f1"] = output["micro_f1"]
    return report


def _label_table(metrics: dict[str, Any]) -> str:
    lines = [
        "| Category | Precision | Recall | F1 | FPR | FNR | Support |",
        "|---|---|---|---|---|---|---|",
    ]
    for category, m in metrics["per_label"].items():
        lines.append(
            f"| {category} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | "
            f"{m['false_positive_rate']:.3f} | {m['false_negative_rate']:.3f} | {m['support']} |"
        )
    return "\n".join(lines)


def dataset_card(meta: dict[str, Any]) -> str:
    summary = meta["summary"]
    config = meta["config"]
    rows = []
    for split in ("train", "validation", "test"):
        s = summary[split]
        positives = ", ".join(f"{k} {v}" for k, v in s["positives"].items())
        rows.append(
            f"| {split} | {s['sessions']} | {s['rows']} | {s['normal_rows']} | "
            f"{s['multi_label_rows']} | {positives} |"
        )
    unsupported = "\n".join(f"- **{k.value}**: {v}" for k, v in UNSUPPORTED_CATEGORIES.items())
    return f"""# Dataset card — {meta["dataset_version"]}

{SYNTHETIC_NOTICE}

- **Source:** {meta["source"]}
- **Fingerprint (SHA-256 of arrays):** `{meta["fingerprint"]}`
- **Feature schema:** {meta["feature_schema_version"]} ({meta["feature_count"]} features)
- **Master seed:** {config["master_seed"]}
- **Generated:** {meta["generated_at"]}

## Generation method

Independent sessions of {config["min_duration_s"]}–{config["max_duration_s"]} simulated seconds,
sampled at {config["step_s"]} s. Each session picks a random driving pattern (mixed, idle,
highway, urban, heavy traffic or rapid acceleration), measurement noise (0.5–2.0×), ambient
temperature (15–40 °C) and a background dropout rate (0–3 %). Sessions belong to groups:
{config["healthy_sessions"]} healthy, {config["sessions_per_fault"]} per single-fault category,
{config["multiple_fault_sessions"]} with two simultaneous faults, and
{config["degraded_data_sessions"]} healthy sessions with degraded data (heavy dropouts, connection
loss or unsupported oil sensors). Faults start at a random time, grow over 30–180 s to a random
maximum severity (0.4–1.0), and in 25 % of cases are intermittent.

Rows are {config["window_s"]}-second feature windows taken every {config["stride_s"]} s. A label is
positive when the fault's severity reached {config["label_threshold"]} within the last
{config["label_lookback_s"]:.0f} s. Windows in which a fault had started but stayed below that
level are **excluded** as ambiguous ({meta["ambiguous_windows_excluded"]} windows). Windows with
insufficient data (see the data-quality rules) are not included.

## Splits (by whole session, stratified by session group)

| Split | Sessions | Rows | Normal rows | Multi-label rows | Positive rows per category |
|---|---|---|---|---|---|
{chr(10).join(rows)}

No session appears in more than one split (checked by `validate_dataset`).

## Missing values

Overall missing feature fraction: {summary["missing_value_fraction"]["overall"]:.2%}.
Most-missing features: {json.dumps(summary["missing_value_fraction"]["most_missing_features"])}.

## Categories not covered

{unsupported}
- **unknown conditions** are not a class; the Isolation Forest flags unusual patterns instead.

## Limitations

- The simulator is a simplified physical model; real vehicles differ in sensor behaviour,
  calibration, PID support and failure modes.
- Fault signatures are designed, not recorded. A model that recognises them may not recognise
  real faults.
- Some injected faults are physically hard to observe (for example, mild cooling degradation
  at highway speed); such windows are labelled positive and limit achievable recall.
"""


def model_card(
    manifest: dict[str, Any],
    metrics: dict[str, Any],
    selection: list[dict[str, Any]],
    anomaly: dict[str, Any],
) -> str:
    clf = manifest["fault_classifier"]
    det = manifest["anomaly_detector"]
    test = metrics["all_rows_model_output"]
    pcts = " / ".join(f"{ANOMALY_PERCENTILES[k]:g}th" for k in ("low", "standard", "high"))
    selection_rows = "\n".join(
        f"| `{json.dumps(s['params'])}` | {s['validation_macro_f1']:.4f} |" for s in selection
    )
    return f"""# Model card — SmartDrive Guardian AI diagnostic models

{SYNTHETIC_NOTICE}

## Fault classifier `{clf["name"]}` v{clf["version"]}

- **Type:** multi-label Random Forest (scikit-learn {clf["sklearn_version"]}), one binary output
  per category: {", ".join(c.value for c in LABELS)}. Several categories can be positive at once.
- **Input:** feature schema {clf["feature_schema_version"]} (96 features from a 60 s window).
  Scenario names, labels and future readings are never used as inputs.
- **Pre-processing:** median imputation inside the pipeline (identical at training and runtime).
- **Class imbalance:** `class_weight="balanced_subsample"`.
- **Selected parameters:** `{json.dumps(clf["parameters"])}`
- **Decision thresholds (tuned on validation):** `{json.dumps(clf["thresholds"])}`
- **Trained:** {clf["trained_at"]} on dataset {clf["dataset_version"]}
  (`{clf["dataset_fingerprint"][:16]}…`)
- **Artifact SHA-256:** `{clf["sha256"]}`

### Hyper-parameter selection (validation macro-F1)

| Parameters | Validation macro-F1 |
|---|---|
{selection_rows}

### Test results (independent simulated sessions)

Macro-F1 **{test["macro_f1"]:.3f}**, micro-F1 {test["micro_f1"]:.3f}, subset accuracy
{test["subset_accuracy"]:.3f}, Hamming loss {test["hamming_loss"]:.3f}.

{_label_table(test)}

### Runtime behaviour

The model **abstains** when data quality is insufficient, when more than 25 % of inputs lie
outside the training range, or when the feature schema differs. Probabilities shown in the app
are the model's `predict_proba` output; a value between 60 % of the threshold and the threshold
is reported as *uncertain*, not as a finding. Probabilities are not recalibrated (see the
calibration section of the evaluation report).

## Anomaly detector `{det["name"]}` v{det["version"]}

- **Type:** Isolation Forest ({det["parameters"].get("n_estimators")} trees) trained on
  {det["baseline_rows"]} normal windows from training sessions only.
- **Input:** 16 features (key sensor levels, trends, ratios and operating context).
- **Thresholds:** {pcts} percentile of validation normal-window scores for
  low / standard / high sensitivity: `{json.dumps(det["thresholds"])}`.
- **Test ROC AUC (normal vs any fault):** {anomaly["roc_auc_normal_vs_abnormal"]:.3f}
- The anomaly score is **not** a probability of failure.

## Intended use and limitations

Experimental decision support inside SmartDrive Guardian AI, trained and evaluated only on
synthetic data. Not a certified diagnostic tool and not a replacement for a qualified mechanic.
"""


def _catalogue_table(catalogue: dict[str, Any]) -> str:
    rows = []
    for name, entry in catalogue.items():
        detected = f"{entry['runs_detected']} of {entry['runs']}" if not entry["healthy"] else "—"
        delay = entry.get("median_detection_after_onset_s")
        rows.append(
            f"| {name.replace('_', ' ')} | {'yes' if entry['healthy'] else 'no'} "
            f"| {_pct(entry['alarm_rate'])} | {entry['runs_with_any_alarm']} of {entry['runs']} "
            f"| {detected} | {'—' if delay is None else f'{delay:.0f} s'} |"
        )
    return "\n".join(rows)


def _limitations(
    metrics: dict[str, Any], anomaly: dict[str, Any], catalogue: dict[str, Any]
) -> str:
    """Failure cases derived from this run's numbers, so the text cannot go stale."""
    per_label = metrics["all_rows_model_output"]["per_label"]
    weakest = min(per_label, key=lambda c: per_label[c]["f1"])
    worst_recall = min(per_label, key=lambda c: per_label[c]["recall"])
    worst_precision = min(per_label, key=lambda c: per_label[c]["precision"])
    rules = metrics["rule_baseline"]["per_label"]
    missed_by_rules = [c for c, v in rules.items() if v["f1"] < 0.1]
    session = anomaly["session_level"]
    healthy_alarms = {
        name: entry
        for name, entry in catalogue.items()
        if entry["healthy"] and entry["runs_with_any_alarm"]
    }
    lines = [
        f"- **Weakest category: {weakest}** (F1 {per_label[weakest]['f1']:.3f}). Lowest recall: "
        f"{worst_recall} ({per_label[worst_recall]['recall']:.3f}); lowest precision: "
        f"{worst_precision} ({per_label[worst_precision]['precision']:.3f}).",
        "- Decision thresholds favour precision (validation precision ≥ 0.9), so the model "
        "accepts missed detections in exchange for fewer false alarms.",
    ]
    weak_patterns = [
        f"{category} in {pattern.replace('_', ' ')} driving (recall {v['recall']:.2f}, "
        f"{v['windows']} windows from {v['sessions']} session(s))"
        for category, patterns in metrics["recall_by_pattern"].items()
        for pattern, v in patterns.items()
        if v["recall"] < 0.5
    ]
    if weak_patterns:
        lines.append(
            "- **Detection depends on driving pattern.** Recall below 0.5 on the test split: "
            + "; ".join(weak_patterns)
            + ". Each figure rests on very few sessions, so it is an indication rather than a "
            "measured rate: a fault that develops in these conditions may go undetected by the "
            "model (the rules still apply). See `recall_by_pattern` in metrics.json."
        )
    if missed_by_rules:
        lines.append(
            f"- The rule baseline almost never detects: {', '.join(missed_by_rules)}. Only "
            "the model covers these patterns."
        )
    lines.append(
        f"- **Anomaly detector:** {session['healthy_sessions_with_persistent_alarm']} of "
        f"{session['healthy_sessions']} healthy test sessions produced a persistent anomaly, "
        "and it detects only part of the fault windows. That is why an anomaly is reported as "
        "information and never raises an alert on its own."
    )
    for name, entry in healthy_alarms.items():
        lines.append(
            f"- Healthy built-in scenario *{name.replace('_', ' ')}* raised a warning in "
            f"{entry['runs_with_any_alarm']} of {entry['runs']} drives "
            f"({_pct(entry['alarm_rate'])} of analyses)."
        )
    lines += [
        "- The robustness subsets differ in their mix of healthy and faulty sessions and of "
        "driving patterns, so their scores are not directly comparable with each other.",
        "- Transmission and brake faults cannot be assessed: there is no telemetry for them.",
        "- No real vehicle data was used. These figures must not be read as real-world accuracy.",
    ]
    return "\n".join(lines)


def evaluation_report(
    metrics: dict[str, Any],
    anomaly: dict[str, Any],
    latency: dict[str, float],
    catalogue: dict[str, Any],
) -> str:
    first = next(iter(catalogue.values()))
    catalogue_runs = first["runs"]
    catalogue_minutes = round(first["analyses"] / first["runs"] * 2 / 60)
    ml = metrics["all_rows_model_output"]
    rule = metrics["rule_baseline"]
    hybrid = metrics["hybrid_union"]
    rob = "\n".join(
        f"| {name} | {m['rows']} | {m['macro_f1']:.3f} | {m['micro_f1']:.3f} |"
        for name, m in metrics["robustness"].items()
    )
    cal = "\n".join(
        f"| {c} | {v['brier']:.4f} | {v['expected_calibration_error']:.4f} |"
        for c, v in metrics["calibration"].items()
    )
    rows = []
    for c in LABELS:
        r, m, h = (x["per_label"][c.value] for x in (rule, ml, hybrid))
        rows.append(
            f"| {c.value} | {r['f1']:.3f} | {m['f1']:.3f} | {h['f1']:.3f} "
            f"| {r['false_positive_rate']:.3f} | {m['false_positive_rate']:.3f} |"
        )
    comparison = "\n".join(rows)
    session = anomaly["session_level"]
    return f"""# Evaluation report

{SYNTHETIC_NOTICE}

Test split: **{metrics["sessions"]} independent simulated sessions** never used for training,
model selection or threshold tuning. Every number below was produced by
`python scripts/train_models.py`; rerunning it with the same configuration reproduces them.

## 1. Random Forest (all test windows)

Macro-F1 **{ml["macro_f1"]:.3f}** · micro-F1 {ml["micro_f1"]:.3f} · subset accuracy
{ml["subset_accuracy"]:.3f} · Hamming loss {ml["hamming_loss"]:.3f}

{_label_table(ml)}

"Any abnormality" detection: precision {ml["any_abnormality"]["precision"]:.3f}, recall
{ml["any_abnormality"]["recall"]:.3f}, false-positive rate on normal windows
{ml["any_abnormality"]["false_positive_rate"]:.3f}.

Out-of-distribution abstention on the test split: {_pct(metrics["abstention_rate"])} of windows.
Treating abstentions as "no finding" gives macro-F1
{metrics["with_abstention_as_no_finding"]["macro_f1"]:.3f}.

![Confusion matrices](confusion_matrix.png)

### As used in the application

The application shows a model finding only after the same category is positive in
{metrics["confirmation_windows"]} consecutive analyses. Applying that rule to the test sessions in
time order gives macro-F1 **{metrics["runtime_confirmed"]["macro_f1"]:.3f}** and an "any
abnormality" false-positive rate of
{metrics["runtime_confirmed"]["any_abnormality"]["false_positive_rate"]:.3f}
(cooling FPR {metrics["runtime_confirmed"]["per_label"]["cooling"]["false_positive_rate"]:.3f}).

{_label_table(metrics["runtime_confirmed"])}

## 2. Comparison with the rule-based baseline

The rule engine was run on the same windows in time order (with its persistence and hysteresis).
A rule "detects" a category when it reports a warning or critical finding for it.

| Category | Rules F1 | Random Forest F1 | Union F1 | Rules FPR | RF FPR |
|---|---|---|---|---|---|
{comparison}

Macro-F1 — rules {rule["macro_f1"]:.3f}, Random Forest {ml["macro_f1"]:.3f}, union of both
{hybrid["macro_f1"]:.3f}. The rules use fixed, conservative limits and need persistence, so they
miss early and mild faults; the classifier sees combinations of features (for example, oil
pressure per 1000 rpm and fuel use per unit load). In the hybrid engine the rules are never
overridden; the model adds findings and evidence.

## 3. Robustness

| Subset | Rows | Macro-F1 | Micro-F1 |
|---|---|---|---|
{rob}

## 4. Calibration

| Category | Brier score | Expected calibration error |
|---|---|---|
{cal}

![Reliability diagram](calibration.png)

Probabilities are shown as produced by the model and are described as model output, not as
the likelihood of a mechanical fault.

## 5. Isolation Forest

ROC AUC (normal vs any fault window): **{anomaly["roc_auc_normal_vs_abnormal"]:.3f}**. At the
standard threshold: window-level false-positive rate
{anomaly["window_level"]["false_positive_rate"]:.3f}, detection rate
{anomaly["window_level"]["recall"]:.3f}. Detection rate by category:
`{json.dumps(anomaly["detection_rate_by_category"])}`.

Session level (anomaly reported only after {session["persistence_windows"]} consecutive anomalous
windows): {session["healthy_sessions_with_persistent_alarm"]} of {session["healthy_sessions"]}
healthy test sessions raised a persistent anomaly; {session["fault_sessions_detected_after_onset"]}
of {session["fault_sessions"]} fault sessions were flagged after the fault became labelled.

![Anomaly score distribution](anomaly_scores.png)

## 6. Inference latency (measured)

Measured on the build machine over {int(latency["runs"])} runs of one complete inference
(window → features → classifier → anomaly → explanation of the top category):
median **{latency["median_ms"]:.1f} ms**, 95th percentile {latency["p95_ms"]:.1f} ms.

## 7. Built-in scenarios through the complete hybrid engine

The full engine (rules, classifier with confirmation, anomaly detector with persistence) was
run exactly as in the application — one analysis every 2 s over a 60 s window — on every
catalogue scenario: {catalogue_runs} drives of {catalogue_minutes} minutes each, with seeds that
appear nowhere in the training data. For healthy scenarios every warning or critical finding is
a false alarm.

| Scenario | Healthy | Analyses with alarm | Drives with alarm | Detected | Median delay |
|---|---|---|---|---|---|
{_catalogue_table(catalogue)}

## 8. Development notes (disclosed for transparency)

- Thresholds are the highest-F1 value subject to validation precision ≥ 0.9; the standard anomaly
  threshold is the 98th percentile of validation normal scores. Both use validation data only.
- **Dataset 1.0.0 → 1.1.0.** The first shipped models (dataset sdg-ds-1.0.0: 48 healthy
  sessions with randomly chosen driving patterns, every drive starting part-warm, at most 10
  minutes long) reported a cooling abnormality in 44–60 % of analyses of the healthy built-in
  *engine idling* scenario (3 seeds, measured with the complete engine). The held-out test split
  did not reveal this because it contained too few healthy idling sessions. Dataset 1.1.0 uses 120
  healthy sessions spread evenly over all six driving patterns, drives of 5–15 minutes and starting
  engine temperatures from cold to fully warm. The catalogue check in section 7 was added so that
  this class of problem is measured on every training run. This decision was made after seeing
  the behaviour of the first models.
- **Anomaly findings reported as information.** The first evaluation of the 1.1.0 models
  showed that the healthy *rapid acceleration* scenario produced an anomaly warning in 5 of 5
  drives (1.3 % of analyses), and that 6 of 22 healthy test sessions produced a persistent
  anomaly. An anomaly cannot name a cause and on its own detects only about a third of fault
  windows, so anomaly-only findings are now always INFORMATION and never raise alerts. This
  changed the engine's decision policy after test results had been seen. The models
  themselves were not retrained or re-tuned for it.
- The test split contains a few dozen sessions, so per-category estimates vary noticeably between
  splits.

## 9. Failure cases and limitations

{_limitations(metrics, anomaly, catalogue)}
"""


def write_reports(
    directory: Path,
    *,
    metrics: dict[str, Any],
    anomaly: dict[str, Any],
    dataset_meta: dict[str, Any],
    manifest: dict[str, Any],
    selection: list[dict[str, Any]],
    importance: list[dict[str, Any]],
    normal_scores: np.ndarray,
    abnormal_scores: np.ndarray,
    latency: dict[str, float],
    catalogue: dict[str, Any],
) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {
        "metrics.json": json.dumps(
            {
                "classifier": metrics,
                "anomaly_detector": anomaly,
                "catalogue_scenarios": catalogue,
                "latency_ms": latency,
            },
            indent=2,
        ),
        "classification_report.json": json.dumps(classification_report(metrics), indent=2),
        "model_card.md": model_card(manifest, metrics, selection, anomaly),
        "dataset_card.md": dataset_card(dataset_meta),
        "evaluation_report.md": evaluation_report(metrics, anomaly, latency, catalogue),
    }
    written = []
    for name, text in outputs.items():
        path = directory / name
        path.write_text(text, "utf-8")
        written.append(path)
    plot_confusion_matrices(metrics, directory / "confusion_matrix.png")
    plot_feature_importance(importance, directory / "feature_importance.png")
    plot_anomaly_scores(
        normal_scores,
        abnormal_scores,
        manifest["anomaly_detector"]["thresholds"]["standard"],
        directory / "anomaly_scores.png",
    )
    plot_calibration(metrics["calibration"], directory / "calibration.png")
    written += [
        directory / n
        for n in (
            "confusion_matrix.png",
            "feature_importance.png",
            "anomaly_scores.png",
            "calibration.png",
        )
    ]
    return written
