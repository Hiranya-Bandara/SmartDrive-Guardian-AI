"""Trip statistics, distance estimation, timelines, filtering, deletion and replay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from smartdrive.config.constants import (
    DataSource,
    DiagnosticSource,
    FaultCategory,
    MaintenanceStatus,
    SessionStatus,
    Severity,
    TripEventType,
)
from smartdrive.database.connection import Database
from smartdrive.database.models import (
    AlertRecord,
    DiagnosticResultRecord,
    MaintenanceRecord,
    TelemetryReadingRecord,
)
from smartdrive.models.telemetry import TelemetrySample
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.services.replay_service import PLAYBACK_SPEEDS, ReplaySource
from smartdrive.services.telemetry_service import TelemetryService
from smartdrive.services.trip_service import TripService, compute_statistics, integrate_distance
from smartdrive.services.vehicle_service import VehicleService
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


def sample(t: float, **values: float | None) -> TelemetrySample:
    return TelemetrySample(timestamp=T0 + timedelta(seconds=t), **values)  # type: ignore[arg-type]


class TestStatistics:
    def test_constant_speed_distance_is_speed_times_time(self) -> None:
        samples = [sample(t, speed_kph=36.0) for t in range(0, 101)]  # 36 km/h = 10 m/s
        distance, covered = integrate_distance(samples)
        assert covered == 100.0
        assert distance == pytest.approx(1.0)

    def test_irregular_intervals_use_each_actual_interval(self) -> None:
        times = [0, 1, 3, 4, 8]  # every gap is at most 5 s
        samples = [sample(t, speed_kph=72.0) for t in times]  # 20 m/s
        distance, covered = integrate_distance(samples)
        assert covered == 8.0
        assert distance == pytest.approx(0.16)

    def test_long_gaps_and_missing_speeds_are_not_bridged(self) -> None:
        samples = [
            sample(0, speed_kph=36.0),
            sample(1, speed_kph=36.0),
            sample(60, speed_kph=36.0),  # 59 s gap: not bridged
            sample(61, speed_kph=None),  # missing reading breaks the chain
            sample(62, speed_kph=36.0),
            sample(63, speed_kph=36.0),
        ]
        distance, covered = integrate_distance(samples)
        assert covered == 2.0
        assert distance == pytest.approx(0.02)
        stats = compute_statistics(samples)
        assert stats.distance_coverage == pytest.approx(2.0 / 63.0, abs=1e-4)

    def test_no_speed_means_no_distance_and_no_invented_values(self) -> None:
        samples = [sample(t, rpm=900.0) for t in range(10)]
        stats = compute_statistics(samples)
        assert stats.distance_km is None
        assert stats.avg_speed_kph is None and stats.max_speed_kph is None
        assert stats.min_coolant_c is None
        assert stats.avg_rpm == 900.0
        assert compute_statistics([]).sample_count == 0

    def test_statistics_ignore_missing_readings_instead_of_zero_filling(self) -> None:
        samples = [
            sample(0, speed_kph=40.0, rpm=1000.0, coolant_temp_c=80.0),
            sample(1, speed_kph=None, rpm=3000.0, coolant_temp_c=None),
            sample(2, speed_kph=60.0, rpm=None, coolant_temp_c=90.0),
        ]
        stats = compute_statistics(samples)
        assert stats.avg_speed_kph == 50.0
        assert stats.max_rpm == 3000.0
        assert (stats.min_coolant_c, stats.max_coolant_c) == (80.0, 90.0)
        assert stats.recorded_duration_s == 2.0
        assert 0 < stats.data_completeness < 1


@pytest.fixture
def services(database: Database) -> tuple[TelemetryService, TripService]:
    telemetry = TelemetryService(database)
    return telemetry, TripService(database, telemetry)


@pytest.fixture
def vehicle_id(database: Database, vehicle_profile: VehicleProfile, tmp_path: object) -> int:
    from pathlib import Path

    return VehicleService(database, Path(str(tmp_path)) / "img").add(vehicle_profile).id


def record_trip(
    telemetry: TelemetryService,
    vehicle_id: int,
    *,
    source: DataSource = DataSource.SIMULATION,
    seconds: int = 120,
    name: str | None = None,
    start: datetime = T0,
) -> int:
    session = telemetry.start_session(vehicle_id, source, name=name, started_at=start)
    samples = [
        TelemetrySample(
            timestamp=start + timedelta(seconds=t),
            speed_kph=50.0,
            rpm=2000.0,
            coolant_temp_c=85.0 + t / 10,
        )
        for t in range(seconds)
    ]
    telemetry.append(session.id, samples)
    telemetry.end_session(session.id)
    return session.id


def add_finding(
    database: Database,
    vehicle_id: int,
    session_id: int,
    at: datetime,
    severity: Severity,
    key: str = "rule:coolant_high",
) -> None:
    with database.session() as s:
        s.add(
            DiagnosticResultRecord(
                vehicle_id=vehicle_id,
                session_id=session_id,
                created_at=at,
                category=FaultCategory.COOLING,
                severity=severity,
                source=DiagnosticSource.RULE,
                summary="Coolant temperature high",
                recommendation="",
                explanation={"text": "rule"},
                finding_key=key,
                data_source=DataSource.SIMULATION,
            )
        )


class TestTripService:
    def test_finalize_stores_summary_and_one_event_per_episode(
        self, database: Database, services: tuple[TelemetryService, TripService], vehicle_id: int
    ) -> None:
        telemetry, trips = services
        trip = record_trip(telemetry, vehicle_id)
        # A warning persisting for 30 s, escalating to critical, then a new episode after a gap.
        for t in range(0, 30, 10):
            add_finding(database, vehicle_id, trip, T0 + timedelta(seconds=t), Severity.WARNING)
        add_finding(database, vehicle_id, trip, T0 + timedelta(seconds=35), Severity.CRITICAL)
        add_finding(database, vehicle_id, trip, T0 + timedelta(seconds=45), Severity.CRITICAL)
        add_finding(database, vehicle_id, trip, T0 + timedelta(seconds=200), Severity.WARNING)
        summary = trips.finalize(trip)
        assert summary["sample_count"] == 120
        assert summary["distance_km"] == pytest.approx(50.0 * 119 / 3600, abs=1e-3)
        assert summary["diagnostic_event_count"] == 3
        assert (summary["warning_count"], summary["critical_count"]) == (2, 1)
        events = trips.events(trip)
        assert [e.severity for e in events] == [
            Severity.WARNING,
            Severity.CRITICAL,
            Severity.WARNING,
        ]
        # Finalising twice does not duplicate events.
        trips.finalize(trip)
        assert len(trips.events(trip)) == 3

    def test_interrupted_trip_is_marked_with_an_event(
        self, services: tuple[TelemetryService, TripService], vehicle_id: int
    ) -> None:
        telemetry, trips = services
        trip = record_trip(telemetry, vehicle_id, source=DataSource.LIVE)
        trips.mark_interrupted(trip, "Adapter unplugged")
        trips.finalize(trip)
        item = trips.get_trip(trip)
        assert item.session.status is SessionStatus.INTERRUPTED
        (event,) = trips.events(trip)
        assert event.event_type is TripEventType.RECORDING_INTERRUPTED
        assert event.detail == "Adapter unplugged"

    def test_filters(
        self,
        database: Database,
        services: tuple[TelemetryService, TripService],
        vehicle_id: int,
    ) -> None:
        telemetry, trips = services
        sim = record_trip(telemetry, vehicle_id, name="Morning test drive")
        live = record_trip(
            telemetry, vehicle_id, source=DataSource.LIVE, start=T0 + timedelta(days=3)
        )
        add_finding(database, vehicle_id, live, T0 + timedelta(days=3), Severity.CRITICAL)
        trips.finalize(sim)
        trips.finalize(live)
        assert [t.session.id for t in trips.list_trips()] == [live, sim]
        assert [t.session.id for t in trips.list_trips(data_source=DataSource.LIVE)] == [live]
        assert [t.session.id for t in trips.list_trips(search="morning")] == [sim]
        assert [t.session.id for t in trips.list_trips(min_severity=Severity.CRITICAL)] == [live]
        assert trips.list_trips(start=T0 + timedelta(days=1), end=T0 + timedelta(days=2)) == []
        assert trips.list_trips(vehicle_id=vehicle_id + 99) == []
        assert trips.get_trip(live).worst_severity is Severity.CRITICAL

    def test_delete_removes_trip_data_but_keeps_unrelated_records(
        self,
        database: Database,
        services: tuple[TelemetryService, TripService],
        vehicle_id: int,
    ) -> None:
        telemetry, trips = services
        trip = record_trip(telemetry, vehicle_id)
        keep = record_trip(telemetry, vehicle_id, start=T0 + timedelta(hours=2))
        add_finding(database, vehicle_id, trip, T0, Severity.WARNING)
        with database.session() as s:
            s.add(
                AlertRecord(
                    vehicle_id=vehicle_id,
                    session_id=trip,
                    created_at=T0,
                    last_occurrence_at=T0,
                    severity=Severity.WARNING,
                    category="cooling",
                    title="Coolant",
                    message="",
                    dedup_key="k",
                    occurrence_count=1,
                )
            )
            s.add(
                MaintenanceRecord(
                    vehicle_id=vehicle_id,
                    title="Oil",
                    category="engine_oil",
                    status=MaintenanceStatus.COMPLETED,
                )
            )
        trips.finalize(trip)
        trips.delete_trip(trip)
        with pytest.raises(RecordNotFoundError):
            trips.get_trip(trip)
        with database.session() as s:
            assert s.query(TelemetryReadingRecord).filter_by(session_id=trip).count() == 0
            assert s.query(TelemetryReadingRecord).filter_by(session_id=keep).count() == 120
            finding = s.query(DiagnosticResultRecord).one()
            assert finding.session_id is None
            alert = s.query(AlertRecord).one()
            assert alert.session_id is None
            assert s.query(MaintenanceRecord).count() == 1

    def test_a_trip_still_recording_cannot_be_deleted(
        self, services: tuple[TelemetryService, TripService], vehicle_id: int
    ) -> None:
        telemetry, trips = services
        session = telemetry.start_session(vehicle_id, DataSource.SIMULATION)
        with pytest.raises(DataValidationError):
            trips.delete_trip(session.id)


class TestReplay:
    def samples(self) -> list[TelemetrySample]:
        return [sample(t, speed_kph=float(t)) for t in (0, 1, 2, 4, 8, 10)]

    def test_playback_follows_original_timing_and_provenance(self) -> None:
        source = ReplaySource(
            self.samples(), session_id=7, original_source=DataSource.LIVE, speed=1.0
        )
        assert source.duration_s == 10.0
        frames = source.read_frames(1.5)
        assert [f.elapsed_s for f in frames] == [0.0, 1.0]
        assert all(f.source is DataSource.REPLAY for f in frames)
        assert frames[0].sample is not None and frames[0].sample.timestamp == T0
        assert [f.elapsed_s for f in source.read_frames(1.5)] == [2.0]

    def test_speed_scales_playback(self) -> None:
        for speed in PLAYBACK_SPEEDS:
            source = ReplaySource(
                self.samples(), session_id=1, original_source=DataSource.SIMULATION, speed=speed
            )
            emitted = [f.elapsed_s for f in source.read_frames(2.0)]
            assert emitted == [t for t in (0, 1, 2, 4, 8, 10) if t <= 2.0 * speed]
        with pytest.raises(ValueError):
            ReplaySource(self.samples(), session_id=1, original_source=DataSource.LIVE, speed=3.0)

    def test_seek_never_emits_future_samples(self) -> None:
        source = ReplaySource(self.samples(), session_id=1, original_source=DataSource.SIMULATION)
        source.seek(4.0)
        assert [f.elapsed_s for f in source.read_frames(0.0)] == [4.0]
        assert source.read_frames(3.0) == []  # position 7: the 8 s sample is still future
        assert [f.elapsed_s for f in source.read_frames(1.0)] == [8.0]
        source.seek(0.5)
        assert [f.elapsed_s for f in source.read_frames(0.6)] == [1.0]

    def test_finished_and_original_samples_are_unchanged(self) -> None:
        original = self.samples()
        source = ReplaySource(original, session_id=1, original_source=DataSource.SIMULATION)
        frames = source.read_frames(100.0)
        assert len(frames) == len(original)
        assert source.finished
        assert source.read_frames(1.0) == []
        assert [f.sample for f in frames] == original

    def test_empty_trip_cannot_be_replayed(self) -> None:
        with pytest.raises(ValueError):
            ReplaySource([], session_id=1, original_source=DataSource.SIMULATION)
