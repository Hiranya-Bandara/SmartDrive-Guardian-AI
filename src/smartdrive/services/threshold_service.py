"""Per-vehicle rule thresholds entered by the user.

The default thresholds are generic and conservative; they are not manufacturer specifications.
A user who has reliable figures for a vehicle (for example from its service documentation) can
override individual values. Overrides are validated with the same rules as the defaults.
"""

from __future__ import annotations

from typing import Final

from pydantic import ValidationError

from smartdrive.config.settings import DiagnosticThresholds
from smartdrive.database.connection import Database
from smartdrive.database.models import VehicleRecord, VehicleThresholdRecord
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError

OVERRIDABLE: Final = (
    "coolant_warning_c",
    "coolant_critical_c",
    "voltage_low_warning_v",
    "voltage_low_critical_v",
    "voltage_high_warning_v",
)


def merge(base: DiagnosticThresholds, overrides: dict[str, float]) -> DiagnosticThresholds:
    values = base.model_dump()
    values.update({k: v for k, v in overrides.items() if k in OVERRIDABLE})
    return DiagnosticThresholds.model_validate(values)


class ThresholdService:
    def __init__(self, database: Database) -> None:
        self._db = database

    def get(self, vehicle_id: int) -> tuple[dict[str, float], str]:
        with self._db.session() as session:
            record = session.get(VehicleThresholdRecord, vehicle_id)
            if record is None:
                return {}, ""
            return dict(record.values), record.source_note

    def save(
        self,
        vehicle_id: int,
        overrides: dict[str, float],
        *,
        source_note: str,
        base: DiagnosticThresholds,
    ) -> None:
        clean = {k: float(v) for k, v in overrides.items() if k in OVERRIDABLE}
        try:
            merge(base, clean)
        except ValidationError as exc:
            message = "; ".join(str(e["msg"]) for e in exc.errors())
            raise DataValidationError(str(exc), user_message=message) from exc
        with self._db.session() as session:
            if session.get(VehicleRecord, vehicle_id) is None:
                raise RecordNotFoundError(f"Vehicle {vehicle_id} does not exist.")
            record = session.get(VehicleThresholdRecord, vehicle_id)
            if not clean:
                if record is not None:
                    session.delete(record)
                return
            if record is None:
                record = VehicleThresholdRecord(vehicle_id=vehicle_id)
                session.add(record)
            record.values = clean
            record.source_note = source_note.strip()[:2000]
