"""Settings: persisted preferences, data management and database maintenance."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
)

from smartdrive.config.constants import ThemePreference, UnitSystem
from smartdrive.config.settings import AppSettings
from smartdrive.services.backup_service import BackupService
from smartdrive.ui.context import UiContext
from smartdrive.ui.dialogs import confirm as confirm_dialogs
from smartdrive.ui.pages.base import Page
from smartdrive.ui.widgets.base import IconPushButton, combo_enum, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.status import StatusLevel
from smartdrive.utils.exceptions import SmartDriveError

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def copy_settings(target: AppSettings, source: AppSettings) -> None:
    """Replace every section in place so objects holding ``target`` see the new values."""
    for name in AppSettings.model_fields:
        setattr(target, name, getattr(source, name))


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(10)
    return form


class SettingsPage(Page):
    key = "settings"
    title = "Settings"
    subtitle = "Preferences are saved automatically"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self._loading = False
        self.backups = BackupService(ctx.app.database, ctx.app.paths, ctx.app.settings)
        grid = QGridLayout()
        grid.setSpacing(16)

        appearance = Card("Appearance")
        form = _form()
        self.theme_combo = QComboBox()
        for preference, text in (
            (ThemePreference.DARK, "Dark"),
            (ThemePreference.LIGHT, "Light"),
            (ThemePreference.SYSTEM, "Follow system"),
        ):
            self.theme_combo.addItem(text, preference)
        self.animations_check = QCheckBox("Enable lightweight animations")
        self.units_combo = QComboBox()
        self.units_combo.addItem("Metric (°C, km/h, kPa)", UnitSystem.METRIC)
        self.units_combo.addItem("Imperial (°F, mph, psi)", UnitSystem.IMPERIAL)
        form.addRow("Theme", self.theme_combo)
        form.addRow("Units", self.units_combo)
        form.addRow("", self.animations_check)
        appearance.body.addLayout(form)
        grid.addWidget(appearance, 0, 0)

        monitoring = Card("Monitoring")
        form = _form()
        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(100, 10_000)
        self.refresh_spin.setSingleStep(100)
        self.refresh_spin.setSuffix(" ms")
        self.history_spin = QSpinBox()
        self.history_spin.setRange(30, 3600)
        self.history_spin.setSingleStep(30)
        self.history_spin.setSuffix(" s")
        self.stale_spin = QSpinBox()
        self.stale_spin.setRange(1, 60)
        self.stale_spin.setSuffix(" s")
        form.addRow("Refresh interval", self.refresh_spin)
        form.addRow("Chart history kept in memory", self.history_spin)
        form.addRow("Mark data stale after", self.stale_spin)
        monitoring.body.addLayout(form)
        grid.addWidget(monitoring, 0, 1)

        data = Card("Data and privacy")
        form = _form()
        retention_row = QHBoxLayout()
        self.keep_forever_check = QCheckBox("Keep forever")
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 3650)
        self.retention_spin.setSuffix(" days")
        retention_row.addWidget(self.retention_spin, 1)
        retention_row.addWidget(self.keep_forever_check)
        self.backups_spin = QSpinBox()
        self.backups_spin.setRange(1, 50)
        self.redact_check = QCheckBox("Mask VINs and registration numbers in log files")
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(LOG_LEVELS)
        form.addRow("Recorded session retention", retention_row)
        form.addRow("Automatic backups to keep", self.backups_spin)
        form.addRow("Log level", self.log_level_combo)
        form.addRow("", self.redact_check)
        data.body.addLayout(form)
        data.body.addWidget(
            label(
                "All data stays on this computer. SmartDrive makes no network connections.",
                "muted",
                wrap=True,
            )
        )
        grid.addWidget(data, 1, 0)

        database = Card("Database")
        self.location_label = label(str(ctx.app.paths.data_dir), "muted", wrap=True)
        database.body.addWidget(label("Application data folder"))
        database.body.addWidget(self.location_label)
        buttons = QHBoxLayout()
        self.backup_button = IconPushButton("Back up now", "database")
        self.backup_as_button = IconPushButton("Back up to…", "folder")
        self.restore_button = IconPushButton("Restore…", "refresh", variant="danger")
        self.open_folder_button = IconPushButton("Open folder", "folder", variant="ghost")
        for button in (
            self.backup_button,
            self.backup_as_button,
            self.restore_button,
            self.open_folder_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        database.body.addLayout(buttons)
        self.reset_button = IconPushButton("Reset preferences", "refresh", variant="ghost")
        database.body.addWidget(self.reset_button)
        grid.addWidget(database, 1, 1)

        diagnostics = Card("AI diagnostics")
        form = _form()
        self.diagnostics_check = QCheckBox("Run diagnostics while monitoring")
        self.ml_check = QCheckBox("Use machine-learning models (rules always run)")
        self.inference_spin = QSpinBox()
        self.inference_spin.setRange(1, 10)
        self.inference_spin.setSuffix(" s")
        self.sensitivity_combo = QComboBox()
        for value, text in (
            ("low", "Low (fewer alarms)"),
            ("standard", "Standard"),
            ("high", "High (more alarms)"),
        ):
            self.sensitivity_combo.addItem(text, value)
        self.persistence_spin = QSpinBox()
        self.persistence_spin.setRange(1, 20)
        self.persistence_spin.setSuffix(" analyses")
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(5, 3600)
        self.cooldown_spin.setSuffix(" s")
        form.addRow("", self.diagnostics_check)
        form.addRow("", self.ml_check)
        self.live_ml_check = QCheckBox("Also on live vehicle data (experimental)")
        self.live_ml_check.setToolTip(
            "The models were trained on simulated data only and abstain when the vehicle lacks "
            "the sensors they need. Rules always run."
        )
        form.addRow("", self.live_ml_check)
        form.addRow("Analyse every", self.inference_spin)
        form.addRow("Anomaly sensitivity", self.sensitivity_combo)
        form.addRow("Anomaly must persist for", self.persistence_spin)
        form.addRow("Alert cooldown", self.cooldown_spin)
        diagnostics.body.addLayout(form)
        diagnostics.body.addWidget(
            label(
                "Rule thresholds are conservative simulation defaults, not manufacturer "
                "specifications. They are stored in settings.json under diagnostics.thresholds.",
                "muted",
                wrap=True,
            )
        )
        grid.addWidget(diagnostics, 2, 0, 1, 2)

        connection = Card("Vehicle connection")
        form = _form()
        self.default_mode_combo = QComboBox()
        self.default_mode_combo.addItem("Simulator", "simulation")
        self.default_mode_combo.addItem("Live vehicle (OBD-II)", "live")
        self.connect_timeout_spin = QSpinBox()
        self.connect_timeout_spin.setRange(1, 120)
        self.connect_timeout_spin.setSuffix(" s")
        self.query_timeout_spin = QDoubleSpinBox()
        self.query_timeout_spin.setRange(0.2, 10.0)
        self.query_timeout_spin.setSingleStep(0.1)
        self.query_timeout_spin.setSuffix(" s")
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(250, 10_000)
        self.poll_spin.setSingleStep(250)
        self.poll_spin.setSuffix(" ms")
        self.reconnect_spin = QSpinBox()
        self.reconnect_spin.setRange(0, 10)
        self.reconnect_spin.setSpecialValueText("Do not reconnect")
        self.reconnect_spin.setSuffix(" attempts")
        self.reconnect_delay_spin = QDoubleSpinBox()
        self.reconnect_delay_spin.setRange(0.5, 60.0)
        self.reconnect_delay_spin.setSuffix(" s (doubles each attempt)")
        self.freeze_frame_check = QCheckBox("Read freeze-frame data when scanning codes")
        self.mock_check = QCheckBox("Show the mock adapter (developer testing; data is simulated)")
        self.mock_profile_combo = QComboBox()
        for value, text in (
            ("healthy", "Healthy vehicle"),
            ("stored_codes", "Stored and pending codes"),
            ("partial_sensors", "Partial sensor support"),
            ("no_ecu", "Ignition off (no ECU reply)"),
            ("legacy_protocol", "Older protocol"),
        ):
            self.mock_profile_combo.addItem(text, value)
        form.addRow("Default monitoring source", self.default_mode_combo)
        form.addRow("Connection timeout", self.connect_timeout_spin)
        form.addRow("Response timeout", self.query_timeout_spin)
        form.addRow("Poll the vehicle every", self.poll_spin)
        form.addRow("After a lost connection", self.reconnect_spin)
        form.addRow("First retry after", self.reconnect_delay_spin)
        form.addRow("", self.freeze_frame_check)
        form.addRow("", self.mock_check)
        form.addRow("Mock adapter behaviour", self.mock_profile_combo)
        connection.body.addLayout(form)
        connection.body.addWidget(
            label(
                "SmartDrive never connects to an adapter on its own: choose the port and press "
                "Connect on the Vehicle Connection page. Changes apply to the next connection.",
                "muted",
                wrap=True,
            )
        )
        grid.addWidget(connection, 3, 0)

        notifications = Card("Notifications and voice")
        form = _form()
        self.desktop_check = QCheckBox("Desktop notifications (where the system supports them)")
        self.sound_check = QCheckBox("Play a sound for warnings and critical findings")
        self.notify_cooldown_spin = QSpinBox()
        self.notify_cooldown_spin.setRange(10, 86_400)
        self.notify_cooldown_spin.setSuffix(" s")
        self.notify_retention_spin = QSpinBox()
        self.notify_retention_spin.setRange(1, 3650)
        self.notify_retention_spin.setSuffix(" days")
        self.voice_check = QCheckBox("Offline voice announcements")
        self.voice_warning_check = QCheckBox("Announce warnings")
        self.voice_critical_check = QCheckBox("Announce critical findings")
        self.voice_maintenance_check = QCheckBox("Announce maintenance reminders")
        self.voice_combo = QComboBox()
        self.voice_combo.setAccessibleName("Voice")
        self.voice_rate_spin = QSpinBox()
        self.voice_rate_spin.setRange(80, 300)
        self.voice_rate_spin.setSuffix(" words/min")
        self.voice_volume_spin = QSpinBox()
        self.voice_volume_spin.setRange(0, 100)
        self.voice_volume_spin.setSuffix(" %")
        self.voice_cooldown_spin = QSpinBox()
        self.voice_cooldown_spin.setRange(30, 86_400)
        self.voice_cooldown_spin.setSuffix(" s")
        self.test_voice_button = IconPushButton("Test voice", "play")
        self.voice_status = label("", "muted", wrap=True)
        form.addRow("", self.desktop_check)
        form.addRow("", self.sound_check)
        form.addRow("Repeat a notification after", self.notify_cooldown_spin)
        form.addRow("Keep read notifications", self.notify_retention_spin)
        form.addRow("", self.voice_check)
        form.addRow("", self.voice_warning_check)
        form.addRow("", self.voice_critical_check)
        form.addRow("", self.voice_maintenance_check)
        form.addRow("Voice", self.voice_combo)
        form.addRow("Speech rate", self.voice_rate_spin)
        form.addRow("Volume", self.voice_volume_spin)
        form.addRow("Repeat the same announcement after", self.voice_cooldown_spin)
        form.addRow(self.test_voice_button, self.voice_status)
        notifications.body.addLayout(form)
        notifications.body.addWidget(
            label(
                "Voice and desktop notifications supplement the screen; they are not a safety "
                "warning system and delivery is not guaranteed. Announcements never include "
                "vehicle identifiers.",
                "muted",
                wrap=True,
            )
        )
        grid.addWidget(notifications, 3, 1)

        records = Card("Trips, maintenance and reports")
        form = _form()
        self.record_default_check = QCheckBox("Record sessions by default")
        self.trip_prefix_edit = QLineEdit()
        self.trip_prefix_edit.setMaxLength(40)
        self.trip_prefix_edit.setAccessibleName("Trip name prefix")
        self.trip_prefix_edit.setPlaceholderText("Trip")
        self.currency_edit = QComboBox()
        self.currency_edit.setEditable(True)
        self.currency_edit.setAccessibleName("Default currency")
        for code in ("LKR", "USD", "EUR", "GBP", "INR", "AUD", "JPY"):
            self.currency_edit.addItem(code)
        self.reminders_check = QCheckBox(
            "Maintenance reminders (each schedule sets how early it reminds you)"
        )
        self.odometer_stale_spin = QSpinBox()
        self.odometer_stale_spin.setRange(1, 3650)
        self.odometer_stale_spin.setSuffix(" days")
        self.identifiers_check = QCheckBox("Include registration number and VIN in reports")
        self.notes_check = QCheckBox("Include the vehicle's garage notes in reports")
        form.addRow("", self.record_default_check)
        form.addRow("New trips are named", self.trip_prefix_edit)
        form.addRow("Default currency", self.currency_edit)
        form.addRow("", self.reminders_check)
        form.addRow("Odometer reading is out of date after", self.odometer_stale_spin)
        form.addRow("", self.identifiers_check)
        form.addRow("", self.notes_check)
        records.body.addLayout(form)
        grid.addWidget(records, 4, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.content.addLayout(grid)
        self.content.addStretch(1)

        for combo in (
            self.theme_combo,
            self.units_combo,
            self.log_level_combo,
            self.sensitivity_combo,
            self.default_mode_combo,
            self.mock_profile_combo,
            self.voice_combo,
        ):
            combo.currentIndexChanged.connect(self._on_changed)
        self.currency_edit.activated.connect(self._on_changed)
        line_edit = self.currency_edit.lineEdit()
        if line_edit is not None:
            line_edit.editingFinished.connect(self._save)
        self.trip_prefix_edit.editingFinished.connect(self._save)
        for spin in (
            self.refresh_spin,
            self.history_spin,
            self.stale_spin,
            self.retention_spin,
            self.backups_spin,
            self.inference_spin,
            self.persistence_spin,
            self.cooldown_spin,
            self.connect_timeout_spin,
            self.query_timeout_spin,
            self.poll_spin,
            self.reconnect_spin,
            self.reconnect_delay_spin,
            self.notify_cooldown_spin,
            self.notify_retention_spin,
            self.voice_rate_spin,
            self.voice_volume_spin,
            self.voice_cooldown_spin,
            self.odometer_stale_spin,
        ):
            spin.valueChanged.connect(self._on_changed)
        for check in (
            self.animations_check,
            self.keep_forever_check,
            self.redact_check,
            self.diagnostics_check,
            self.ml_check,
            self.live_ml_check,
            self.freeze_frame_check,
            self.mock_check,
            self.desktop_check,
            self.sound_check,
            self.voice_check,
            self.voice_warning_check,
            self.voice_critical_check,
            self.voice_maintenance_check,
            self.record_default_check,
            self.reminders_check,
            self.identifiers_check,
            self.notes_check,
        ):
            check.toggled.connect(self._on_changed)
        self.test_voice_button.clicked.connect(self._test_voice)
        ctx.notifications.voice_ready.connect(self._on_voice_ready)
        ctx.notifications.voice_failed.connect(self._on_voice_failed)
        self.backup_button.clicked.connect(self._backup_default)
        self.backup_as_button.clicked.connect(self._backup_as)
        self.restore_button.clicked.connect(self._restore_dialog)
        self.open_folder_button.clicked.connect(self._open_data_folder)
        self.reset_button.clicked.connect(self.reset_preferences)
        ctx.state.settings_changed.connect(self.load)
        self.load()

    def load(self, *_args: object) -> None:
        self._loading = True
        s = self.ctx.app.settings
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(s.appearance.theme))
        self.units_combo.setCurrentIndex(self.units_combo.findData(s.units.system))
        self.animations_check.setChecked(s.appearance.animations_enabled)
        self.refresh_spin.setValue(s.monitoring.refresh_interval_ms)
        self.history_spin.setValue(s.monitoring.chart_history_seconds)
        self.stale_spin.setValue(round(s.monitoring.stale_after_seconds))
        days = s.retention.telemetry_retention_days
        self.keep_forever_check.setChecked(days is None)
        self.retention_spin.setEnabled(days is not None)
        self.retention_spin.setValue(days or 365)
        self.backups_spin.setValue(s.retention.keep_backups)
        self.redact_check.setChecked(s.privacy.redact_identifiers_in_logs)
        self.log_level_combo.setCurrentText(s.logging.level)
        d = s.diagnostics
        self.diagnostics_check.setChecked(d.enabled)
        self.ml_check.setChecked(d.machine_learning_enabled)
        self.inference_spin.setValue(round(d.inference_interval_s))
        self.sensitivity_combo.setCurrentIndex(
            self.sensitivity_combo.findData(d.anomaly_sensitivity)
        )
        self.persistence_spin.setValue(d.anomaly_persistence_windows)
        self.cooldown_spin.setValue(s.alerts.cooldown_seconds)
        self.live_ml_check.setChecked(d.live_ml_enabled)
        o = s.obd
        self.default_mode_combo.setCurrentIndex(
            self.default_mode_combo.findData(s.monitoring.default_mode)
        )
        self.connect_timeout_spin.setValue(round(o.connection_timeout_seconds))
        self.query_timeout_spin.setValue(o.query_timeout_seconds)
        self.poll_spin.setValue(o.poll_interval_ms)
        self.reconnect_spin.setValue(o.max_reconnect_attempts)
        self.reconnect_delay_spin.setValue(o.reconnect_initial_delay_seconds)
        self.freeze_frame_check.setChecked(o.read_freeze_frame)
        self.mock_check.setChecked(o.show_mock_adapter)
        self.mock_profile_combo.setCurrentIndex(self.mock_profile_combo.findData(o.mock_profile))
        self.mock_profile_combo.setEnabled(o.show_mock_adapter)
        a = s.alerts
        self.desktop_check.setChecked(a.desktop_notifications)
        self.sound_check.setChecked(a.notification_sounds)
        self.notify_cooldown_spin.setValue(a.notification_cooldown_seconds)
        self.notify_retention_spin.setValue(a.notification_retention_days)
        self.voice_check.setChecked(a.voice_notifications)
        self.voice_warning_check.setChecked(a.voice_warnings)
        self.voice_critical_check.setChecked(a.voice_critical)
        self.voice_maintenance_check.setChecked(a.voice_maintenance)
        self.voice_rate_spin.setValue(a.voice_rate)
        self.voice_volume_spin.setValue(round(a.voice_volume * 100))
        self.voice_cooldown_spin.setValue(a.voice_cooldown_seconds)
        self._load_voices()
        for widget in (
            self.voice_warning_check,
            self.voice_critical_check,
            self.voice_maintenance_check,
            self.voice_combo,
            self.voice_rate_spin,
            self.voice_volume_spin,
            self.voice_cooldown_spin,
        ):
            widget.setEnabled(a.voice_notifications)
        self.record_default_check.setChecked(s.trips.record_by_default)
        self.trip_prefix_edit.setText(s.trips.name_prefix)
        m = s.maintenance
        self.currency_edit.setCurrentText(m.currency)
        self.reminders_check.setChecked(m.reminders_enabled)
        self.odometer_stale_spin.setValue(m.odometer_stale_days)
        self.identifiers_check.setChecked(s.reports.include_identifiers)
        self.notes_check.setChecked(s.reports.include_notes)
        self._loading = False

    def _save(self) -> None:
        if self._loading:
            return
        s = self.ctx.app.settings
        try:
            theme = combo_enum(self.theme_combo, ThemePreference)
            units = combo_enum(self.units_combo, UnitSystem)
            if theme is not None:
                s.appearance.theme = theme
            if units is not None:
                s.units.system = units
            s.appearance.animations_enabled = self.animations_check.isChecked()
            s.monitoring.refresh_interval_ms = self.refresh_spin.value()
            s.monitoring.chart_history_seconds = self.history_spin.value()
            s.monitoring.stale_after_seconds = float(self.stale_spin.value())
            self.retention_spin.setEnabled(not self.keep_forever_check.isChecked())
            s.retention.telemetry_retention_days = (
                None if self.keep_forever_check.isChecked() else self.retention_spin.value()
            )
            s.retention.keep_backups = self.backups_spin.value()
            s.privacy.redact_identifiers_in_logs = self.redact_check.isChecked()
            s.logging.level = self.log_level_combo.currentText()  # type: ignore[assignment]
            d = s.diagnostics
            d.enabled = self.diagnostics_check.isChecked()
            d.machine_learning_enabled = self.ml_check.isChecked()
            d.inference_interval_s = float(self.inference_spin.value())
            d.anomaly_sensitivity = str(self.sensitivity_combo.currentData())  # type: ignore[assignment]
            d.anomaly_persistence_windows = self.persistence_spin.value()
            s.alerts.cooldown_seconds = self.cooldown_spin.value()
            d.live_ml_enabled = self.live_ml_check.isChecked()
            mode = str(self.default_mode_combo.currentData())
            s.monitoring.default_mode = mode  # type: ignore[assignment]
            o = s.obd
            o.connection_timeout_seconds = float(self.connect_timeout_spin.value())
            o.query_timeout_seconds = self.query_timeout_spin.value()
            o.poll_interval_ms = self.poll_spin.value()
            o.max_reconnect_attempts = self.reconnect_spin.value()
            o.reconnect_initial_delay_seconds = self.reconnect_delay_spin.value()
            o.read_freeze_frame = self.freeze_frame_check.isChecked()
            o.show_mock_adapter = self.mock_check.isChecked()
            o.mock_profile = str(self.mock_profile_combo.currentData())  # type: ignore[assignment]
            a = s.alerts
            a.desktop_notifications = self.desktop_check.isChecked()
            a.notification_sounds = self.sound_check.isChecked()
            a.notification_cooldown_seconds = self.notify_cooldown_spin.value()
            a.notification_retention_days = self.notify_retention_spin.value()
            a.voice_notifications = self.voice_check.isChecked()
            a.voice_warnings = self.voice_warning_check.isChecked()
            a.voice_critical = self.voice_critical_check.isChecked()
            a.voice_maintenance = self.voice_maintenance_check.isChecked()
            a.voice_id = self.voice_combo.currentData() or None
            a.voice_rate = self.voice_rate_spin.value()
            a.voice_volume = self.voice_volume_spin.value() / 100.0
            a.voice_cooldown_seconds = self.voice_cooldown_spin.value()
            s.trips.record_by_default = self.record_default_check.isChecked()
            s.trips.name_prefix = self.trip_prefix_edit.text().strip() or "Trip"
            m = s.maintenance
            m.currency = self.currency_edit.currentText().strip().upper()
            m.reminders_enabled = self.reminders_check.isChecked()
            m.odometer_stale_days = self.odometer_stale_spin.value()
            s.reports.include_identifiers = self.identifiers_check.isChecked()
            s.reports.include_notes = self.notes_check.isChecked()
            if mode != self.ctx.monitoring.preferred_mode and not self.ctx.monitoring.is_active:
                self.ctx.monitoring.set_preferred_mode(mode)
        except ValidationError as exc:
            self.ctx.notifier.notify(
                f"Invalid setting: {exc.errors()[0]['msg']}", StatusLevel.WARNING
            )
            self.load()
            return
        self.ctx.monitoring.set_interval(s.monitoring.refresh_interval_ms)
        self.ctx.theme.set_preference(s.appearance.theme)
        self._persist()

    def _on_changed(self, *_: object) -> None:
        self._save()

    def _backup_default(self) -> None:
        self.backup()

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.app.paths.data_dir)))

    def _load_voices(self) -> None:
        notifications = self.ctx.notifications
        wanted = self.ctx.app.settings.alerts.voice_id
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        self.voice_combo.addItem("System default", None)
        for voice in notifications.voices:
            self.voice_combo.addItem(voice.name, voice.voice_id)
        index = self.voice_combo.findData(wanted)
        self.voice_combo.setCurrentIndex(max(0, index))
        self.voice_combo.blockSignals(False)
        if notifications.voice_available is None:
            self.voice_status.setText("Checking for an offline speech engine…")
        elif notifications.voice_available:
            self.voice_status.setText(f"{len(notifications.voices)} offline voice(s) available.")
        else:
            self.voice_status.setText(notifications.voice_unavailable_reason)
        self.test_voice_button.setEnabled(bool(notifications.voice_available))

    def _on_voice_ready(self, _available: bool, _reason: str) -> None:
        was_loading = self._loading
        self._loading = True
        self._load_voices()
        self._loading = was_loading

    def _on_voice_failed(self, message: str) -> None:
        self.voice_status.setText(message)

    def _test_voice(self) -> None:
        self.voice_status.setText("Speaking…")
        self.ctx.notifications.test_voice()

    def _persist(self) -> None:
        try:
            self.ctx.state.save_settings()
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)

    def reset_preferences(self) -> None:
        if not confirm_dialogs.confirm(
            self,
            "Reset preferences?",
            "All preferences return to their defaults. Vehicles and recorded data are not "
            "affected.",
            confirm_text="Reset",
            palette=self.ctx.theme.palette,
        ):
            return
        copy_settings(self.ctx.app.settings, AppSettings())
        self.ctx.theme.set_preference(self.ctx.app.settings.appearance.theme)
        self.ctx.monitoring.set_interval(self.ctx.app.settings.monitoring.refresh_interval_ms)
        self._persist()
        self.ctx.notifier.notify("Preferences reset to defaults.", StatusLevel.NORMAL)

    def backup(self, destination: Path | None = None) -> Path | None:
        try:
            path = self.backups.backup(destination)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return None
        self.ctx.notifier.notify(f"Backup written: {path.name}", StatusLevel.NORMAL)
        return path

    def _backup_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save database backup",
            str(self.backups.default_directory / "smartdrive-backup.db"),
            "SQLite database (*.db)",
        )
        if path:
            self.backup(Path(path))

    def _restore_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Restore database backup",
            str(self.backups.default_directory),
            "SQLite database (*.db)",
        )
        if path:
            self.restore(Path(path))

    def restore(self, source: Path) -> bool:
        if self.ctx.monitoring.is_active:
            self.ctx.notifier.notify(
                "Stop monitoring before restoring a backup.", StatusLevel.WARNING
            )
            return False
        if not confirm_dialogs.confirm(
            self,
            "Restore this backup?",
            f"The current database will be replaced by {source.name}. A safety copy of the "
            "current database is saved first so this can be undone.",
            confirm_text="Restore",
            destructive=True,
            palette=self.ctx.theme.palette,
        ):
            return False
        try:
            safety = self.backups.restore(source)
        except SmartDriveError as exc:
            self.ctx.notifier.notify(exc.user_message, StatusLevel.CRITICAL)
            return False
        self.ctx.state.reload()
        self.ctx.notifier.notify(
            f"Database restored. Previous data saved as {safety.name}.", StatusLevel.NORMAL
        )
        return True
