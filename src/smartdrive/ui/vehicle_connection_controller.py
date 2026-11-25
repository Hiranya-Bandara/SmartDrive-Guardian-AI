"""Main-thread façade over the OBD worker thread.

Pages call this controller; it forwards requests to :class:`ObdWorker` through queued signals
and re-emits results on the GUI thread. It also records connection history and trouble-code
scans, and acts as the *live frame producer* for the monitoring controller. Nothing connects to
hardware until the user presses Connect.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Final

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, Signal

from smartdrive.config.constants import DataSource
from smartdrive.config.settings import AppSettings
from smartdrive.models.trouble_code import DtcScan
from smartdrive.obd.discovery import SerialPortInfo
from smartdrive.obd.elm327 import LinkQuality
from smartdrive.obd.mock import MOCK_PORT
from smartdrive.obd.session import (
    ConnectionParameters,
    ConnectionReport,
    ConnectionStatus,
    DtcScanResult,
    PollResult,
    ReconnectPolicy,
)
from smartdrive.services.data_source import TelemetryFrame
from smartdrive.services.obd_service import ObdHistoryService
from smartdrive.ui.workers.obd_worker import ObdWorker, SessionFactory
from smartdrive.utils.exceptions import SmartDriveError

logger = logging.getLogger(__name__)

THREAD_JOIN_TIMEOUT_MS: Final = 8000


class VehicleConnectionController(QObject):
    status_changed = Signal(object)  # ConnectionStatus
    ports_changed = Signal(object)  # list[SerialPortInfo]
    report_changed = Signal(object)  # ConnectionReport | None
    connect_failed = Signal(str)
    frame_received = Signal(object)  # TelemetryFrame
    poll_completed = Signal(object)  # PollResult
    quality_changed = Signal(object)  # LinkQuality
    scan_completed = Signal(object)  # DtcScan (persisted) or DtcScanResult when no vehicle
    scan_failed = Signal(str)
    link_lost = Signal(str)
    link_restored = Signal()
    link_failed = Signal(str)  # reconnection exhausted; adapter closed
    message = Signal(str)

    _req_ports = Signal(bool)
    _req_connect = Signal(object)
    _req_policy = Signal(object)
    _req_retry = Signal()
    _req_start = Signal(int)
    _req_stop = Signal()
    _req_pause = Signal(bool)
    _req_interval = Signal(int)
    _req_scan = Signal(bool)
    _req_disconnect = Signal()

    def __init__(
        self,
        settings: AppSettings,
        history: ObdHistoryService,
        *,
        session_factory: SessionFactory | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._history = history
        self._cancel = threading.Event()
        self.status = ConnectionStatus.DISCONNECTED
        self.status_message = ""
        self.ports: list[SerialPortInfo] = []
        self.report: ConnectionReport | None = None
        self.quality: LinkQuality | None = None
        self.last_poll: PollResult | None = None
        self.last_sample_at: datetime | None = None
        self.connected_since: datetime | None = None
        self.samples_received = 0
        self.connection_id: int | None = None
        self.last_scan: DtcScan | None = None
        self.scanning = False
        self.streaming = False
        self.vehicle_id: int | None = None
        self.recording_session_id: int | None = None
        """Trip being recorded, if any; a scan made during it is linked to the trip."""
        self.last_error: str | None = None
        self._closed = False

        policy = ReconnectPolicy(
            max_attempts=settings.obd.max_reconnect_attempts,
            initial_delay_s=settings.obd.reconnect_initial_delay_seconds,
        )
        kwargs = {} if session_factory is None else {"session_factory": session_factory}
        self._worker = ObdWorker(self._cancel, policy=policy, **kwargs)
        self._thread = QThread()
        self._thread.setObjectName("smartdrive-obd")
        self._worker.moveToThread(self._thread)
        w = self._worker
        self._req_ports.connect(w.list_ports)
        self._req_connect.connect(w.connect_adapter)
        self._req_policy.connect(w.set_policy)
        self._req_retry.connect(w.retry_ecu)
        self._req_start.connect(w.start_polling)
        self._req_stop.connect(w.stop_polling)
        self._req_pause.connect(w.set_paused)
        self._req_interval.connect(w.set_interval)
        self._req_scan.connect(w.scan_codes)
        self._req_disconnect.connect(w.disconnect_adapter)
        w.status_changed.connect(self._on_status)
        w.ports_listed.connect(self._on_ports)
        w.connected.connect(self._on_connected)
        w.connect_failed.connect(self._on_connect_failed)
        w.frame_ready.connect(self._on_frame)
        w.polled.connect(self._on_polled)
        w.quality_changed.connect(self._on_quality)
        w.scan_finished.connect(self._on_scan)
        w.scan_failed.connect(self._on_scan_failed)
        w.link_lost.connect(self._on_link_lost)
        w.reconnected.connect(self._on_reconnected)
        w.reconnect_failed.connect(self._on_link_failed)
        w.disconnected.connect(self._on_disconnected)
        self._thread.start()

    # -- state --------------------------------------------------------------------------------

    @property
    def is_mock(self) -> bool:
        return self.report is not None and self.report.is_mock

    @property
    def ecu_connected(self) -> bool:
        return self.status.has_ecu

    @property
    def busy(self) -> bool:
        return self.status in (
            ConnectionStatus.CONNECTING,
            ConnectionStatus.RECONNECTING,
            ConnectionStatus.DISCONNECTING,
        )

    @property
    def data_source(self) -> DataSource:
        """Telemetry from the mock adapter is simulated data, never live vehicle data."""
        return DataSource.SIMULATION if self.is_mock else DataSource.LIVE

    @property
    def source_description(self) -> str:
        if self.report is None:
            return "No adapter"
        if self.report.is_mock:
            return "Mock OBD-II adapter (simulated data)"
        return f"Live vehicle via {self.report.port}"

    @property
    def unavailable_sensors(self) -> frozenset[str]:
        capabilities = self.report.capabilities if self.report else None
        return frozenset(capabilities.missing_sample_fields) if capabilities else frozenset()

    def thread_running(self) -> bool:
        return self._thread.isRunning()

    # -- user actions -------------------------------------------------------------------------

    def refresh_ports(self) -> None:
        if not self._closed:
            self._req_ports.emit(self._settings.obd.show_mock_adapter)

    def connect_adapter(self, port: str | None, *, vehicle_id: int | None) -> None:
        if self._closed or self.busy:
            return
        if port == MOCK_PORT and not self._settings.obd.show_mock_adapter:
            self.connect_failed.emit("The mock adapter is disabled in Settings.")
            return
        obd = self._settings.obd
        self.vehicle_id = vehicle_id
        self.last_error = None
        self._cancel.clear()
        params = ConnectionParameters(
            port=port,
            baudrate=obd.baudrate,
            connect_timeout_s=obd.connection_timeout_seconds,
            query_timeout_s=obd.query_timeout_seconds,
            mock_profile=obd.mock_profile,
        )
        self._req_policy.emit(
            ReconnectPolicy(
                max_attempts=obd.max_reconnect_attempts,
                initial_delay_s=obd.reconnect_initial_delay_seconds,
            )
        )
        self._req_connect.emit(params)

    def retry_ecu(self) -> None:
        if not self._closed and self.status is ConnectionStatus.ADAPTER_CONNECTED:
            self._req_retry.emit()

    def disconnect_adapter(self) -> None:
        if self._closed:
            return
        self._cancel.set()  # interrupt a pending read; the worker clears it afterwards
        self._req_disconnect.emit()

    def scan_codes(self) -> None:
        if self._closed or self.scanning:
            return
        if not self.ecu_connected:
            self.scan_failed.emit("Connect to the vehicle ECU before scanning for trouble codes.")
            return
        self.scanning = True
        self._req_scan.emit(self._settings.obd.read_freeze_frame)

    def set_vehicle(self, vehicle_id: int | None) -> None:
        self.vehicle_id = vehicle_id

    # -- live frame producer (used by MonitoringController) -----------------------------------

    def begin_stream(self, interval_ms: int) -> bool:
        if not self.ecu_connected or self._closed:
            return False
        self.streaming = True
        self._req_start.emit(interval_ms)
        return True

    def end_stream(self) -> None:
        if self.streaming:
            self.streaming = False
            if not self._closed:
                self._req_stop.emit()

    def set_stream_paused(self, paused: bool) -> None:
        if self.streaming and not self._closed:
            self._req_pause.emit(paused)

    def set_stream_interval(self, interval_ms: int) -> None:
        if not self._closed:
            self._req_interval.emit(interval_ms)

    # -- shutdown -----------------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel.set()
        if self._thread.isRunning():
            QMetaObject.invokeMethod(
                self._worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection
            )
        self._thread.quit()
        if not self._thread.wait(THREAD_JOIN_TIMEOUT_MS):
            logger.error("OBD thread did not stop within timeout")
        self._end_history("Application closed")

    # -- worker results -----------------------------------------------------------------------

    def _on_status(self, value: str, message: str) -> None:
        status = ConnectionStatus(value)
        self.status_message = message
        if status is not self.status:
            self.status = status
            if status in (ConnectionStatus.DISCONNECTED, ConnectionStatus.FAILED):
                self.connected_since = None
            self.status_changed.emit(status)
        elif message:
            self.status_changed.emit(status)

    def _on_ports(self, ports: object) -> None:
        self.ports = list(ports) if isinstance(ports, list) else []
        self.ports_changed.emit(self.ports)

    def _on_connected(self, report: object) -> None:
        if not isinstance(report, ConnectionReport):
            return
        first = self.report is None or self.report.port != report.port
        self.report = report
        self.connected_since = self.connected_since or report.connected_at
        if report.ecu_connected:
            self.last_error = None
        else:
            self.last_error = report.ecu_message
        try:
            if first or self.connection_id is None:
                method = self.method_for(report.port)
                self.connection_id = self._history.record_connection(
                    report, vehicle_id=self.vehicle_id, connection_method=method
                )
            else:
                self._history.update_connection(self.connection_id, report=report)
        except SmartDriveError as exc:
            self.message.emit(exc.user_message)
        self.report_changed.emit(report)

    def method_for(self, port: str) -> str:
        for info in self.ports:
            if info.port == port:
                return info.connection_method
        return "Mock (no hardware)" if port == MOCK_PORT else "Serial port"

    def _on_connect_failed(self, message: str) -> None:
        self.last_error = message
        self.report = None
        self.report_changed.emit(None)
        self.connect_failed.emit(message)

    def _on_frame(self, frame: object) -> None:
        if not isinstance(frame, TelemetryFrame):
            return
        if frame.sample is not None:
            self.samples_received += 1
            self.last_sample_at = datetime.now(UTC)
        if self.streaming:
            self.frame_received.emit(frame)

    def _on_polled(self, result: object) -> None:
        if isinstance(result, PollResult):
            self.last_poll = result
            self.poll_completed.emit(result)

    def _on_quality(self, quality: object) -> None:
        if isinstance(quality, LinkQuality):
            self.quality = quality
            self.quality_changed.emit(quality)

    def _on_scan(self, result: object) -> None:
        self.scanning = False
        if not isinstance(result, DtcScanResult):
            return
        if self.vehicle_id is None:
            self.scan_completed.emit(result)
            return
        try:
            scan = self._history.record_scan(
                self.vehicle_id,
                result,
                data_source=self.data_source,
                is_mock=self.is_mock,
                protocol=self.report.protocol_name if self.report else None,
                connection_id=self.connection_id,
                session_id=self.recording_session_id,
            )
        except SmartDriveError as exc:
            self.scan_failed.emit(exc.user_message)
            return
        self.last_scan = scan
        self.scan_completed.emit(scan)

    def _on_scan_failed(self, message: str) -> None:
        self.scanning = False
        self.scan_failed.emit(message)

    def _on_link_lost(self, message: str) -> None:
        self.last_error = message
        self.link_lost.emit(message)

    def _on_reconnected(self, report: object) -> None:
        if isinstance(report, ConnectionReport):
            self.report = report
            self.report_changed.emit(report)
        self.last_error = None
        self.link_restored.emit()

    def _on_link_failed(self, message: str) -> None:
        self.last_error = message
        self.streaming = False
        self._end_history(message)
        self.report = None
        self.report_changed.emit(None)
        self.link_failed.emit(message)

    def _on_disconnected(self, message: str) -> None:
        self.streaming = False
        self._end_history(message)
        self.report = None
        self.quality = None
        self.last_poll = None
        self.report_changed.emit(None)

    def _end_history(self, reason: str) -> None:
        connection_id, self.connection_id = self.connection_id, None
        if connection_id is None:
            return
        try:
            self._history.end_connection(
                connection_id, reason=reason, samples_received=self.samples_received
            )
        except SmartDriveError:
            logger.warning("Could not record the end of the adapter connection", exc_info=True)
        self.samples_received = 0
