"""Notification storage and deduplication, alert acknowledgement, retention and voice output.

The speech engine is always a fake here; no test produces sound.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pytestqt.qtbot import QtBot

from smartdrive.config.constants import NotificationCategory, NotificationSeverity, Severity
from smartdrive.database.connection import Database
from smartdrive.database.models import AlertRecord
from smartdrive.services.notification_service import NotificationService
from smartdrive.services.voice import (
    Announcement,
    AnnouncementQueue,
    NullSpeechBackend,
    VoiceInfo,
)
from smartdrive.ui.workers.voice_worker import VoiceConfig, VoiceWorker
from smartdrive.utils.exceptions import RecordNotFoundError

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
WARN = NotificationSeverity.WARNING
DIAG = NotificationCategory.DIAGNOSTIC


@pytest.fixture
def service(database: Database) -> NotificationService:
    return NotificationService(database)


class TestNotificationService:
    def test_repeats_within_cooldown_update_one_record(self, service: NotificationService) -> None:
        first = service.notify(WARN, DIAG, "Coolant high", dedup_key="k", now=T0, cooldown_s=300)
        repeat = service.notify(
            WARN, DIAG, "Coolant high", dedup_key="k", now=T0 + timedelta(seconds=60)
        )
        assert first.is_new and not repeat.is_new
        assert repeat.notification.id == first.notification.id
        assert repeat.notification.occurrence_count == 2
        later = service.notify(
            WARN, DIAG, "Coolant high", dedup_key="k", now=T0 + timedelta(hours=1)
        )
        assert later.is_new and later.notification.id != first.notification.id
        assert len(service.list_notifications()) == 2

    def test_escalation_within_cooldown_is_delivered_again(
        self, service: NotificationService
    ) -> None:
        service.notify(WARN, DIAG, "Coolant high", dedup_key="k", now=T0)
        service.mark_all_read()
        escalated = service.notify(
            NotificationSeverity.CRITICAL,
            DIAG,
            "Coolant critically high",
            dedup_key="k",
            now=T0 + timedelta(seconds=30),
        )
        assert escalated.is_new
        assert escalated.notification.severity is NotificationSeverity.CRITICAL
        assert escalated.notification.read_at is None
        assert len(service.list_notifications()) == 1

    def test_filters_read_and_unread(self, service: NotificationService) -> None:
        a = service.notify(WARN, DIAG, "Coolant high", now=T0).notification
        service.notify(
            NotificationSeverity.SUCCESS, NotificationCategory.TRIP, "Trip recorded", now=T0
        )
        service.notify(
            NotificationSeverity.INFORMATION,
            NotificationCategory.MAINTENANCE,
            "Oil upcoming",
            vehicle_id=None,
            now=T0 - timedelta(days=10),
        )
        assert service.unread_count() == 3
        assert [n.title for n in service.list_notifications(category="trip")] == ["Trip recorded"]
        assert [n.title for n in service.list_notifications(severity=WARN)] == ["Coolant high"]
        assert [n.title for n in service.list_notifications(search="oil")] == ["Oil upcoming"]
        recent = service.list_notifications(start=T0 - timedelta(days=1))
        assert {n.title for n in recent} == {"Coolant high", "Trip recorded"}
        service.mark_read(a.id)
        assert service.unread_count() == 2
        assert {n.title for n in service.list_notifications(unread_only=True)} == {
            "Trip recorded",
            "Oil upcoming",
        }
        assert service.mark_all_read() == 2
        assert service.unread_count() == 0
        with pytest.raises(RecordNotFoundError):
            service.mark_read(9999)

    def test_acknowledging_never_resolves_the_condition(
        self, service: NotificationService, database: Database
    ) -> None:
        with database.session() as s:
            alert = AlertRecord(
                created_at=T0,
                last_occurrence_at=T0,
                severity=Severity.CRITICAL,
                category="cooling",
                title="Coolant critically high",
                message="",
                dedup_key="v1:rule:coolant_high",
                occurrence_count=1,
            )
            s.add(alert)
            s.flush()
            alert_id = alert.id
        note = service.notify(
            NotificationSeverity.CRITICAL, DIAG, "Coolant critically high", alert_id=alert_id
        ).notification
        service.acknowledge(note.id)
        (linked,) = service.alerts()
        assert linked.acknowledged_at is not None
        assert linked.resolved_at is None and linked.condition_active
        assert "still active" in linked.state_text and "acknowledged" in linked.state_text
        assert service.alerts(active_only=True) == [linked]
        assert service.alert(alert_id) == linked
        assert service.latest_alert_id("v1:rule:coolant_high") == alert_id

    def test_retention_removes_only_old_read_notifications(
        self, service: NotificationService
    ) -> None:
        old = datetime.now(UTC) - timedelta(days=200)
        read_old = service.notify(WARN, DIAG, "Old read", now=old).notification
        service.notify(WARN, DIAG, "Old unread", now=old)
        service.notify(WARN, DIAG, "New read", now=datetime.now(UTC))
        service.mark_read(read_old.id)
        service.mark_read(service.list_notifications(search="New read")[0].id)
        assert service.purge(older_than_days=90) == 1
        assert {n.title for n in service.list_notifications()} == {"Old unread", "New read"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TestAnnouncementQueue:
    def test_duplicates_and_cooldown_are_suppressed(self) -> None:
        clock = FakeClock()
        queue = AnnouncementQueue(cooldown_s=60, clock=clock)
        assert queue.push(Announcement("a", "Coolant high"))
        assert not queue.push(Announcement("a", "Coolant high"))  # already queued
        assert queue.pop() == Announcement("a", "Coolant high")
        assert not queue.push(Announcement("a", "Coolant high"))  # spoken 0 s ago
        clock.now = 61
        assert queue.push(Announcement("a", "Coolant high"))
        assert queue.suppressed == 2

    def test_priority_order_and_bounded_size(self) -> None:
        queue = AnnouncementQueue(limit=2, clock=FakeClock())
        assert queue.push(Announcement("r", "Reminder", 1))
        assert queue.push(Announcement("w", "Warning", 5))
        assert queue.push(Announcement("c", "Critical", 10))  # evicts the reminder
        assert not queue.push(Announcement("r2", "Another reminder", 1))
        assert [queue.pop().key, queue.pop().key] == ["c", "w"]  # type: ignore[union-attr]
        assert queue.pop() is None
        assert queue.dropped == 2

    def test_text_is_bounded(self) -> None:
        queue = AnnouncementQueue(clock=FakeClock())
        queue.push(Announcement("long", "x" * 1000))
        item = queue.pop()
        assert item is not None and len(item.text) == 200


class RecordingBackend:
    def __init__(self, *, fail: bool = False) -> None:
        self.spoken: list[tuple[str, str | None, int, float]] = []
        self.closed = False
        self.fail = fail

    @property
    def available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    def voices(self) -> list[VoiceInfo]:
        return [VoiceInfo("v1", "Voice one")]

    def speak(self, text: str, *, voice_id: str | None, rate: int, volume: float) -> None:
        if self.fail:
            raise RuntimeError("engine crashed")
        self.spoken.append((text, voice_id, rate, volume))

    def close(self) -> None:
        self.closed = True


class TestVoiceWorker:
    """Slots are called directly; the threading is covered by the GUI tests."""

    def test_lifecycle_configuration_and_announcements(self, qtbot: QtBot) -> None:
        backend = RecordingBackend()
        worker = VoiceWorker(lambda: backend)
        ready: list[tuple[bool, str, object]] = []
        spoken: list[str] = []
        worker.ready.connect(lambda a, r, v: ready.append((a, r, v)))
        worker.spoken.connect(spoken.append)
        worker.start()
        assert ready == [(True, "", [VoiceInfo("v1", "Voice one")])]
        worker.enqueue(Announcement("k", "Warning: coolant high."))
        qtbot.wait(20)
        assert backend.spoken == []  # voice is off until configured
        worker.configure(VoiceConfig(True, "v1", 160, 0.5, 300.0))
        worker.enqueue(Announcement("k", "Warning: coolant high."))
        qtbot.waitUntil(lambda: spoken == ["k"])
        assert backend.spoken == [("Warning: coolant high.", "v1", 160, 0.5)]
        worker.enqueue(Announcement("k", "Warning: coolant high."))  # inside the cooldown
        qtbot.wait(20)
        assert len(backend.spoken) == 1
        worker.test_voice("Test")
        assert backend.spoken[-1][0] == "Test"
        worker.shutdown()
        assert backend.closed
        worker.enqueue(Announcement("x", "After shutdown"))
        assert len(backend.spoken) == 2

    def test_backend_failure_is_reported_not_raised(self, qtbot: QtBot) -> None:
        worker = VoiceWorker(lambda: RecordingBackend(fail=True))
        failures: list[str] = []
        worker.failed.connect(failures.append)
        worker.start()
        worker.configure(VoiceConfig(True, None, 175, 1.0, 300.0))
        worker.enqueue(Announcement("k", "Critical"))
        qtbot.waitUntil(lambda: bool(failures))
        assert "engine crashed" in failures[0]

    def test_unavailable_engine_explains_why(self) -> None:
        worker = VoiceWorker(lambda: NullSpeechBackend("No speech engine on this computer."))
        ready: list[tuple[bool, str]] = []
        failures: list[str] = []
        worker.ready.connect(lambda a, r, _v: ready.append((a, r)))
        worker.failed.connect(failures.append)
        worker.start()
        assert ready == [(False, "No speech engine on this computer.")]
        worker.test_voice("Hello")
        assert failures == ["No speech engine on this computer."]
