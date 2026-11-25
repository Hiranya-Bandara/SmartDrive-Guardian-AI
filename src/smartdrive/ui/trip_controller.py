"""Trip lifecycle on the GUI side: summaries after recording, connection events, replay loading.

- When a recording ends, the trip summary is computed on the background job thread.
- While a live trip is recorded, connection loss and recovery are written to its timeline. If
  reconnection is exhausted, monitoring stops and the trip is marked *interrupted*.
- Replay: the trip's samples are loaded in the background, then handed to the monitoring
  controller, which plays them through the normal pipeline without recording anything and
  without involving any adapter.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from smartdrive.config.constants import Severity, TripEventType
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.services.replay_service import PLAYBACK_SPEEDS
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.trip_service import TripListItem, TripService
from smartdrive.ui.monitoring_controller import MonitoringController
from smartdrive.ui.vehicle_connection_controller import VehicleConnectionController
from smartdrive.ui.workers.task_runner import TaskRunner
from smartdrive.utils.exceptions import SmartDriveError

logger = logging.getLogger(__name__)


class TripController(QObject):
    trips_changed = Signal()
    trip_finalized = Signal(int)
    replay_loading = Signal(bool)
    message = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        trips: TripService,
        telemetry: TelemetryService,
        monitoring: MonitoringController,
        connection: VehicleConnectionController,
        tasks: TaskRunner,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.trips = trips
        self._telemetry = telemetry
        self._monitoring = monitoring
        self._connection = connection
        self._tasks = tasks
        self.recording_session_id: int | None = None
        self._interrupted: dict[int, str] = {}
        self._finalize_jobs: dict[int, int] = {}
        self._replay_job: int | None = None
        self._replay_speed = 1.0
        monitoring.recording_changed.connect(self._on_recording_changed)
        monitoring.trip_completed.connect(self._on_trip_completed)
        connection.link_lost.connect(self._on_link_lost)
        connection.link_restored.connect(self._on_link_restored)
        connection.link_failed.connect(self._on_link_failed)
        connection.report_changed.connect(self._on_report_changed)
        tasks.finished.connect(self._on_job_finished)
        tasks.failed.connect(self._on_job_failed)

    # -- recording ----------------------------------------------------------------------------

    def summarise_unfinished(self) -> None:
        """Summarise trips that ended without a summary (for example after a crash)."""
        self._tasks.submit("Summarise unfinished trips", self.trips.finalize_missing)

    def _on_recording_changed(self, session_id: object) -> None:
        self.recording_session_id = session_id if isinstance(session_id, int) else None
        self._connection.recording_session_id = self.recording_session_id
        self.trips_changed.emit()

    def _on_trip_completed(self, session_id: int) -> None:
        reason = self._interrupted.pop(session_id, None)

        def finalise() -> int:
            if reason is not None:
                self.trips.mark_interrupted(session_id, reason)
            self.trips.finalize(session_id)
            return session_id

        job = self._tasks.submit("Summarise trip", finalise)
        if job is None:
            self.error.emit("The trip summary could not be queued; it will be computed later.")
            return
        self._finalize_jobs[job] = session_id

    def _add_event(
        self, event_type: TripEventType, title: str, detail: str, severity: Severity
    ) -> None:
        session_id = self.recording_session_id
        if session_id is None or not self._monitoring.streaming_from_adapter:
            return
        try:
            self.trips.add_event(
                session_id, event_type, title, severity=severity, detail=detail, source="connection"
            )
        except SmartDriveError as exc:
            logger.warning("Could not record trip event", extra={"error": str(exc)})

    def _on_link_lost(self, message: str) -> None:
        self._add_event(
            TripEventType.CONNECTION_LOST,
            "Connection to the vehicle lost",
            message,
            Severity.WARNING,
        )

    def _on_link_restored(self) -> None:
        self._add_event(
            TripEventType.CONNECTION_RESTORED,
            "Connection to the vehicle restored",
            "",
            Severity.INFORMATION,
        )

    def _on_link_failed(self, message: str) -> None:
        if not self._monitoring.streaming_from_adapter:
            return
        if self.recording_session_id is not None:
            self._interrupted[self.recording_session_id] = message
        self._monitoring.stop()
        self.error.emit(f"Live monitoring stopped: {message}")

    def _on_report_changed(self, report: object) -> None:
        # The user disconnected (or the adapter went away) while live data was streaming.
        if report is None and self._monitoring.streaming_from_adapter:
            self._monitoring.stop()

    # -- replay -------------------------------------------------------------------------------

    @property
    def replay_loading_active(self) -> bool:
        return self._replay_job is not None

    def start_replay(self, session_id: int, *, speed: float = 1.0) -> bool:
        if self._monitoring.is_active:
            self.error.emit("Stop monitoring before replaying a trip.")
            return False
        if self._replay_job is not None:
            return False
        if speed not in PLAYBACK_SPEEDS:
            speed = 1.0
        self._replay_speed = speed

        def load() -> tuple[TripListItem, list[TelemetrySample]]:
            return self.trips.get_trip(session_id), self._telemetry.load_samples(session_id)

        job = self._tasks.submit("Load trip for replay", load)
        if job is None:
            self.error.emit("The trip could not be loaded right now. Try again shortly.")
            return False
        self._replay_job = job
        self.replay_loading.emit(True)
        return True

    # -- job results --------------------------------------------------------------------------

    def _on_job_finished(self, job_id: int, result: object) -> None:
        if job_id in self._finalize_jobs:
            session_id = self._finalize_jobs.pop(job_id)
            self.trip_finalized.emit(session_id)
            self.trips_changed.emit()
            return
        if job_id == self._replay_job:
            self._replay_job = None
            self.replay_loading.emit(False)
            if not isinstance(result, tuple):
                return
            trip, samples = result
            if not samples:
                self.error.emit("This trip has no recorded telemetry to replay.")
                return
            if self._monitoring.is_active:
                self.error.emit("Monitoring started while the trip was loading; replay cancelled.")
                return
            self._monitoring.start_replay(
                samples,
                session_id=trip.session.id,
                original_source=trip.session.data_source,
                speed=self._replay_speed,
            )

    def _on_job_failed(self, job_id: int, message: str) -> None:
        if job_id in self._finalize_jobs:
            self._finalize_jobs.pop(job_id)
            self.error.emit(message)
        elif job_id == self._replay_job:
            self._replay_job = None
            self.replay_loading.emit(False)
            self.error.emit(message)
