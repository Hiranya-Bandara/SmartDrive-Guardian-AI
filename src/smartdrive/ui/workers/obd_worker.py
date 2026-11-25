"""Owns the serial adapter on its own thread: discovery, connection, polling, code scans.

Every blocking adapter call happens here, never on the GUI thread. Results leave only as Qt
signals. A shared :class:`threading.Event` lets the GUI thread cancel a pending read (for example
during shutdown) without waiting for an adapter timeout. Reconnection after a lost link is
bounded by :class:`ReconnectPolicy` and scheduled with timers, so the thread stays responsive.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from smartdrive.config.constants import DataSource
from smartdrive.obd.discovery import list_serial_ports
from smartdrive.obd.errors import (
    AdapterDisconnectedError,
    CommunicationTimeoutError,
    ObdError,
    OperationCancelledError,
)
from smartdrive.obd.session import (
    ConnectionParameters,
    ConnectionStatus,
    ObdSession,
    ReconnectPolicy,
)
from smartdrive.services.data_source import TelemetryFrame

logger = logging.getLogger(__name__)

SessionFactory = Callable[..., ObdSession]


class ObdWorker(QObject):
    status_changed = Signal(str, str)
    ports_listed = Signal(object)
    connected = Signal(object)  # ConnectionReport (adapter connected; ECU may not be)
    connect_failed = Signal(str)
    frame_ready = Signal(object)  # TelemetryFrame
    polled = Signal(object)  # PollResult
    quality_changed = Signal(object)  # LinkQuality
    scan_finished = Signal(object)  # DtcScanResult
    scan_failed = Signal(str)
    link_lost = Signal(str)
    reconnected = Signal(object)  # ConnectionReport
    reconnect_failed = Signal(str)  # attempts exhausted; the adapter has been closed
    disconnected = Signal(str)

    def __init__(
        self,
        cancel: threading.Event,
        *,
        policy: ReconnectPolicy | None = None,
        session_factory: SessionFactory = ObdSession,
    ) -> None:
        super().__init__()
        self._cancel = cancel
        self._policy = policy or ReconnectPolicy()
        self._session_factory = session_factory
        self._session: ObdSession | None = None
        self._params: ConnectionParameters | None = None
        self._poll_timer: QTimer | None = None
        self._reconnect_timer: QTimer | None = None
        self._interval_ms = 1000
        self._polling = False
        self._paused = False
        self._stream_started = 0.0
        self._attempt = 0
        self._closed = False

    # -- helpers ------------------------------------------------------------------------------

    def _emit_status(self, status: ConnectionStatus, message: str) -> None:
        self.status_changed.emit(status.value, message)

    def _timers(self) -> tuple[QTimer, QTimer]:
        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.setSingleShot(True)
            self._poll_timer.timeout.connect(self._poll)
        if self._reconnect_timer is None:
            self._reconnect_timer = QTimer(self)
            self._reconnect_timer.setSingleShot(True)
            self._reconnect_timer.timeout.connect(self._attempt_reconnect)
        return self._poll_timer, self._reconnect_timer

    # -- discovery and connection -------------------------------------------------------------

    @Slot(bool)
    def list_ports(self, include_mock: bool) -> None:
        self._emit_status(ConnectionStatus.DISCOVERING, "")
        try:
            ports = list_serial_ports(include_mock=include_mock)
        except Exception:
            logger.exception("Port discovery failed")
            ports = []
        self.ports_listed.emit(ports)
        status = self._session.status if self._session else ConnectionStatus.DISCONNECTED
        self._emit_status(status, "")

    @Slot(object)
    def set_policy(self, policy: object) -> None:
        """Takes effect from the next reconnection sequence."""
        if isinstance(policy, ReconnectPolicy):
            self._policy = policy

    @Slot(object)
    def connect_adapter(self, params: object) -> None:
        if not isinstance(params, ConnectionParameters) or self._closed:
            return
        self._close_session()
        self._params = params
        self._session = self._session_factory(
            params, cancel=self._cancel, on_status=self._emit_status
        )
        try:
            report = self._session.connect()
        except OperationCancelledError:
            self._close_session()
            self.connect_failed.emit("Connection cancelled.")
            return
        except ObdError as exc:
            logger.warning("Adapter connection failed", extra={"error": str(exc)})
            self._close_session(status=ConnectionStatus.FAILED, message=exc.user_message)
            self.connect_failed.emit(exc.user_message)
            return
        except ValueError as exc:
            self._close_session(status=ConnectionStatus.FAILED, message=str(exc))
            self.connect_failed.emit(str(exc))
            return
        self.connected.emit(report)

    @Slot()
    def retry_ecu(self) -> None:
        session = self._session
        if session is None or self._closed:
            return
        try:
            report = session.retry_ecu()
        except ObdError as exc:
            self._handle_link_error(exc)
            return
        self.connected.emit(report)

    # -- polling ------------------------------------------------------------------------------

    @Slot(int)
    def start_polling(self, interval_ms: int) -> None:
        if self._session is None or not self._session.status.has_ecu:
            return
        self._interval_ms = interval_ms
        self._polling = True
        self._paused = False
        self._stream_started = time.monotonic()
        self._session.set_status(ConnectionStatus.MONITORING, "")
        self._timers()[0].start(0)

    @Slot()
    def stop_polling(self) -> None:
        self._polling = False
        if self._poll_timer is not None:
            self._poll_timer.stop()
        if self._session is not None and self._session.status is ConnectionStatus.MONITORING:
            self._session.set_status(ConnectionStatus.ECU_CONNECTED, "")

    @Slot(bool)
    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if not paused and self._polling and self._poll_timer is not None:
            self._poll_timer.start(0)

    @Slot(int)
    def set_interval(self, interval_ms: int) -> None:
        self._interval_ms = interval_ms

    def _poll(self) -> None:
        session = self._session
        if not self._polling or self._paused or session is None or self._closed:
            return
        started = time.monotonic()
        try:
            result = session.poll()
        except ObdError as exc:
            self._handle_link_error(exc)
            return
        source = DataSource.SIMULATION if session.is_mock else DataSource.LIVE
        self.polled.emit(result)
        self.frame_ready.emit(
            TelemetryFrame(
                source=source,
                elapsed_s=time.monotonic() - self._stream_started,
                sample=result.sample,
                rejected=result.rejected,
            )
        )
        quality = session.quality()
        if quality is not None:
            self.quality_changed.emit(quality)
        spent_ms = (time.monotonic() - started) * 1000.0
        if self._polling and self._poll_timer is not None:
            self._poll_timer.start(max(0, round(self._interval_ms - spent_ms)))

    # -- trouble codes ------------------------------------------------------------------------

    @Slot(bool)
    def scan_codes(self, include_freeze_frame: bool) -> None:
        session = self._session
        if session is None or self._closed:
            self.scan_failed.emit("Connect to the vehicle before scanning for trouble codes.")
            return
        try:
            result = session.scan_trouble_codes(include_freeze_frame=include_freeze_frame)
        except ObdError as exc:
            self.scan_failed.emit(exc.user_message)
            if isinstance(exc, (AdapterDisconnectedError, CommunicationTimeoutError)):
                self._handle_link_error(exc)
            return
        self.scan_finished.emit(result)
        if self._polling and self._poll_timer is not None and not self._poll_timer.isActive():
            self._poll_timer.start(0)

    # -- failures -----------------------------------------------------------------------------

    def _handle_link_error(self, exc: ObdError) -> None:
        if isinstance(exc, OperationCancelledError) or self._closed:
            return
        logger.warning("Adapter link problem", extra={"error": str(exc)})
        if not exc.recoverable or self._params is None:
            self._close_session(status=ConnectionStatus.FAILED, message=exc.user_message)
            self.reconnect_failed.emit(exc.user_message)
            return
        self.link_lost.emit(exc.user_message)
        if self._poll_timer is not None:
            self._poll_timer.stop()
        self._attempt = 0
        self._schedule_reconnect(exc.user_message)

    def _schedule_reconnect(self, message: str) -> None:
        self._attempt += 1
        delay = self._policy.delay(self._attempt)
        if delay is None:
            self._close_session(status=ConnectionStatus.FAILED, message=message)
            self.reconnect_failed.emit(
                f"{message} Reconnection stopped after {self._policy.max_attempts} attempts."
            )
            return
        self._emit_status(
            ConnectionStatus.RECONNECTING,
            f"Attempt {self._attempt} of {self._policy.max_attempts} in {delay:.0f} s",
        )
        self._timers()[1].start(round(delay * 1000))

    def _attempt_reconnect(self) -> None:
        session = self._session
        if session is None or self._closed:
            return
        try:
            report = session.reconnect()
        except OperationCancelledError:
            return
        except (ObdError, ValueError) as exc:
            message = getattr(exc, "user_message", str(exc))
            self._schedule_reconnect(message)
            return
        if not report.ecu_connected:
            self._schedule_reconnect(report.ecu_message or "The vehicle ECU did not answer.")
            return
        self._attempt = 0
        self.reconnected.emit(report)
        if self._polling:
            session.set_status(ConnectionStatus.MONITORING, "")
            self._timers()[0].start(0)

    # -- shutdown -----------------------------------------------------------------------------

    @Slot()
    def disconnect_adapter(self) -> None:
        self._polling = False
        self._close_session()
        self._cancel.clear()
        self.disconnected.emit("Disconnected by the user.")

    @Slot()
    def shutdown(self) -> None:
        self._closed = True
        self._polling = False
        self._close_session()
        for timer in (self._poll_timer, self._reconnect_timer):
            if timer is not None:
                timer.stop()
                timer.deleteLater()
        self._poll_timer = None
        self._reconnect_timer = None

    def _close_session(self, *, status: ConnectionStatus | None = None, message: str = "") -> None:
        for timer in (self._poll_timer, self._reconnect_timer):
            if timer is not None:
                timer.stop()
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.warning("Adapter session did not close cleanly", exc_info=True)
        if status is not None:
            self._emit_status(status, message)
        elif session is not None:
            self._emit_status(ConnectionStatus.DISCONNECTED, message)
