"""Persistence for adapter connections and read-only trouble-code scans.

Scanning upserts one row per (vehicle, code, status): the first and most recent detection times
and a detection count are kept, and a code missing from a later scan of the same status is
marked inactive rather than deleted, so history is never lost. Nothing here talks to hardware.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from smartdrive.config.constants import DataSource, DtcStatus
from smartdrive.database.connection import Database
from smartdrive.database.models import (
    DiagnosticResultRecord,
    DiagnosticTroubleCodeRecord,
    DtcScanRecord,
    ObdConnectionRecord,
)
from smartdrive.database.types import utc_now
from smartdrive.models.trouble_code import DtcScan, ObdConnection, TroubleCode
from smartdrive.obd.session import ConnectionReport, DtcScanResult
from smartdrive.services.dtc_reference import lookup

logger = logging.getLogger(__name__)


class ObdHistoryService:
    def __init__(self, database: Database) -> None:
        self._db = database

    # -- connections ----------------------------------------------------------------------------

    def record_connection(
        self, report: ConnectionReport, *, vehicle_id: int | None, connection_method: str
    ) -> int:
        capabilities = report.capabilities
        with self._db.session() as session:
            record = ObdConnectionRecord(
                vehicle_id=vehicle_id,
                started_at=report.connected_at,
                port=report.port,
                connection_method=connection_method[:48],
                is_mock=report.is_mock,
                baudrate=report.baudrate,
                adapter_version=report.adapter.version[:64],
                adapter_description=(report.adapter.device_description or None),
                ecu_connected=report.ecu_connected,
                protocol=report.protocol_name,
                supported_pids=sorted(capabilities.supported_pids) if capabilities else [],
                missing_sensors=list(capabilities.missing_sample_fields) if capabilities else [],
            )
            session.add(record)
            session.flush()
            return record.id

    def update_connection(
        self,
        connection_id: int,
        *,
        report: ConnectionReport | None = None,
        samples_received: int | None = None,
    ) -> None:
        with self._db.session() as session:
            record = session.get(ObdConnectionRecord, connection_id)
            if record is None:
                return
            if report is not None:
                record.ecu_connected = report.ecu_connected
                record.protocol = report.protocol_name
                if report.capabilities is not None:
                    record.supported_pids = sorted(report.capabilities.supported_pids)
                    record.missing_sensors = list(report.capabilities.missing_sample_fields)
            if samples_received is not None:
                record.samples_received = samples_received

    def end_connection(
        self, connection_id: int, *, reason: str, samples_received: int | None = None
    ) -> None:
        with self._db.session() as session:
            record = session.get(ObdConnectionRecord, connection_id)
            if record is None or record.ended_at is not None:
                return
            record.ended_at = max(utc_now(), record.started_at)
            record.end_reason = reason[:200]
            if samples_received is not None:
                record.samples_received = samples_received

    def close_orphaned_connections(self) -> int:
        with self._db.session() as session:
            rows = list(
                session.scalars(
                    select(ObdConnectionRecord).where(ObdConnectionRecord.ended_at.is_(None))
                )
            )
            for row in rows:
                row.ended_at = row.started_at
                row.end_reason = "Application closed without disconnecting"
            return len(rows)

    def connections(self, *, vehicle_id: int | None = None, limit: int = 50) -> list[ObdConnection]:
        stmt = select(ObdConnectionRecord).order_by(ObdConnectionRecord.started_at.desc())
        if vehicle_id is not None:
            stmt = stmt.where(ObdConnectionRecord.vehicle_id == vehicle_id)
        with self._db.session() as session:
            return [ObdConnection.model_validate(r) for r in session.scalars(stmt.limit(limit))]

    # -- trouble codes --------------------------------------------------------------------------

    def record_scan(
        self,
        vehicle_id: int,
        result: DtcScanResult,
        *,
        data_source: DataSource,
        is_mock: bool,
        protocol: str | None = None,
        connection_id: int | None = None,
        session_id: int | None = None,
    ) -> DtcScan:
        codes = result.codes()
        scanned_statuses = [DtcStatus.STORED, DtcStatus.PENDING]
        if result.permanent is not None:
            scanned_statuses.append(DtcStatus.PERMANENT)
        with self._db.session() as session:
            scan = DtcScanRecord(
                vehicle_id=vehicle_id,
                connection_id=connection_id,
                session_id=session_id,
                scanned_at=result.scanned_at,
                data_source=data_source,
                is_mock=is_mock,
                protocol=protocol,
                mil_on=result.mil_on,
                reported_count=result.reported_count,
                stored_count=len(result.stored),
                pending_count=len(result.pending),
                permanent_count=None if result.permanent is None else len(result.permanent),
                codes=[{"code": c, "status": s.value} for c, s in codes],
                freeze_frame=None
                if result.freeze_frame is None
                else {
                    "trigger_code": result.freeze_frame.trigger_code,
                    "values": dict(result.freeze_frame.values),
                },
                notes=list(result.notes),
            )
            session.add(scan)
            session.flush()
            seen: set[tuple[str, DtcStatus]] = set()
            for code, status in codes:
                seen.add((code, status))
                info = lookup(code)
                existing = session.scalar(
                    select(DiagnosticTroubleCodeRecord).where(
                        DiagnosticTroubleCodeRecord.vehicle_id == vehicle_id,
                        DiagnosticTroubleCodeRecord.code == code,
                        DiagnosticTroubleCodeRecord.status == status,
                    )
                )
                if existing is None:
                    session.add(
                        DiagnosticTroubleCodeRecord(
                            vehicle_id=vehicle_id,
                            session_id=session_id,
                            code=code,
                            status=status,
                            description=info.display_description[:255],
                            description_source=info.source[:120],
                            first_seen_at=result.scanned_at,
                            last_seen_at=result.scanned_at,
                            last_scan_id=scan.id,
                            detection_count=1,
                            is_active=True,
                        )
                    )
                else:
                    existing.last_seen_at = result.scanned_at
                    existing.last_scan_id = scan.id
                    existing.detection_count += 1
                    existing.is_active = True
            for record in session.scalars(
                select(DiagnosticTroubleCodeRecord).where(
                    DiagnosticTroubleCodeRecord.vehicle_id == vehicle_id,
                    DiagnosticTroubleCodeRecord.status.in_(scanned_statuses),
                    DiagnosticTroubleCodeRecord.is_active.is_(True),
                )
            ):
                if (record.code, record.status) not in seen:
                    record.is_active = False
            session.flush()
            return DtcScan.model_validate(scan)

    def trouble_codes(
        self,
        vehicle_id: int,
        *,
        active_only: bool = False,
        status: DtcStatus | None = None,
        category: str | None = None,
        search: str = "",
    ) -> list[TroubleCode]:
        stmt = (
            select(DiagnosticTroubleCodeRecord)
            .where(DiagnosticTroubleCodeRecord.vehicle_id == vehicle_id)
            .order_by(
                DiagnosticTroubleCodeRecord.is_active.desc(),
                DiagnosticTroubleCodeRecord.last_seen_at.desc(),
                DiagnosticTroubleCodeRecord.code,
            )
        )
        if active_only:
            stmt = stmt.where(DiagnosticTroubleCodeRecord.is_active.is_(True))
        if status is not None:
            stmt = stmt.where(DiagnosticTroubleCodeRecord.status == status)
        if category:
            stmt = stmt.where(DiagnosticTroubleCodeRecord.code.startswith(category[:1].upper()))
        text = search.strip()
        if text:
            pattern = f"%{text}%"
            stmt = stmt.where(
                DiagnosticTroubleCodeRecord.code.ilike(pattern)
                | DiagnosticTroubleCodeRecord.description.ilike(pattern)
            )
        with self._db.session() as session:
            return [TroubleCode.model_validate(r) for r in session.scalars(stmt)]

    def active_code_count(self, vehicle_id: int, status: DtcStatus = DtcStatus.STORED) -> int:
        with self._db.session() as session:
            return int(
                session.scalar(
                    select(func.count()).where(
                        DiagnosticTroubleCodeRecord.vehicle_id == vehicle_id,
                        DiagnosticTroubleCodeRecord.status == status,
                        DiagnosticTroubleCodeRecord.is_active.is_(True),
                    )
                )
                or 0
            )

    def scans(self, vehicle_id: int, *, limit: int = 50) -> list[DtcScan]:
        stmt = (
            select(DtcScanRecord)
            .where(DtcScanRecord.vehicle_id == vehicle_id)
            .order_by(DtcScanRecord.scanned_at.desc(), DtcScanRecord.id.desc())
            .limit(limit)
        )
        with self._db.session() as session:
            return [DtcScan.model_validate(r) for r in session.scalars(stmt)]

    def related_findings(
        self, vehicle_id: int, around: datetime, *, window_minutes: int = 30, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Diagnostic findings recorded near a scan, shown as context next to the codes."""
        start, end = around - timedelta(minutes=window_minutes), around + timedelta(minutes=5)
        stmt = (
            select(DiagnosticResultRecord)
            .where(
                DiagnosticResultRecord.vehicle_id == vehicle_id,
                DiagnosticResultRecord.created_at >= start,
                DiagnosticResultRecord.created_at <= end,
            )
            .order_by(DiagnosticResultRecord.created_at.desc())
            .limit(limit)
        )
        with self._db.session() as session:
            return [
                {
                    "created_at": r.created_at,
                    "summary": r.summary,
                    "severity": r.severity.value,
                    "source": r.source.value,
                    "data_source": r.data_source.value if r.data_source else None,
                }
                for r in session.scalars(stmt)
            ]

    def delete_vehicle_scans(self, vehicle_id: int) -> int:
        """Remove a vehicle's trouble-code history (user-requested data deletion)."""
        with self._db.session() as session:
            session.execute(
                delete(DiagnosticTroubleCodeRecord).where(
                    DiagnosticTroubleCodeRecord.vehicle_id == vehicle_id
                )
            )
            result = session.execute(
                delete(DtcScanRecord).where(DtcScanRecord.vehicle_id == vehicle_id)
            )
            return int(result.rowcount or 0)  # type: ignore[attr-defined]
