"""Application notifications and diagnostic alert state for the Alert Centre.

Notification policy:
- Notifications are deduplicated on a key (for example ``conn:lost`` or ``maint:v3:s7:overdue``).
  A repeat within the cooldown updates the existing record (count and time) and is *not*
  delivered again; after the cooldown a new record is created and delivered.
- Reading or acknowledging a notification never changes the state of the vehicle condition it
  refers to. Diagnostic alerts carry their own ``resolved_at``, set only by the diagnostic
  service when the finding is no longer present in an analysis with sufficient data.
- Retention removes read notifications older than the configured number of days.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from smartdrive.config.constants import NotificationCategory, NotificationSeverity, Severity
from smartdrive.database.connection import Database
from smartdrive.database.models import AlertRecord, NotificationRecord
from smartdrive.database.types import utc_now
from smartdrive.models.notification import DiagnosticAlert, Notification
from smartdrive.utils.exceptions import RecordNotFoundError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotifyOutcome:
    notification: Notification
    is_new: bool


class NotificationService:
    def __init__(self, database: Database) -> None:
        self._db = database

    # -- notifications --------------------------------------------------------------------------

    def notify(
        self,
        severity: NotificationSeverity,
        category: NotificationCategory,
        title: str,
        message: str = "",
        *,
        dedup_key: str | None = None,
        vehicle_id: int | None = None,
        alert_id: int | None = None,
        cooldown_s: float = 300.0,
        now: datetime | None = None,
    ) -> NotifyOutcome:
        timestamp = now or utc_now()
        key = (dedup_key or f"{category.value}:{title}")[:160]
        with self._db.session() as session:
            existing = session.scalar(
                select(NotificationRecord)
                .where(NotificationRecord.dedup_key == key)
                .order_by(NotificationRecord.last_occurrence_at.desc())
                .limit(1)
            )
            if existing is not None and timestamp - existing.last_occurrence_at <= timedelta(
                seconds=cooldown_s
            ):
                existing.occurrence_count += 1
                existing.last_occurrence_at = timestamp
                if _rank(severity) > _rank(existing.severity):
                    existing.severity = severity
                    existing.title = title[:160]
                    existing.message = message
                    existing.read_at = None
                    existing.acknowledged_at = None
                    session.flush()
                    return NotifyOutcome(Notification.model_validate(existing), True)
                session.flush()
                return NotifyOutcome(Notification.model_validate(existing), False)
            record = NotificationRecord(
                created_at=timestamp,
                last_occurrence_at=timestamp,
                severity=severity,
                category=category.value,
                title=title[:160],
                message=message,
                vehicle_id=vehicle_id,
                alert_id=alert_id,
                dedup_key=key,
                occurrence_count=1,
            )
            session.add(record)
            session.flush()
            return NotifyOutcome(Notification.model_validate(record), True)

    def list_notifications(
        self,
        *,
        unread_only: bool = False,
        severity: NotificationSeverity | None = None,
        category: str | None = None,
        vehicle_id: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        search: str = "",
        limit: int = 500,
    ) -> list[Notification]:
        stmt = select(NotificationRecord).order_by(NotificationRecord.last_occurrence_at.desc())
        if unread_only:
            stmt = stmt.where(NotificationRecord.read_at.is_(None))
        if severity is not None:
            stmt = stmt.where(NotificationRecord.severity == severity)
        if category:
            stmt = stmt.where(NotificationRecord.category == category)
        if vehicle_id is not None:
            stmt = stmt.where(NotificationRecord.vehicle_id == vehicle_id)
        if start is not None:
            stmt = stmt.where(NotificationRecord.last_occurrence_at >= start)
        if end is not None:
            stmt = stmt.where(NotificationRecord.created_at <= end)
        text = search.strip()
        if text:
            pattern = f"%{text}%"
            stmt = stmt.where(
                NotificationRecord.title.ilike(pattern) | NotificationRecord.message.ilike(pattern)
            )
        with self._db.session() as session:
            return [Notification.model_validate(r) for r in session.scalars(stmt.limit(limit))]

    def unread_count(self, *, vehicle_id: int | None = None) -> int:
        stmt = select(func.count()).where(NotificationRecord.read_at.is_(None))
        if vehicle_id is not None:
            stmt = stmt.where(
                (NotificationRecord.vehicle_id == vehicle_id)
                | NotificationRecord.vehicle_id.is_(None)
            )
        with self._db.session() as session:
            return int(session.scalar(stmt) or 0)

    def mark_read(self, notification_id: int) -> None:
        with self._db.session() as session:
            record = self._require(session, notification_id)
            if record.read_at is None:
                record.read_at = utc_now()

    def mark_all_read(self) -> int:
        with self._db.session() as session:
            result = session.execute(
                update(NotificationRecord)
                .where(NotificationRecord.read_at.is_(None))
                .values(read_at=utc_now())
            )
            return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def acknowledge(self, notification_id: int) -> None:
        """Acknowledge a notification (also marks it read). Linked conditions are unaffected."""
        with self._db.session() as session:
            record = self._require(session, notification_id)
            now = utc_now()
            record.acknowledged_at = record.acknowledged_at or now
            record.read_at = record.read_at or now
            if record.alert_id is not None:
                alert = session.get(AlertRecord, record.alert_id)
                if alert is not None and alert.acknowledged_at is None:
                    alert.acknowledged_at = now
                    alert.read_at = alert.read_at or now

    def purge(self, *, older_than_days: int) -> int:
        cutoff = utc_now() - timedelta(days=older_than_days)
        with self._db.session() as session:
            result = session.execute(
                delete(NotificationRecord).where(
                    NotificationRecord.read_at.is_not(None),
                    NotificationRecord.last_occurrence_at < cutoff,
                )
            )
            return int(result.rowcount or 0)  # type: ignore[attr-defined]

    @staticmethod
    def _require(session: Session, notification_id: int) -> NotificationRecord:
        record = session.get(NotificationRecord, notification_id)
        if record is None:
            raise RecordNotFoundError(f"Notification {notification_id} does not exist.")
        return record

    # -- diagnostic alerts ----------------------------------------------------------------------

    def alerts(
        self,
        *,
        active_only: bool = False,
        vehicle_id: int | None = None,
        severity: Severity | None = None,
        source: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        search: str = "",
        limit: int = 500,
    ) -> list[DiagnosticAlert]:
        stmt = select(AlertRecord).order_by(AlertRecord.last_occurrence_at.desc())
        if active_only:
            stmt = stmt.where(AlertRecord.resolved_at.is_(None))
        if vehicle_id is not None:
            stmt = stmt.where(AlertRecord.vehicle_id == vehicle_id)
        if severity is not None:
            stmt = stmt.where(AlertRecord.severity == severity)
        if source:
            stmt = stmt.where(AlertRecord.source == source)
        if start is not None:
            stmt = stmt.where(AlertRecord.last_occurrence_at >= start)
        if end is not None:
            stmt = stmt.where(AlertRecord.created_at <= end)
        text = search.strip()
        if text:
            pattern = f"%{text}%"
            stmt = stmt.where(AlertRecord.title.ilike(pattern) | AlertRecord.message.ilike(pattern))
        with self._db.session() as session:
            return [DiagnosticAlert.model_validate(r) for r in session.scalars(stmt.limit(limit))]

    def alert(self, alert_id: int) -> DiagnosticAlert | None:
        with self._db.session() as session:
            record = session.get(AlertRecord, alert_id)
            return None if record is None else DiagnosticAlert.model_validate(record)

    def acknowledge_alert(self, alert_id: int) -> None:
        with self._db.session() as session:
            alert = session.get(AlertRecord, alert_id)
            if alert is None:
                raise RecordNotFoundError(f"Alert {alert_id} does not exist.")
            now = utc_now()
            alert.acknowledged_at = alert.acknowledged_at or now
            alert.read_at = alert.read_at or now

    def latest_alert_id(self, dedup_key: str) -> int | None:
        with self._db.session() as session:
            return session.scalar(
                select(AlertRecord.id)
                .where(AlertRecord.dedup_key == dedup_key)
                .order_by(AlertRecord.last_occurrence_at.desc())
                .limit(1)
            )


_RANK = {
    NotificationSeverity.INFORMATION: 0,
    NotificationSeverity.SUCCESS: 0,
    NotificationSeverity.WARNING: 1,
    NotificationSeverity.CRITICAL: 2,
}


def _rank(severity: NotificationSeverity) -> int:
    return _RANK[severity]
