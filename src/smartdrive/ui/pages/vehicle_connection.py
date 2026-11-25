"""Vehicle Connection: adapter discovery, read-only OBD-II connection, capabilities and quality.

Nothing here connects automatically. Every figure on the page comes from the adapter or the
vehicle (version string, protocol, supported PIDs, measured latency); when there is no adapter
the page shows setup guidance instead of placeholder readings.
"""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
)

from smartdrive.config.constants import DataSource
from smartdrive.obd.discovery import SerialPortInfo
from smartdrive.obd.pids import DATA_PIDS, NOT_AVAILABLE_OVER_OBD
from smartdrive.obd.session import ConnectionReport, ConnectionStatus, PollResult
from smartdrive.services.threshold_service import OVERRIDABLE
from smartdrive.ui.context import UiContext
from smartdrive.ui.pages.base import Page
from smartdrive.ui.themes.palette import ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, label
from smartdrive.ui.widgets.cards import Card
from smartdrive.ui.widgets.monitoring_controls import MonitoringControls
from smartdrive.ui.widgets.states import StatefulStack
from smartdrive.ui.widgets.status import StatusIndicator, StatusLevel
from smartdrive.ui.widgets.tables import MISSING, fill_table, local_time, make_table
from smartdrive.utils.exceptions import SmartDriveError

STATUS_LEVEL = {
    ConnectionStatus.DISCONNECTED: StatusLevel.OFFLINE,
    ConnectionStatus.DISCOVERING: StatusLevel.INFO,
    ConnectionStatus.CONNECTING: StatusLevel.INFO,
    ConnectionStatus.ADAPTER_CONNECTED: StatusLevel.WARNING,
    ConnectionStatus.ECU_CONNECTED: StatusLevel.NORMAL,
    ConnectionStatus.MONITORING: StatusLevel.NORMAL,
    ConnectionStatus.RECONNECTING: StatusLevel.WARNING,
    ConnectionStatus.FAILED: StatusLevel.CRITICAL,
    ConnectionStatus.DISCONNECTING: StatusLevel.INFO,
}
SENSOR_COLUMNS = ("Parameter", "PID", "Unit", "Vehicle support", "Latest value", "Last cycle")
THRESHOLD_LABELS = {
    "coolant_warning_c": ("Coolant warning", "°C"),
    "coolant_critical_c": ("Coolant critical", "°C"),
    "voltage_low_warning_v": ("Low voltage warning", "V"),
    "voltage_low_critical_v": ("Low voltage critical", "V"),
    "voltage_high_warning_v": ("High voltage warning", "V"),
}
SETUP_TEXT = (
    "1. With the vehicle parked safely and the ignition on (engine running or not), plug an "
    "ELM327-compatible adapter into the OBD-II port under the dashboard.\n"
    "2. USB adapters appear as a COM port. Bluetooth Classic adapters must first be paired in "
    "Windows Settings, which then creates an outgoing COM port.\n"
    "3. Press Refresh, choose the port and press Connect. SmartDrive only reads data; it cannot "
    "clear codes or change anything in the vehicle.\n"
    "Bluetooth Low Energy, Wi-Fi and manufacturer-specific adapters are not supported. Do not "
    "operate the application while driving."
)


def _value_text(value: float | None, unit: str) -> str:
    if value is None:
        return MISSING
    digits = 0 if abs(value) >= 100 else 1 if abs(value) >= 10 else 2
    return f"{value:.{digits}f} {unit}".strip()


def _duration(since: datetime | None) -> str:
    if since is None:
        return MISSING
    seconds = int((datetime.now(UTC) - since).total_seconds())
    hours, rest = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


