"""Settings: persisted preferences, data management and database maintenance."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
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
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.content.addLayout(grid)
        self.content.addStretch(1)

        for combo in (
            self.theme_combo,
            self.units_combo,
            self.log_level_combo,
            self.sensitivity_combo,
        ):
            combo.currentIndexChanged.connect(lambda _i: self._save())
        for spin in (
            self.refresh_spin,
            self.history_spin,
            self.stale_spin,
            self.retention_spin,
            self.backups_spin,
            self.inference_spin,
            self.persistence_spin,
            self.cooldown_spin,
        ):
            spin.valueChanged.connect(lambda _v: self._save())
        for check in (
            self.animations_check,
            self.keep_forever_check,
            self.redact_check,
            self.diagnostics_check,
            self.ml_check,
        ):
            check.toggled.connect(lambda _c: self._save())
        self.backup_button.clicked.connect(lambda: self.backup())
        self.backup_as_button.clicked.connect(self._backup_as)
        self.restore_button.clicked.connect(self._restore_dialog)
        self.open_folder_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ctx.app.paths.data_dir)))
        )
        self.reset_button.clicked.connect(self.reset_preferences)
        ctx.state.settings_changed.connect(lambda _s: self.load())
        self.load()

    def load(self) -> None:
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
        except ValidationError as exc:
            self.ctx.notifier.notify(
                f"Invalid setting: {exc.errors()[0]['msg']}", StatusLevel.WARNING
            )
            self.load()
            return
        self.ctx.monitoring.set_interval(s.monitoring.refresh_interval_ms)
        self.ctx.theme.set_preference(s.appearance.theme)
        self._persist()

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
