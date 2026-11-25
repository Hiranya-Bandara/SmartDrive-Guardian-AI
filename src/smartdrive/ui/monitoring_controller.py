"""Main-thread façade over the monitoring and persistence workers.

Pages talk only to this controller. It owns the worker threads, the bounded telemetry buffer and
the staleness tracker, and re-emits worker results as signals on the GUI thread.

Three operating modes share one pipeline (buffer, charts, diagnostics):

- simulation: a :class:`SimulationSource` polled by a :class:`MonitoringWorker`;
- live: frames produced by the vehicle connection controller (the OBD worker thread owns the
  serial port, so live frames are pushed rather than polled here);
- replay: a :class:`ReplaySource` of a recorded trip, polled by a :class:`MonitoringWorker`.

Only one mode runs at a time. Starting, stopping or seeking clears the buffer and emits
``stream_reset`` so no telemetry crosses from one stream into another.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal, SignalInstance

from smartdrive.config.constants import DataSource
from smartdrive.config.settings import AppSettings
from smartdrive.core.monitoring import StalenessTracker, TelemetryBuffer
from smartdrive.core.telemetry_processing import sensor_bounds
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.services.data_source import TelemetryFrame, TelemetrySource
from smartdrive.services.replay_service import PLAYBACK_SPEEDS, ReplaySource
from smartdrive.services.simulator import SimulationConfig, SimulationSource
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.ui.workers.monitoring_worker import MonitoringWorker
from smartdrive.ui.workers.persistence_worker import PersistenceWorker
from smartdrive.utils.exceptions import SmartDriveError

logger = logging.getLogger(__name__)

THREAD_JOIN_TIMEOUT_MS: Final = 5000
STALE_CHECK_MS: Final = 500
MIN_REFRESH_MS: Final = 100
MAX_BUFFER_POINTS: Final = 36_000
REPLAY_TICK_MS: Final = 100


class MonitoringState(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class ConnectionState(StrEnum):
    IDLE = "idle"
    CONNECTED = "connected"
    NO_RESPONSE = "no_response"
    STALE = "stale"


def buffer_capacity(history_seconds: int) -> int:
    return max(600, min(MAX_BUFFER_POINTS, history_seconds * 1000 // MIN_REFRESH_MS))


class MonitoringController(QObject):
    frame_received = Signal(object)
    state_changed = Signal(object)
    connection_changed = Signal(object)
    recording_changed = Signal(object)
    persisted_count_changed = Signal(int)
    error_occurred = Signal(str)
    simulation_changed = Signal()
    record_requested_changed = Signal(bool)
    stream_reset = Signal()
    trip_completed = Signal(int)  # session id of a recording that has just ended
    replay_changed = Signal()
    preferred_mode_changed = Signal(str)

    _request_pause = Signal(bool)
    _request_interval = Signal(int)
    _request_execute = Signal(object)
    _request_enqueue = Signal(object)

    def __init__(
        self,
        settings: AppSettings,
        telemetry: TelemetryService,
        *,
        clock: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._telemetry = telemetry
        self._clock = clock
        self.buffer = TelemetryBuffer(buffer_capacity(settings.monitoring.chart_history_seconds))
        self.staleness = StalenessTracker()
        self.simulation_config = SimulationConfig()
        self.speed_factor = 1.0
        self.output_overrides: dict[str, float] = {}
        self.target_speed: float | None = None
        self.last_frame: TelemetryFrame | None = None
        self.last_update_at: datetime | None = None
        self.frames_without_response = 0
        self.persisted_count = 0
        self._state = MonitoringState.STOPPED
        self._connection = ConnectionState.IDLE
        self._source_kind: DataSource | None = None
        self._worker: MonitoringWorker | None = None
        self._thread: QThread | None = None
        self._persistence: PersistenceWorker | None = None
        self._persistence_thread: QThread | None = None
        self._session_id: int | None = None
        self._record_requested = settings.trips.record_by_default
        self._preferred_mode: str = settings.monitoring.default_mode
        self._live: LiveFrameProducer | None = None
        self.source_description = ""
        self.is_mock_source = False
        self.unavailable_sensors: frozenset[str] = frozenset()
        self.replay_session_id: int | None = None
        self.replay_original_source: DataSource | None = None
        self.replay_duration_s = 0.0
        self.replay_speed = 1.0
        self.replay_finished = False
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(STALE_CHECK_MS)
        self._stale_timer.timeout.connect(self._check_staleness)

    # -- read-only state ----------------------------------------------------------------------

    @property
    def state(self) -> MonitoringState:
        return self._state

    @property
    def connection(self) -> ConnectionState:
        return self._connection

    @property
    def is_active(self) -> bool:
        return self._state is not MonitoringState.STOPPED

    @property
    def data_source(self) -> DataSource | None:
        return self._source_kind

    @property
    def streaming_from_adapter(self) -> bool:
        """True while frames come from an OBD-II adapter (real or mock), whatever their label."""
        return self._live is not None

    @property
    def session_id(self) -> int | None:
        return self._session_id

    @property
    def record_requested(self) -> bool:
        return self._record_requested

    def set_record_requested(self, value: bool) -> None:
        if value != self._record_requested:
            self._record_requested = value
            self.record_requested_changed.emit(value)

    @property
    def preferred_mode(self) -> str:
        """``"simulation"`` or ``"live"``: the source the Start button uses. Never connects."""
        return self._preferred_mode

    def set_preferred_mode(self, mode: str) -> None:
        if mode not in ("simulation", "live"):
            raise ValueError(f"Unknown monitoring mode {mode!r}")
        if mode != self._preferred_mode:
            self._preferred_mode = mode
            self.preferred_mode_changed.emit(mode)

    @property
    def interval_ms(self) -> int:
        return self._settings.monitoring.refresh_interval_ms

    @property
    def stale_threshold_s(self) -> float:
        return max(self._settings.monitoring.stale_after_seconds, 3 * self.interval_ms / 1000.0)

    def data_age_s(self) -> float | None:
        """Seconds since the last successful reading, or None if there has been none."""
        return self.staleness.age(self._clock())

    def threads_running(self) -> bool:
        return any(
            t is not None and t.isRunning() for t in (self._thread, self._persistence_thread)
        )

    # -- lifecycle ----------------------------------------------------------------------------

    def start(
        self,
        *,
        record: bool = False,
        vehicle_id: int | None = None,
        trip_name: str | None = None,
    ) -> None:
        """Start the simulator (the default mode)."""
        if self.is_active:
            return
        source = SimulationSource(self.simulation_config, speed_factor=self.speed_factor)
        for sensor, value in self.output_overrides.items():
            source.simulator.set_output_override(sensor, value)
        source.simulator.set_target_speed(self.target_speed)
        self._reset_stream()
        if record:
            if vehicle_id is None:
                self.error_occurred.emit("Select an active vehicle before recording a session.")
                return
            config = self.simulation_config
            if not self._start_recording(
                vehicle_id,
                DataSource.SIMULATION,
                scenario=config.scenario.value,
                seed=config.seed,
                name=trip_name,
            ):
                return
        self.source_description = "Simulator"
        self.is_mock_source = False
        self.unavailable_sensors = frozenset()
        self._start_worker(source)
        self._source_kind = source.data_source
        self._activate()

    def start_live(
        self,
        producer: LiveFrameProducer,
        *,
        record: bool = False,
        vehicle_id: int | None = None,
        trip_name: str | None = None,
    ) -> bool:
        """Stream frames from a connected adapter. Returns False if the ECU is not connected."""
        if self.is_active:
            return False
        if not producer.ecu_connected:
            self.error_occurred.emit(
                "Connect to the vehicle on the Vehicle Connection page before live monitoring."
            )
            return False
        self._reset_stream()
        data_source = producer.data_source
        if record:
            if vehicle_id is None:
                self.error_occurred.emit("Select an active vehicle before recording a session.")
                return False
            scenario = "mock-obd-adapter" if producer.is_mock else None
            if not self._start_recording(
                vehicle_id, data_source, scenario=scenario, name=trip_name
            ):
                return False
        if not producer.begin_stream(self._settings.obd.poll_interval_ms):
            self._finish_recording()
            self.error_occurred.emit("The adapter could not start polling the vehicle.")
            return False
        self._live = producer
        producer.frame_received.connect(self._on_frame)
        self.source_description = producer.source_description
        self.is_mock_source = producer.is_mock
        self.unavailable_sensors = producer.unavailable_sensors
        self._source_kind = data_source
        self._activate()
        return True

    def start_replay(
        self,
        samples: Sequence[TelemetrySample],
        *,
        session_id: int,
        original_source: DataSource,
        speed: float = 1.0,
    ) -> bool:
        """Replay a recorded trip. Nothing is recorded and no hardware is involved."""
        if self.is_active:
            return False
        try:
            source = ReplaySource(
                samples, session_id=session_id, original_source=original_source, speed=speed
            )
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            return False
        self._reset_stream()
        self.replay_session_id = session_id
        self.replay_original_source = original_source
        self.replay_duration_s = source.duration_s
        self.replay_speed = speed
        self.replay_finished = False
        self.source_description = f"Replay of trip #{session_id}"
        self.is_mock_source = False
        self.unavailable_sensors = frozenset()
        self._start_worker(source, interval_ms=REPLAY_TICK_MS)
        self._source_kind = DataSource.REPLAY
        self._activate()
        self.replay_changed.emit()
        return True

    def seek_replay(self, position_s: float) -> None:
        """Jump within the replay. Time-dependent state is reset so no window spans the jump."""
        if self._source_kind is not DataSource.REPLAY:
            return
        was_finished = self.replay_finished
        self.buffer.clear()
        self.staleness.reset()
        self.last_frame = None
        self.replay_finished = False
        self._run_on_source(lambda s: _as_replay(s).seek(position_s))
        self.stream_reset.emit()
        if was_finished and self._state is MonitoringState.PAUSED:
            self.resume()
        self.replay_changed.emit()

    def set_replay_speed(self, speed: float) -> None:
        if speed not in PLAYBACK_SPEEDS:
            raise ValueError(f"Playback speed must be one of {PLAYBACK_SPEEDS}")
        self.replay_speed = speed
        self._run_on_source(lambda s: setattr(_as_replay(s), "speed", speed))
        self.replay_changed.emit()

    @property
    def replay_position_s(self) -> float:
        if self._source_kind is not DataSource.REPLAY or self.last_frame is None:
            return 0.0
        return self.last_frame.elapsed_s

    def _activate(self) -> None:
        self._set_state(MonitoringState.RUNNING)
        self._set_connection(ConnectionState.IDLE)
        self._stale_timer.start()

    def _reset_stream(self) -> None:
        self.buffer.clear()
        self.staleness.reset()
        self.last_frame = None
        self.frames_without_response = 0
        self.stream_reset.emit()

    def stop(self) -> None:
        if not self.is_active and not self.threads_running():
            return
        self._stale_timer.stop()
        self._stop_worker()
        self._stop_live()
        self._finish_recording()
        self._source_kind = None
        self.replay_session_id = None
        self.replay_original_source = None
        self.source_description = ""
        self.unavailable_sensors = frozenset()
        self._set_state(MonitoringState.STOPPED)
        self._set_connection(ConnectionState.IDLE)
        self.stream_reset.emit()

    def _stop_live(self) -> None:
        live, self._live = self._live, None
        if live is None:
            return
        with contextlib.suppress(RuntimeError, TypeError):
            live.frame_received.disconnect(self._on_frame)
        live.end_stream()

    def _finish_recording(self) -> None:
        session_id = self._stop_recording()
        if session_id is None:
            return
        try:
            self._telemetry.end_session(session_id)
        except SmartDriveError as exc:
            self.error_occurred.emit(exc.user_message)
            return
        self.trip_completed.emit(session_id)

    def pause(self) -> None:
        if self._state is MonitoringState.RUNNING:
            self._request_pause.emit(True)
            if self._live is not None:
                self._live.set_stream_paused(True)
            self._set_state(MonitoringState.PAUSED)

    def resume(self) -> None:
        if self._state is MonitoringState.PAUSED:
            self.staleness.reset()
            self._request_pause.emit(False)
            if self._live is not None:
                self._live.set_stream_paused(False)
            self._set_state(MonitoringState.RUNNING)

    def shutdown(self) -> None:
        self.stop()

    # -- configuration ------------------------------------------------------------------------

    def set_interval(self, interval_ms: int) -> None:
        self._settings.monitoring.refresh_interval_ms = interval_ms
        if self.is_active and self._source_kind is not DataSource.REPLAY:
            self._request_interval.emit(interval_ms)

    def resize_history(self) -> None:
        capacity = buffer_capacity(self._settings.monitoring.chart_history_seconds)
        if capacity != self.buffer.capacity:
            self.buffer = TelemetryBuffer(capacity)

    def configure_simulation(self, config: SimulationConfig) -> None:
        self.simulation_config = config
        self.buffer.clear()
        self._run_on_source(lambda s: _as_simulation(s).simulator.reconfigure(config))
        self.simulation_changed.emit()

    def reset_simulation(self) -> None:
        self.buffer.clear()
        self._run_on_source(lambda s: _as_simulation(s).reset())
        self.simulation_changed.emit()

    def set_speed_factor(self, factor: float) -> None:
        if not 0.1 <= factor <= 20.0:
            raise ValueError("Simulation speed must be between 0.1x and 20x")
        self.speed_factor = factor
        self._run_on_source(lambda s: setattr(_as_simulation(s), "speed_factor", factor))
        self.simulation_changed.emit()

    def set_output_override(self, sensor: str, value: float | None) -> None:
        if value is None:
            self.output_overrides.pop(sensor, None)
        else:
            low, high = sensor_bounds()[sensor]
            if not low <= value <= high:
                raise ValueError(f"{sensor} must be between {low} and {high}")
            self.output_overrides[sensor] = value
        self._run_on_source(
            lambda s: _as_simulation(s).simulator.set_output_override(sensor, value)
        )

    def set_target_speed(self, kph: float | None) -> None:
        self.target_speed = kph
        self._run_on_source(lambda s: _as_simulation(s).simulator.set_target_speed(kph))

    # -- internals ----------------------------------------------------------------------------

    def _run_on_source(self, command: Callable[[TelemetrySource], None]) -> None:
        if self._worker is not None:
            self._request_execute.emit(command)

    def _start_worker(self, source: TelemetrySource, *, interval_ms: int | None = None) -> None:
        worker = MonitoringWorker(source, interval_ms or self.interval_ms)
        thread = QThread()
        thread.setObjectName("smartdrive-monitoring")
        worker.moveToThread(thread)
        thread.started.connect(worker.start)
        worker.frame_ready.connect(self._on_frame)
        worker.failed.connect(self._on_worker_failed)
        worker.command_failed.connect(self.error_occurred)
        self._request_pause.connect(worker.set_paused)
        self._request_interval.connect(worker.set_interval)
        self._request_execute.connect(worker.execute)
        self._worker, self._thread = worker, thread
        thread.start()

    def _stop_worker(self) -> None:
        worker, thread = self._worker, self._thread
        self._worker = None
        self._thread = None
        if worker is None or thread is None:
            return
        for signal in (self._request_pause, self._request_interval, self._request_execute):
            signal.disconnect()
        worker.frame_ready.disconnect(self._on_frame)
        if thread.isRunning():
            QMetaObject.invokeMethod(worker, "stop", Qt.ConnectionType.BlockingQueuedConnection)
        thread.quit()
        if not thread.wait(THREAD_JOIN_TIMEOUT_MS):
            logger.error("Monitoring thread did not stop within timeout")

    def _start_recording(
        self,
        vehicle_id: int,
        data_source: DataSource,
        *,
        scenario: str | None = None,
        seed: int | None = None,
        name: str | None = None,
    ) -> bool:
        if not name:
            prefix = self._settings.trips.name_prefix.strip() or "Trip"
            name = f"{prefix} {datetime.now().astimezone():%Y-%m-%d %H:%M}"
        try:
            session = self._telemetry.start_session(
                vehicle_id, data_source, scenario=scenario, random_seed=seed, name=name
            )
        except SmartDriveError as exc:
            self.error_occurred.emit(exc.user_message)
            return False
        persistence = PersistenceWorker(self._telemetry, session.id)
        thread = QThread()
        thread.setObjectName("smartdrive-persistence")
        persistence.moveToThread(thread)
        thread.started.connect(persistence.start)
        persistence.persisted.connect(self._on_persisted)
        persistence.failed.connect(self.error_occurred)
        self._request_enqueue.connect(persistence.enqueue)
        self._persistence, self._persistence_thread = persistence, thread
        self._session_id = session.id
        self.persisted_count = 0
        thread.start()
        self.recording_changed.emit(session.id)
        return True

    def _stop_recording(self) -> int | None:
        persistence, thread = self._persistence, self._persistence_thread
        session_id = self._session_id
        self._persistence = None
        self._persistence_thread = None
        self._session_id = None
        if persistence is None or thread is None:
            return None
        self._request_enqueue.disconnect()
        if thread.isRunning():
            QMetaObject.invokeMethod(
                persistence, "stop", Qt.ConnectionType.BlockingQueuedConnection
            )
        thread.quit()
        if not thread.wait(THREAD_JOIN_TIMEOUT_MS):
            logger.error("Persistence thread did not stop within timeout")
        self.persisted_count = persistence.total_persisted
        self.recording_changed.emit(None)
        return session_id

    def _on_frame(self, frame: object) -> None:
        if not isinstance(frame, TelemetryFrame) or not self.is_active:
            return
        self.last_frame = frame
        if frame.sample is not None:
            last = self.buffer.last_elapsed
            if last is not None and last > frame.elapsed_s:
                self.buffer.clear()
            self.buffer.append(frame.elapsed_s, frame.sample)
            self.staleness.mark(self._clock())
            self.last_update_at = datetime.now(UTC)
            self._set_connection(ConnectionState.CONNECTED)
            if self._persistence is not None:
                self._request_enqueue.emit(frame.sample)
        else:
            self.frames_without_response += 1
            self._set_connection(ConnectionState.NO_RESPONSE)
        self.frame_received.emit(frame)
        if (
            self._source_kind is DataSource.REPLAY
            and not self.replay_finished
            and frame.elapsed_s >= self.replay_duration_s
        ):
            self.replay_finished = True
            self.pause()
            self.replay_changed.emit()

    def _on_persisted(self, total: int) -> None:
        self.persisted_count = total
        self.persisted_count_changed.emit(total)

    def _on_worker_failed(self, message: str) -> None:
        self.error_occurred.emit(message)
        if self._worker is not None and self._state is not MonitoringState.STOPPED:
            QTimer.singleShot(0, self.stop)

    def _check_staleness(self) -> None:
        if self._state is not MonitoringState.RUNNING:
            return
        if self._connection is ConnectionState.CONNECTED and self.staleness.is_stale(
            self._clock(), self.stale_threshold_s
        ):
            self._set_connection(ConnectionState.STALE)

    def _set_state(self, state: MonitoringState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)

    def _set_connection(self, connection: ConnectionState) -> None:
        if connection is not self._connection:
            self._connection = connection
            self.connection_changed.emit(connection)


def _as_replay(source: TelemetrySource) -> ReplaySource:
    if not isinstance(source, ReplaySource):
        raise TypeError("This operation is only available during a replay.")
    return source


class LiveFrameProducer(Protocol):
    """What the monitoring controller needs from the vehicle connection controller."""

    @property
    def frame_received(self) -> SignalInstance: ...

    @property
    def ecu_connected(self) -> bool: ...

    @property
    def is_mock(self) -> bool: ...

    @property
    def data_source(self) -> DataSource: ...

    @property
    def source_description(self) -> str: ...

    @property
    def unavailable_sensors(self) -> frozenset[str]: ...

    def begin_stream(self, interval_ms: int) -> bool: ...

    def end_stream(self) -> None: ...

    def set_stream_paused(self, paused: bool) -> None: ...


def _as_simulation(source: TelemetrySource) -> SimulationSource:
    if not isinstance(source, SimulationSource):
        raise TypeError("This operation is only available for the simulator.")
    return source