class VehicleConnectionPage(Page):
    key = "connection"
    title = "Vehicle Connection"
    subtitle = "Read-only OBD-II connection through an ELM327-compatible adapter"

    def __init__(self, ctx: UiContext) -> None:
        super().__init__(ctx)
        self.connection = ctx.connection
        self._diagnostics_log: list[str] = []

        top = QHBoxLayout()
        top.setSpacing(16)
        adapter_card = Card("Adapter")
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setAccessibleName("Serial port")
        self.port_combo.setMinimumWidth(260)
        self.refresh_button = IconPushButton("Refresh", "refresh", tooltip="List serial ports")
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_button)
        adapter_card.body.addLayout(port_row)
        self.method_label = label("", "muted", wrap=True)
        adapter_card.body.addWidget(self.method_label)
        buttons = QHBoxLayout()
        self.connect_button = IconPushButton("Connect", "plug", variant="primary")
        self.retry_button = IconPushButton(
            "Retry vehicle", "refresh", tooltip="Ask the vehicle ECU again (ignition on?)"
        )
        self.disconnect_button = IconPushButton("Disconnect", "x", variant="danger")
        for button in (self.connect_button, self.retry_button, self.disconnect_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        adapter_card.body.addLayout(buttons)
        status_row = QHBoxLayout()
        self.adapter_pill = StatusIndicator("Adapter: not connected", StatusLevel.OFFLINE)
        self.ecu_pill = StatusIndicator("Vehicle ECU: not connected", StatusLevel.OFFLINE)
        status_row.addWidget(self.adapter_pill)
        status_row.addWidget(self.ecu_pill)
        status_row.addStretch(1)
        adapter_card.body.addLayout(status_row)
        self.status_text = label("", wrap=True)
        adapter_card.body.addWidget(self.status_text)
        adapter_card.body.addWidget(label("Live monitoring", "section-title"))
        self.controls = MonitoringControls(ctx)
        adapter_card.body.addWidget(self.controls)
        adapter_card.body.addStretch(1)
        top.addWidget(adapter_card, 3)

        details_card = Card("Connection details")
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        self.facts: dict[str, QLabel] = {}
        for key, title in (
            ("vehicle", "Selected vehicle"),
            ("port", "Port / method"),
            ("adapter", "Adapter"),
            ("protocol", "Vehicle protocol"),
            ("voltage", "Adapter supply voltage"),
            ("sensors", "Supported parameters"),
            ("mil", "Check-engine lamp (MIL)"),
            ("duration", "Connected for"),
            ("last", "Last telemetry"),
            ("polling", "Polling"),
            ("quality", "Link quality (measured)"),
            ("source", "Data label"),
        ):
            value = label(MISSING, wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.facts[key] = value
            form.addRow(label(title, "muted"), value)
        details_card.body.addLayout(form)
        top.addWidget(details_card, 2)
        self.content.addLayout(top)

        self.sensor_table = make_table(SENSOR_COLUMNS, "Supported parameters")
        self.sensor_table.setMinimumHeight(260)
        self.sensor_stack = StatefulStack(self.sensor_table)
        sensors_card = Card("Parameters")
        sensors_card.body.addWidget(self.sensor_stack)
        self.content.addWidget(sensors_card)

        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        log_card = Card("Connection diagnostics")
        self.log_list = QListWidget()
        self.log_list.setAccessibleName("Connection diagnostics")
        self.log_list.setMinimumHeight(150)
        log_card.body.addWidget(self.log_list)
        bottom.addWidget(log_card, 1)
        help_card = Card("Connecting compatible hardware")
        help_card.body.addWidget(label(SETUP_TEXT, wrap=True))
        bottom.addWidget(help_card, 1)
        self.content.addLayout(bottom)

        thresholds_card = Card("Rule thresholds for this vehicle")
        thresholds_card.body.addWidget(
            label(
                "The default rule thresholds are generic and conservative, not manufacturer "
                "specifications. Enter a value only if you have a reliable figure for this "
                "vehicle, such as its service documentation, and record where it came from. "
                "Leave a field at 0 to use the default.",
                "muted",
                wrap=True,
            )
        )
        threshold_form = QFormLayout()
        self.threshold_spins: dict[str, QDoubleSpinBox] = {}
        for key in OVERRIDABLE:
            title, unit = THRESHOLD_LABELS[key]
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 200.0)
            spin.setDecimals(1)
            spin.setSuffix(f" {unit}")
            spin.setSpecialValueText("Default")
            spin.setAccessibleName(title)
            self.threshold_spins[key] = spin
            threshold_form.addRow(title, spin)
        self.threshold_note = QLineEdit()
        self.threshold_note.setPlaceholderText("Source of these values (required)")
        self.threshold_note.setAccessibleName("Threshold source")
        threshold_form.addRow("Source", self.threshold_note)
        thresholds_card.body.addLayout(threshold_form)
        self.save_thresholds_button = IconPushButton("Save thresholds", "check", variant="primary")
        self.threshold_status = label("", "muted", wrap=True)
        row = QHBoxLayout()
        row.addWidget(self.save_thresholds_button)
        row.addWidget(self.threshold_status, 1)
        thresholds_card.body.addLayout(row)
        self.content.addWidget(thresholds_card)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._refresh_live_facts)

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.connect_selected)
        self.retry_button.clicked.connect(self.connection.retry_ecu)
        self.disconnect_button.clicked.connect(self.connection.disconnect_adapter)
        self.port_combo.currentIndexChanged.connect(self._on_port_selected)
        self.save_thresholds_button.clicked.connect(self.save_thresholds)
        self.connection.status_changed.connect(self._on_status)
        self.connection.ports_changed.connect(self._on_ports)
        self.connection.report_changed.connect(self._on_report)
        self.connection.connect_failed.connect(self._on_connect_failed)
        self.connection.poll_completed.connect(self._on_poll)
        self.connection.quality_changed.connect(self._on_quality)
        self.connection.link_lost.connect(self._on_link_lost)
        self.connection.link_restored.connect(self._on_link_restored)
        self.connection.link_failed.connect(self._on_link_failed)
        self.connection.message.connect(self._log)
        ctx.state.active_vehicle_changed.connect(self._on_vehicle_changed)
        ctx.monitoring.state_changed.connect(self._refresh_buttons)
        self._on_ports(self.connection.ports)
        self._on_vehicle_changed(ctx.state.active_vehicle)
        self.refresh_view()

    # -- actions ------------------------------------------------------------------------------

    def on_shown(self) -> None:
        if not self.connection.ports:
            self.refresh_ports()
        self.refresh_view()

    def refresh_ports(self) -> None:
        self._log("Listing serial ports…")
        self.connection.refresh_ports()

    def selected_port(self) -> SerialPortInfo | None:
        data = self.port_combo.currentData()
        return data if isinstance(data, SerialPortInfo) else None

    def connect_selected(self) -> None:
        port = self.selected_port()
        if port is None:
            self._log("Choose a serial port first.")
            return
        vehicle = self.ctx.state.active_vehicle
        self._log(f"Connecting to {port.port}…")
        self.connection.connect_adapter(port.port, vehicle_id=vehicle.id if vehicle else None)
        if not port.is_mock:
            settings = self.ctx.app.settings
            if settings.obd.port != port.port:
                settings.obd.port = port.port
                self.ctx.state.save_settings()

    def save_thresholds(self) -> None:
        vehicle = self.ctx.state.active_vehicle
        if vehicle is None:
            self.threshold_status.setText("Select an active vehicle first.")
            return
        overrides = {k: s.value() for k, s in self.threshold_spins.items() if s.value() > 0}
        note = self.threshold_note.text().strip()
        if overrides and not note:
            self.threshold_status.setText("Record where these values come from before saving.")
            return
        try:
            self.ctx.thresholds.save(
                vehicle.id,
                overrides,
                source_note=note,
                base=self.ctx.app.settings.diagnostics.thresholds,
            )
        except SmartDriveError as exc:
            self.threshold_status.setText(exc.user_message)
            return
        self.ctx.diagnostics.vehicle_thresholds = overrides
        self.ctx.diagnostics.apply_settings()
        self.threshold_status.setText(
            "Saved. Rule checks for this vehicle now use these values."
            if overrides
            else "Vehicle-specific values removed; defaults apply."
        )

    # -- signal handlers ----------------------------------------------------------------------

    def _log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_list.insertItem(0, f"{stamp}  {text}")
        while self.log_list.count() > 200:
            self.log_list.takeItem(self.log_list.count() - 1)

    def _on_ports(self, ports: object) -> None:
        current = self.selected_port()
        preferred = current.port if current else self.ctx.app.settings.obd.port
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        items = list(ports) if isinstance(ports, list) else []
        for info in items:
            if isinstance(info, SerialPortInfo):
                self.port_combo.addItem(info.label, info)
        if not items:
            self.port_combo.addItem("No serial ports found", None)
        for index in range(self.port_combo.count()):
            data = self.port_combo.itemData(index)
            if isinstance(data, SerialPortInfo) and data.port == preferred:
                self.port_combo.setCurrentIndex(index)
        self.port_combo.blockSignals(False)
        if isinstance(ports, list):
            self._log(f"Found {len(items)} serial port(s).")
        self._on_port_selected()

    def _on_port_selected(self, *_: object) -> None:
        port = self.selected_port()
        if port is None:
            self.method_label.setText(
                "No adapter detected. Plug in the adapter (or pair it) and press Refresh."
            )
        else:
            maker = f" · {port.manufacturer}" if port.manufacturer else ""
            mock = " — not a real vehicle; data is labelled simulated" if port.is_mock else ""
            self.method_label.setText(f"{port.connection_method}{maker}{mock}")
        self._refresh_buttons()

    def _on_status(self, status: object) -> None:
        if isinstance(status, ConnectionStatus):
            message = self.connection.status_message
            self._log(status.label + (f": {message}" if message else ""))
        self.refresh_view()

    def _on_report(self, report: object) -> None:
        if isinstance(report, ConnectionReport):
            self._log(
                f"Adapter {report.adapter.version} on {report.port}; "
                + (
                    f"vehicle protocol {report.protocol_name or 'unknown'}."
                    if report.ecu_connected
                    else f"vehicle not responding ({report.ecu_message or 'no reply'})."
                )
            )
        self.refresh_view()

    def _on_connect_failed(self, message: str) -> None:
        self._log(f"Connection failed: {message}")
        self.refresh_view()

    def _on_poll(self, result: object) -> None:
        if isinstance(result, PollResult):
            self._render_sensors(result)

    def _on_quality(self, _quality: object) -> None:
        self._refresh_live_facts()

    def _on_link_lost(self, message: str) -> None:
        self._log(f"Connection lost: {message} Reconnecting…")

    def _on_link_restored(self) -> None:
        self._log("Connection restored.")

    def _on_link_failed(self, message: str) -> None:
        self._log(f"Reconnection stopped: {message}")

    def _on_vehicle_changed(self, _vehicle: object) -> None:
        vehicle = self.ctx.state.active_vehicle
        self.facts["vehicle"].setText(vehicle.name if vehicle else "No active vehicle")
        values: dict[str, float] = {}
        note = ""
        if vehicle is not None:
            try:
                values, note = self.ctx.thresholds.get(vehicle.id)
            except SmartDriveError:
                values, note = {}, ""
        for key, spin in self.threshold_spins.items():
            spin.setValue(values.get(key, 0.0))
            spin.setEnabled(vehicle is not None)
        self.threshold_note.setText(note)
        self.threshold_status.setText(
            "Using vehicle-specific values." if values else "Using the generic defaults."
        )

    # -- rendering ----------------------------------------------------------------------------

    def refresh_view(self) -> None:
        c = self.connection
        status = c.status
        report = c.report
        level = STATUS_LEVEL[status]
        if status.has_adapter or status is ConnectionStatus.RECONNECTING:
            self.adapter_pill.set_status("Adapter: connected", StatusLevel.NORMAL)
        else:
            self.adapter_pill.set_status(
                f"Adapter: {status.label.lower()}",
                level if status is not ConnectionStatus.DISCONNECTED else StatusLevel.OFFLINE,
            )
        if status.has_ecu:
            self.ecu_pill.set_status("Vehicle ECU: connected", StatusLevel.NORMAL)
        elif status is ConnectionStatus.ADAPTER_CONNECTED:
            self.ecu_pill.set_status("Vehicle ECU: not responding", StatusLevel.WARNING)
        else:
            self.ecu_pill.set_status("Vehicle ECU: not connected", StatusLevel.OFFLINE)
        detail = c.status_message or (c.last_error or "")
        self.status_text.setText(
            status.label + (f" — {detail}" if detail and detail not in status.label else "")
        )
        if report is None:
            for key in ("port", "adapter", "protocol", "voltage", "sensors", "mil"):
                self.facts[key].setText(MISSING)
            self.facts["source"].setText("No adapter connected")
            self.sensor_stack.show_empty(
                "No vehicle connected",
                "Connect a compatible adapter to see which standard parameters this vehicle "
                "reports. No readings are shown without a connection.",
            )
        else:
            for index in range(self.port_combo.count()):
                data = self.port_combo.itemData(index)
                if isinstance(data, SerialPortInfo) and data.port == report.port:
                    self.port_combo.blockSignals(True)
                    self.port_combo.setCurrentIndex(index)
                    self.port_combo.blockSignals(False)
                    break
            self.facts["port"].setText(f"{report.port} · {c.method_for(report.port)}")
            adapter = report.adapter
            description = f" ({adapter.device_description})" if adapter.device_description else ""
            self.facts["adapter"].setText(f"{adapter.version}{description}")
            self.facts["protocol"].setText(
                report.protocol_name or ("Not detected" if not report.ecu_connected else MISSING)
            )
            self.facts["voltage"].setText(_value_text(adapter.supply_voltage_v, "V"))
            caps = report.capabilities
            self.facts["sensors"].setText(
                f"{caps.sensor_count} of {len(DATA_PIDS)} that SmartDrive reads"
                if caps is not None
                else "Not read yet"
            )
            monitor = report.monitor_status
            self.facts["mil"].setText(
                MISSING
                if monitor is None
                else (
                    f"{'On' if monitor.mil_on else 'Off'} · "
                    f"{monitor.dtc_count} confirmed code(s) reported"
                )
            )
            self.facts["source"].setText(
                "Mock adapter — simulated data"
                if report.is_mock
                else ("Live vehicle telemetry" if c.data_source is DataSource.LIVE else MISSING)
            )
            self._render_sensors(c.last_poll)
        self._refresh_live_facts()
        self._refresh_buttons()
        active = status.has_adapter or status is ConnectionStatus.RECONNECTING
        if active and not self._clock.isActive():
            self._clock.start()
        elif not active and self._clock.isActive():
            self._clock.stop()

    def _render_sensors(self, poll: PollResult | None) -> None:
        report = self.connection.report
        caps = report.capabilities if report else None
        if caps is None:
            self.sensor_stack.show_empty(
                "Vehicle not responding",
                "The adapter is connected but the vehicle ECU has not answered. Switch the "
                "ignition on and press Retry vehicle.",
            )
            return
        supported = set(caps.supported_pids)
        sample = poll.sample if poll else None
        rows: list[tuple[str, ...]] = []
        keys: list[str] = []
        for spec in DATA_PIDS:
            is_supported = spec.pid in supported
            value: float | None = None
            if sample is not None:
                if spec.sample_field is not None:
                    value = getattr(sample, spec.sample_field)
                elif spec.extra_key is not None:
                    value = sample.extra.get(spec.extra_key)
            cycle = MISSING
            if poll is not None and is_supported:
                if spec.key in poll.timed_out:
                    cycle = "Timed out"
                elif spec.key in poll.malformed:
                    cycle = "Malformed reply (discarded)"
                elif spec.key in poll.rejected:
                    cycle = "Out of range (discarded)"
                elif spec.key in poll.unavailable:
                    cycle = "No data"
                elif value is not None:
                    cycle = "OK"
            rows.append(
                (
                    spec.label,
                    f"01 {spec.pid:02X}",
                    spec.unit,
                    "Supported" if is_supported else "Not supported",
                    _value_text(value, spec.unit) if is_supported else MISSING,
                    cycle if is_supported else "Not requested",
                )
            )
            keys.append(spec.key)
        for name in NOT_AVAILABLE_OVER_OBD:
            rows.append(
                (
                    name.replace("_kpa", "").replace("_", " ").capitalize(),
                    MISSING,
                    "kPa",
                    "Not defined in generic OBD-II",
                    MISSING,
                    "Not available",
                )
            )
            keys.append(name)
        fill_table(self.sensor_table, rows, keys)
        self.sensor_stack.show_content()

    def _refresh_live_facts(self) -> None:
        c = self.connection
        self.facts["duration"].setText(_duration(c.connected_since))
        self.facts["last"].setText(
            local_time(c.last_sample_at, seconds=True) if c.last_sample_at else MISSING
        )
        if c.status is ConnectionStatus.MONITORING:
            interval = self.ctx.app.settings.obd.poll_interval_ms
            duration = f", last cycle {c.last_poll.duration_ms:.0f} ms" if c.last_poll else ""
            self.facts["polling"].setText(
                f"Every {interval} ms · {c.samples_received} samples{duration}"
            )
        else:
            self.facts["polling"].setText("Not polling")
        q = c.quality
        if q is None or q.requests == 0:
            self.facts["quality"].setText(MISSING)
        else:
            ratio = q.success_ratio or 0.0
            latency = (
                f", median {q.median_latency_ms:.0f} ms" if q.median_latency_ms is not None else ""
            )
            self.facts["quality"].setText(
                f"{ratio:.0%} of last {q.requests} requests answered{latency}; "
                f"{q.timeouts} timeout(s)"
            )

    def _refresh_buttons(self, *_: object) -> None:
        c = self.connection
        status = c.status
        idle = status in (ConnectionStatus.DISCONNECTED, ConnectionStatus.FAILED)
        self.connect_button.setEnabled(idle and self.selected_port() is not None)
        self.refresh_button.setEnabled(idle)
        self.port_combo.setEnabled(idle)
        self.retry_button.setEnabled(status is ConnectionStatus.ADAPTER_CONNECTED)
        self.disconnect_button.setEnabled(not idle and status is not ConnectionStatus.DISCONNECTING)

    def apply_palette(self, palette: ThemePalette) -> None:
        for widget in (self.adapter_pill, self.ecu_pill):
            widget.apply_palette(palette)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        self._clock.stop()
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self.connection.status.has_adapter:
            self._clock.start()
