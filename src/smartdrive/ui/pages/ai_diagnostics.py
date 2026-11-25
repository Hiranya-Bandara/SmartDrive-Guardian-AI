"""AI Diagnostics: hybrid assessment, model output, explanations, health score and history.

Everything shown here comes from a real assessment produced by the inference worker or from
stored history. When no assessment exists the page says why instead of showing example values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smartdrive.ai.dataset import LABELS
from smartdrive.ai.features import describe_feature
from smartdrive.ai.model_registry import ANOMALY_NAME, CLASSIFIER_NAME, LoadStatus
from smartdrive.config.constants import DataSource, DiagnosticSource, FaultCategory, Severity
from smartdrive.core.health_score import EXPERIMENTAL_NOTE
from smartdrive.core.units import MISSING_TEXT
from smartdrive.database.repositories.diagnostic_repository import DiagnosticHistoryEntry
from smartdrive.models.diagnostic import (
    SEVERITY_RANK,
    DiagnosticAssessment,
    DiagnosticStatus,
    Explanation,
    LabelState,
    ModelRunStatus,
)
from smartdrive.ui.context import UiContext
from smartdrive.ui.monitoring_controller import MonitoringState
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label, set_props
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.charts import ChartContainer
from smartdrive.ui.widgets.diagnostic_card import (
    SOURCE_TEXT,
    FindingCard,
    format_evidence,
    severity_text,
)
from smartdrive.ui.widgets.explanation_chart import BarChart
from smartdrive.ui.widgets.health_score import HealthScoreWidget
from smartdrive.ui.widgets.monitoring_controls import MonitoringControls, toggle_monitoring
from smartdrive.ui.widgets.notifications import Banner
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel

PAGE_NOTICE: Final = (
    "Experimental diagnostics. The models were trained and evaluated only on simulated data; "
    "findings are indications to check, not confirmed mechanical faults, and no finding does "
    "not mean the vehicle is safe to drive."
)
HISTORY_COLUMNS: Final = (
    "Time",
    "Severity",
    "Source",
    "Category",
    "Finding",
    "Mode",
    "Session",
    "Model",
)
TOP_CONTRIBUTIONS: Final = 10
TOP_IMPORTANCE: Final = 12
HISTORY_REFRESH_MS: Final = 5000

STATUS_DISPLAY: Final[dict[DiagnosticStatus, tuple[str, StatusLevel]]] = {
    DiagnosticStatus.CRITICAL: ("Critical finding", StatusLevel.CRITICAL),
    DiagnosticStatus.WARNING: ("Warning", StatusLevel.WARNING),
    DiagnosticStatus.INFORMATION: ("Information", StatusLevel.INFO),
    DiagnosticStatus.NO_ABNORMALITY: ("No abnormality detected", StatusLevel.NORMAL),
    DiagnosticStatus.INSUFFICIENT_DATA: ("Insufficient data", StatusLevel.OFFLINE),
    DiagnosticStatus.STALE: ("Telemetry stale", StatusLevel.WARNING),
}
MODEL_STATUS_TEXT: Final[dict[LoadStatus, tuple[str, StatusLevel]]] = {
    LoadStatus.AVAILABLE: ("available", StatusLevel.NORMAL),
    LoadStatus.MISSING: ("unavailable", StatusLevel.OFFLINE),
    LoadStatus.INTEGRITY_FAILED: ("integrity check failed", StatusLevel.CRITICAL),
    LoadStatus.INCOMPATIBLE: ("incompatible", StatusLevel.WARNING),
    LoadStatus.LOAD_FAILED: ("failed to load", StatusLevel.CRITICAL),
}
RUN_STATUS_TEXT: Final[dict[ModelRunStatus, str]] = {
    ModelRunStatus.OK: "Ran normally",
    ModelRunStatus.ABSTAINED: "Abstained",
    ModelRunStatus.UNAVAILABLE: "Model unavailable",
    ModelRunStatus.INCOMPATIBLE: "Model incompatible",
    ModelRunStatus.FAILED: "Inference failed",
    ModelRunStatus.DISABLED: "Turned off in settings",
}


def category_text(category: FaultCategory | str) -> str:
    value = category.value if isinstance(category, FaultCategory) else category
    return {"unknown_anomaly": "Unusual pattern"}.get(value, value.replace("_", " ").title())


def model_status_pill(ctx: UiContext, name: str, title: str) -> tuple[str, StatusLevel]:
    controller = ctx.diagnostics
    if controller.models_loading:
        return f"{title}: loading", StatusLevel.INFO
    status = controller.model_status(name)
    if status is None:
        return f"{title}: unavailable", StatusLevel.OFFLINE
    text, level = MODEL_STATUS_TEXT[status]
    return f"{title}: {text}", level


def format_time(moment: datetime | None) -> str:
    if moment is None:
        return "Never"
    return moment.astimezone().strftime("%H:%M:%S")


def explanation_summary(explanation: Explanation, values: dict[str, float]) -> str:
    supporting = ", ".join(describe_feature(c.feature) for c in explanation.supporting(3))
    opposing = ", ".join(describe_feature(c.feature) for c in explanation.opposing(3))
    lines = [
        f"Model output {explanation.probability:.2f} = average training output "
        f"{explanation.base_value:.2f} + the sum of the feature contributions shown.",
        f"Pushing towards this category: {supporting or 'none'}.",
        f"Pushing against it: {opposing or 'none'}.",
    ]
    readings = [
        f"{describe_feature(c.feature)} = {values[c.feature]:.3g}"
        for c in explanation.supporting(3)
        if c.feature in values
    ]
    if readings:
        lines.append("Relevant values: " + "; ".join(readings) + ".")
    return "\n".join(lines)


class ProbabilityRow(QWidget):
    def __init__(self, category: FaultCategory) -> None:
        super().__init__()
        self.category = category
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        name = label(category_text(category))
        name.setMinimumWidth(110)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setAccessibleName(f"{category_text(category)} model output")
        self.text = label(MISSING_TEXT, "muted")
        self.text.setMinimumWidth(230)
        layout.addWidget(name)
        layout.addWidget(self.bar, 1)
        layout.addWidget(self.text)

    def set_prediction(
        self, probability: float | None, threshold: float | None, state: str
    ) -> None:
        if probability is None:
            self.bar.setValue(0)
            self.text.setText(state)
            set_props(self.bar, level="")
            return
        self.bar.setValue(round(probability * 100))
        self.text.setText(f"{probability:.2f} (threshold {threshold:.2f}) · {state}")
        level = {"Positive": "critical", "Uncertain": "warning"}.get(state, "")
        set_props(self.bar, level=level)


class AiDiagnosticsPage(Page):
    key = "diagnostics"
    title = "AI Diagnostics"
    subtitle = "Hybrid rule-based and machine-learning assessment (experimental)"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._history: list[DiagnosticHistoryEntry] = []
        self._history_dirty = True
        self.content.addWidget(Banner(PAGE_NOTICE, StatusLevel.WARNING))

        # -- overview --------------------------------------------------------------------------
        overview = Card("Diagnostic overview")
        row = QHBoxLayout()
        row.setSpacing(18)
        self.health_widget = HealthScoreWidget()
        row.addWidget(self.health_widget, 0, Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(8)
        pills = QHBoxLayout()
        self.status_pill = StatusIndicator(prefix="Status: ")
        self.mode_pill = StatusIndicator(prefix="Mode: ")
        pills.addWidget(self.status_pill)
        pills.addWidget(self.mode_pill)
        pills.addStretch(1)
        model_pills = QHBoxLayout()
        self.classifier_pill = StatusIndicator()
        self.anomaly_pill = StatusIndicator()
        self.rules_pill = StatusIndicator("Rule engine: active", StatusLevel.NORMAL)
        for pill in (self.classifier_pill, self.anomaly_pill, self.rules_pill):
            model_pills.addWidget(pill)
        model_pills.addStretch(1)
        facts = QFormLayout()
        facts.setHorizontalSpacing(16)
        self.facts: dict[str, QLabel] = {}
        for key, title in (
            ("vehicle", "Active vehicle"),
            ("last", "Last inference"),
            ("latency", "Inference time"),
            ("completeness", "Data completeness"),
            ("warnings", "Active warnings"),
        ):
            value = label(MISSING_TEXT)
            self.facts[key] = value
            facts.addRow(label(title, "muted"), value)
        self.controls = MonitoringControls(ctx)
        info.addLayout(pills)
        info.addLayout(model_pills)
        info.addLayout(facts)
        info.addWidget(self.controls)
        row.addLayout(info, 2)
        components = QVBoxLayout()
        components.addWidget(label("Health score components", "card-title"))
        self.components_label = label("", wrap=True)
        self.health_note = label(EXPERIMENTAL_NOTE, "muted", wrap=True)
        components.addWidget(self.components_label)
        components.addStretch(1)
        components.addWidget(self.health_note)
        row.addLayout(components, 2)
        overview.body.addLayout(row)
        self.content.addWidget(overview)

        # -- findings and recommendations ------------------------------------------------------
        middle = QHBoxLayout()
        middle.setSpacing(16)
        findings_card = Card("Active findings")
        self.findings_widget = QWidget()
        self.findings_layout = QVBoxLayout(self.findings_widget)
        self.findings_layout.setContentsMargins(0, 0, 0, 0)
        self.findings_layout.setSpacing(10)
        self.findings_stack = StatefulStack(self.findings_widget)
        self.findings_stack.setMinimumHeight(220)
        findings_card.body.addWidget(self.findings_stack)
        middle.addWidget(findings_card, 3)
        recommendations = Card("Recommendations")
        self.recommendations_label = label("", wrap=True)
        recommendations.body.addWidget(self.recommendations_label)
        recommendations.body.addStretch(1)
        recommendations.body.addWidget(
            label(
                "Recommendations are cautious suggestions based on the available evidence. "
                "SmartDrive is not a replacement for a qualified mechanic.",
                "muted",
                wrap=True,
            )
        )
        middle.addWidget(recommendations, 2)
        self.content.addLayout(middle)

        # -- machine-learning results ----------------------------------------------------------
        ml_grid = QGridLayout()
        ml_grid.setSpacing(16)
        classifier_card = Card("Random Forest fault classifier")
        self.classifier_status = label("", "muted", wrap=True)
        classifier_card.body.addWidget(self.classifier_status)
        self.probability_rows = {c: ProbabilityRow(c) for c in LABELS}
        for probability_row in self.probability_rows.values():
            classifier_card.body.addWidget(probability_row)
        classifier_card.body.addWidget(
            label(
                "Bars show the model's output for each category. It is a score from a model "
                "trained on simulated data, not the probability that a component has failed.",
                "muted",
                wrap=True,
            )
        )
        ml_grid.addWidget(classifier_card, 0, 0)
        anomaly_card = Card("Isolation Forest anomaly detector")
        anomaly_form = QFormLayout()
        self.anomaly_values: dict[str, QLabel] = {}
        for key, title in (
            ("status", "Status"),
            ("score", "Anomaly score"),
            ("threshold", "Threshold"),
            ("streak", "Consecutive anomalous analyses"),
            ("version", "Model version"),
        ):
            value = label(MISSING_TEXT, wrap=True)
            self.anomaly_values[key] = value
            anomaly_form.addRow(label(title, "muted"), value)
        anomaly_card.body.addLayout(anomaly_form)
        anomaly_card.body.addWidget(
            label(
                "The score measures how unusual the last minute of telemetry is compared with "
                "normal simulated driving. It does not identify a cause and is not a failure "
                "probability.",
                "muted",
                wrap=True,
            )
        )
        anomaly_card.body.addStretch(1)
        ml_grid.addWidget(anomaly_card, 0, 1)
        ml_grid.setColumnStretch(0, 3)
        ml_grid.setColumnStretch(1, 2)
        self.content.addLayout(ml_grid)

        # -- explainability --------------------------------------------------------------------
        xai = QGridLayout()
        xai.setSpacing(16)
        explanation_card = Card("Why the model produced this output")
        selector = QHBoxLayout()
        selector.addWidget(label("Category", "muted"))
        self.explanation_combo = QComboBox()
        self.explanation_combo.setAccessibleName("Explained category")
        selector.addWidget(self.explanation_combo, 1)
        explanation_card.body.addLayout(selector)
        self.contribution_chart = BarChart(
            "Feature contributions to this prediction", "Contribution to model output"
        )
        self.explanation_stack = StatefulStack(self.contribution_chart)
        explanation_card.body.addWidget(self.explanation_stack)
        self.explanation_label = label("", wrap=True)
        explanation_card.body.addWidget(self.explanation_label)
        explanation_card.body.addWidget(
            label(
                "Method: exact tree-path decomposition of the Random Forest output (each tree's "
                "prediction split into a base value plus one change per decision node). Orange "
                "bars push towards the category, blue bars against it.",
                "muted",
                wrap=True,
            )
        )
        xai.addWidget(explanation_card, 0, 0)
        self.importance_chart = BarChart(
            "Global feature importance (whole model, not this prediction)",
            "Drop in validation macro-F1 when the feature is shuffled",
        )
        xai.addWidget(self.importance_chart, 0, 1)
        xai.setColumnStretch(0, 1)
        xai.setColumnStretch(1, 1)
        self.content.addLayout(xai)

        self.trend_chart = ChartContainer(
            "Health score during this monitoring run",
            "Score",
            x_label="Simulated time (s)",
            height=160,
        )
        self.trend_chart.add_curve("health", "Health score")
        self.content.addWidget(self.trend_chart)

        # -- history ---------------------------------------------------------------------------
        history_card = Card("Diagnostic history")
        filters = QHBoxLayout()
        self.severity_filter = QComboBox()
        self.severity_filter.setAccessibleName("Severity filter")
        self.severity_filter.addItem("All severities", None)
        for severity in (Severity.CRITICAL, Severity.WARNING, Severity.INFORMATION):
            self.severity_filter.addItem(severity.value.title(), severity)
        self.source_filter = QComboBox()
        self.source_filter.setAccessibleName("Source filter")
        self.source_filter.addItem("All sources", None)
        for source in (
            DiagnosticSource.RULE,
            DiagnosticSource.CLASSIFIER,
            DiagnosticSource.ANOMALY_DETECTOR,
        ):
            self.source_filter.addItem(SOURCE_TEXT[source], source)
        self.mode_filter = QComboBox()
        self.mode_filter.setAccessibleName("Operating mode filter")
        self.mode_filter.addItem("All modes", None)
        for mode in DataSource:
            self.mode_filter.addItem(mode.value.title(), mode)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search findings")
        self.search_edit.setAccessibleName("Search diagnostic history")
        self.search_edit.setClearButtonEnabled(True)
        self.refresh_button = IconPushButton("Refresh", "refresh", variant="ghost")
        for widget in (self.severity_filter, self.source_filter, self.mode_filter):
            filters.addWidget(widget)
        filters.addWidget(self.search_edit, 1)
        filters.addWidget(self.refresh_button)
        history_card.body.addLayout(filters)
        self.history_table = QTableWidget(0, len(HISTORY_COLUMNS))
        self.history_table.setHorizontalHeaderLabels(HISTORY_COLUMNS)
        self.history_table.verticalHeader().hide()
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setAccessibleName("Diagnostic history")
        self.history_table.setMinimumHeight(240)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.history_stack = StatefulStack(self.history_table)
        history_card.body.addWidget(self.history_stack)
        self.history_details = label("Select a finding to see its details.", "muted", wrap=True)
        self.history_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        history_card.body.addWidget(self.history_details)
        self.content.addWidget(history_card)

        diagnostics = ctx.diagnostics
        diagnostics.assessment_changed.connect(self._on_assessment)
        diagnostics.models_changed.connect(self.refresh_view)
        diagnostics.error_occurred.connect(lambda _e: self.refresh_view())
        ctx.monitoring.state_changed.connect(lambda _s: self.refresh_view())
        ctx.state.active_vehicle_changed.connect(lambda _v: self._mark_history())
        ctx.state.settings_changed.connect(lambda _s: self.refresh_view())
        self.explanation_combo.currentIndexChanged.connect(lambda _i: self._render_explanation())
        for combo in (self.severity_filter, self.source_filter, self.mode_filter):
            combo.currentIndexChanged.connect(lambda _i: self.reload_history())
        self.search_edit.textChanged.connect(lambda _t: self.reload_history())
        self.refresh_button.clicked.connect(self.reload_history)
        self.history_table.itemSelectionChanged.connect(self._show_history_details)
        self._history_timer = QTimer(self)
        self._history_timer.setInterval(HISTORY_REFRESH_MS)
        self._history_timer.timeout.connect(self._refresh_history_if_needed)
        self._history_timer.start()
        self.refresh_view()
        self.reload_history()

    # -- lifecycle ----------------------------------------------------------------------------

    def on_shown(self) -> None:
        self.refresh_view()
        self.reload_history()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._render_explanation()
        self._render_importance()

    def _on_assessment(self, _assessment: object) -> None:
        self._history_dirty = True
        if self.isVisible():
            self.refresh_view()

    def _mark_history(self) -> None:
        self._history_dirty = True
        self.refresh_view()

    def _refresh_history_if_needed(self) -> None:
        if self._history_dirty and self.isVisible():
            self.reload_history()

    # -- rendering ----------------------------------------------------------------------------

    def refresh_view(self) -> None:
        latest = self.ctx.diagnostics.latest
        self._render_overview(latest)
        self._render_findings(latest)
        self._render_classifier(latest)
        self._render_anomaly(latest)
        self._render_trend()
        self._refresh_explanation_choices(latest)
        self._render_importance()

    def _render_overview(self, latest: DiagnosticAssessment | None) -> None:
        ctx = self.ctx
        monitoring = ctx.monitoring
        vehicle = ctx.state.active_vehicle
        self.health_widget.set_health(latest.health if latest else None)
        if latest is not None:
            self.status_pill.set_status(*STATUS_DISPLAY[latest.status])
        else:
            self.status_pill.set_status(self._idle_status(), StatusLevel.OFFLINE)
        mode = monitoring.data_source.value.title() if monitoring.data_source else "Stopped"
        self.mode_pill.set_status(
            mode,
            StatusLevel.SIMULATION
            if monitoring.data_source is DataSource.SIMULATION
            else StatusLevel.OFFLINE,
        )
        self.classifier_pill.set_status(*model_status_pill(ctx, CLASSIFIER_NAME, "Classifier"))
        self.anomaly_pill.set_status(*model_status_pill(ctx, ANOMALY_NAME, "Anomaly detector"))
        self.facts["vehicle"].setText(
            vehicle.name if vehicle else "None selected — results are not saved to history"
        )
        self.facts["last"].setText(format_time(ctx.diagnostics.last_inference_at))
        self.facts["latency"].setText(f"{latest.inference_ms:.0f} ms" if latest else MISSING_TEXT)
        self.facts["completeness"].setText(
            f"{latest.quality.overall_completeness:.0%} of core sensors · "
            f"{latest.quality.coverage:.0%} of the last minute covered"
            if latest
            else MISSING_TEXT
        )
        self.facts["warnings"].setText(str(latest.warning_count) if latest else MISSING_TEXT)
        if latest is None or not latest.health.available:
            reason = latest.health.reason if latest else "No assessment yet."
            self.components_label.setText(reason)
        elif not latest.health.components:
            self.components_label.setText("No deductions: no findings in the current analysis.")
        else:
            self.components_label.setText(
                "\n".join(
                    f"−{c.penalty:.0f}  {c.name}: {c.explanation}" for c in latest.health.components
                )
            )
        text = (
            "\n".join(f"• {r}" for r in latest.recommendations)
            if latest
            else ("Recommendations appear once an assessment is available.")
        )
        self.recommendations_label.setText(text)

    def _idle_status(self) -> str:
        ctx = self.ctx
        if not ctx.app.settings.diagnostics.enabled:
            return "Diagnostics turned off"
        if ctx.diagnostics.models_loading:
            return "Loading models"
        if ctx.monitoring.state is MonitoringState.STOPPED:
            return "Monitoring stopped"
        if ctx.monitoring.state is MonitoringState.PAUSED:
            return "Monitoring paused"
        return "Collecting telemetry"

    def _render_findings(self, latest: DiagnosticAssessment | None) -> None:
        while self.findings_layout.count():
            item = self.findings_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        stack = self.findings_stack
        ctx = self.ctx
        if latest is None:
            error = ctx.diagnostics.last_error
            if not ctx.app.settings.diagnostics.enabled:
                stack.show_empty(
                    "Diagnostics are turned off",
                    "Turn diagnostics on in Settings to analyse telemetry.",
                )
            elif error and ctx.monitoring.is_active:
                stack.show_error("Inference failed", error, action_text=None)
            elif ctx.monitoring.state is MonitoringState.STOPPED:
                stack.show_empty(
                    "Monitoring stopped",
                    "Start monitoring to analyse telemetry. Diagnostics run in the background "
                    "every few seconds.",
                    action_text="Start monitoring",
                    action=lambda: toggle_monitoring(ctx),
                )
            elif ctx.diagnostics.models_loading:
                stack.show_loading("Loading models…", "Verifying the trusted model artifacts.")
            else:
                stack.show_loading(
                    "Collecting telemetry…",
                    "An assessment needs at least 20 seconds of readings in the last minute.",
                )
            return
        if latest.status is DiagnosticStatus.STALE:
            stack.show_error("Telemetry is stale", latest.health.reason, action_text=None)
            return
        if not latest.findings:
            if latest.status is DiagnosticStatus.INSUFFICIENT_DATA:
                stack.show_empty("Insufficient data", latest.quality.reason)
            else:
                stack.show_empty(
                    "No abnormality detected",
                    "No rule, model or anomaly finding in the current analysis. This is not "
                    "proof that the vehicle is safe to drive.",
                )
            return
        ordered = sorted(latest.findings, key=lambda f: SEVERITY_RANK[f.severity], reverse=True)
        for finding in ordered:
            card = FindingCard(finding)
            self.findings_layout.addWidget(card)
        self.findings_layout.addStretch(1)
        stack.show_content()

    def _render_classifier(self, latest: DiagnosticAssessment | None) -> None:
        if latest is None:
            self.classifier_status.setText("No assessment yet.")
            for row in self.probability_rows.values():
                row.set_prediction(None, None, MISSING_TEXT)
            return
        result = latest.classifier
        version = f" · model {result.model_version}" if result.model_version else ""
        detail = f" — {result.reason}" if result.reason else ""
        self.classifier_status.setText(f"{RUN_STATUS_TEXT[result.status]}{detail}{version}")
        labels = {p.category: p for p in result.labels}
        for category, row in self.probability_rows.items():
            prediction = labels.get(category)
            if prediction is None:
                row.set_prediction(None, None, "Not assessed")
                continue
            state = {
                LabelState.POSITIVE: "Positive",
                LabelState.UNCERTAIN: "Uncertain",
                LabelState.NEGATIVE: "Negative",
            }[prediction.state]
            row.set_prediction(prediction.probability, prediction.threshold, state)

    def _render_anomaly(self, latest: DiagnosticAssessment | None) -> None:
        values = self.anomaly_values
        if latest is None:
            for value in values.values():
                value.setText(MISSING_TEXT)
            return
        result = latest.anomaly
        state = RUN_STATUS_TEXT[result.status]
        if result.status is ModelRunStatus.OK:
            state = (
                "Persistent unusual pattern"
                if result.persistent
                else "Unusual reading (not yet persistent)"
                if result.is_anomalous
                else "Within the normal range"
            )
        if result.reason and result.status is not ModelRunStatus.OK:
            state += f" — {result.reason}"
        values["status"].setText(state)
        values["score"].setText(MISSING_TEXT if result.score is None else f"{result.score:.3f}")
        values["threshold"].setText(
            MISSING_TEXT
            if result.threshold is None
            else f"{result.threshold:.3f} ({self.ctx.app.settings.diagnostics.anomaly_sensitivity})"
        )
        values["streak"].setText(str(result.consecutive))
        values["version"].setText(result.model_version or MISSING_TEXT)

    def _render_trend(self) -> None:
        points = [(t, s) for t, s in self.ctx.diagnostics.live_trend]
        times = [t for t, _ in points]
        scores = [float("nan") if s is None else float(s) for _, s in points]
        self.trend_chart.set_data("health", times, scores)
        self.trend_chart.set_y_range(0, 100)

    # -- explanations -------------------------------------------------------------------------

    def _refresh_explanation_choices(self, latest: DiagnosticAssessment | None) -> None:
        current = self.explanation_combo.currentData()
        categories = list(latest.explanations) if latest else []
        self.explanation_combo.blockSignals(True)
        self.explanation_combo.clear()
        for category in categories:
            self.explanation_combo.addItem(category_text(category), category)
        index = self.explanation_combo.findData(current)
        self.explanation_combo.setCurrentIndex(index if index >= 0 else 0)
        self.explanation_combo.setEnabled(bool(categories))
        self.explanation_combo.blockSignals(False)
        self._render_explanation()

    def _render_explanation(self) -> None:
        latest = self.ctx.diagnostics.latest
        category = combo_enum(self.explanation_combo, FaultCategory)
        explanation = latest.explanations.get(category) if latest and category else None
        if explanation is None:
            self.contribution_chart.clear_bars()
            reason = (
                "Explanations appear when the classifier has run on sufficient data."
                if latest is None or latest.classifier.status is not ModelRunStatus.OK
                else "No explanation available for this assessment."
            )
            self.explanation_stack.show_empty("No prediction to explain", reason)
            self.explanation_label.setText("")
            return
        ranked = sorted(explanation.contributions, key=lambda c: abs(c.contribution), reverse=True)[
            :TOP_CONTRIBUTIONS
        ]
        self.contribution_chart.set_bars(
            [describe_feature(c.feature) for c in ranked], [c.contribution for c in ranked]
        )
        self.explanation_stack.show_content()
        values = {c.feature: c.value for c in explanation.contributions}
        self.explanation_label.setText(explanation_summary(explanation, values))

    def _render_importance(self) -> None:
        models = self.ctx.diagnostics.models
        importance: list[dict[str, Any]] = []
        if models is not None and models.classifier is not None:
            importance = list(models.manifest.get(CLASSIFIER_NAME, {}).get("global_importance", []))
        top = importance[:TOP_IMPORTANCE]
        self.importance_chart.set_bars(
            [describe_feature(str(i["feature"])) for i in top],
            [float(i["permutation_mean"]) for i in top],
        )

    # -- history ------------------------------------------------------------------------------

    def reload_history(self) -> None:
        self._history_dirty = False
        vehicle = self.ctx.state.active_vehicle
        severity = combo_enum(self.severity_filter, Severity)
        source = combo_enum(self.source_filter, DiagnosticSource)
        mode = combo_enum(self.mode_filter, DataSource)
        self._history = self.ctx.diagnostic_history.history(
            vehicle_id=vehicle.id if vehicle else None,
            severities=[severity] if severity else None,
            source=source,
            data_source=mode,
            search=self.search_edit.text(),
        )
        table = self.history_table
        table.setRowCount(len(self._history))
        for row, entry in enumerate(self._history):
            cells = (
                entry.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                severity_text(entry.severity),
                SOURCE_TEXT[entry.source],
                category_text(entry.category),
                entry.summary,
                entry.data_source.value.title() if entry.data_source else MISSING_TEXT,
                str(entry.session_id) if entry.session_id else MISSING_TEXT,
                entry.model_version or MISSING_TEXT,
            )
            for column, text in enumerate(cells):
                table.setItem(row, column, QTableWidgetItem(text))
        if self._history:
            self.history_stack.show_content()
        elif vehicle is None:
            self.history_stack.show_empty(
                "No vehicle selected",
                "Diagnostic history is saved for the active vehicle. Select one in the garage.",
            )
        else:
            self.history_stack.show_empty(
                "No diagnostic findings recorded",
                "Findings are saved here while monitoring runs with an active vehicle.",
            )
        self._show_history_details()

    def _show_history_details(self) -> None:
        rows = self.history_table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._history):
            self.history_details.setText("Select a finding to see its details.")
            return
        entry = self._history[rows[0].row()]
        detail = entry.explanation
        lines = [
            f"{severity_text(entry.severity)} · {SOURCE_TEXT[entry.source]} · "
            f"{entry.created_at.astimezone():%Y-%m-%d %H:%M:%S}",
            str(detail.get("text", "")),
        ]
        evidence = detail.get("evidence")
        if isinstance(evidence, dict) and evidence:
            lines.append(f"Evidence — {format_evidence(evidence)}")
        corroborated = detail.get("corroborated_by")
        if corroborated:
            lines.append(
                "Agrees with: " + ", ".join(SOURCE_TEXT[DiagnosticSource(s)] for s in corroborated)
            )
        if entry.confidence is not None:
            lines.append(f"Model output: {entry.confidence:.2f}")
        if entry.anomaly_score is not None:
            lines.append(f"Anomaly score: {entry.anomaly_score:.3f}")
        if entry.model_version:
            lines.append(f"Model version: {entry.model_version}")
        if entry.recommendation:
            lines.append("Recommendation at the time: " + entry.recommendation.replace("\n", " "))
        self.history_details.setText("\n".join(lines))
