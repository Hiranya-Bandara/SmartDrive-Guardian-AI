from __future__ import annotations

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from smartdrive.config.constants import FuelType
from smartdrive.database.models import VehicleRecord
from smartdrive.models.vehicle import Vehicle, VehicleProfile
from smartdrive.utils.exceptions import DataValidationError, RecordNotFoundError


def _profile_values(profile: VehicleProfile) -> dict[str, object]:
    """Only user-editable profile fields; never ids, timestamps or the active flag."""
    return profile.model_dump(include=set(VehicleProfile.model_fields))


class VehicleRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, profile: VehicleProfile) -> Vehicle:
        record = VehicleRecord(**_profile_values(profile))
        self._session.add(record)
        self._flush()
        return Vehicle.model_validate(record)

    def get(self, vehicle_id: int) -> Vehicle:
        return Vehicle.model_validate(self._require(vehicle_id))

    def list_vehicles(
        self, *, search: str | None = None, fuel_type: FuelType | None = None
    ) -> list[Vehicle]:
        stmt = select(VehicleRecord).order_by(func.lower(VehicleRecord.name), VehicleRecord.id)
        if search and search.strip():
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(VehicleRecord.name).like(pattern),
                    func.lower(VehicleRecord.manufacturer).like(pattern),
                    func.lower(VehicleRecord.model).like(pattern),
                )
            )
        if fuel_type is not None:
            stmt = stmt.where(VehicleRecord.fuel_type == fuel_type)
        return [Vehicle.model_validate(r) for r in self._session.scalars(stmt)]

    def update(self, vehicle_id: int, profile: VehicleProfile) -> Vehicle:
        record = self._require(vehicle_id)
        for field, value in _profile_values(profile).items():
            setattr(record, field, value)
        self._flush()
        return Vehicle.model_validate(record)

    def delete(self, vehicle_id: int) -> None:
        """Delete a vehicle; sessions, telemetry, alerts and maintenance cascade in the database."""
        result = self._session.execute(delete(VehicleRecord).where(VehicleRecord.id == vehicle_id))
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise RecordNotFoundError(f"Vehicle {vehicle_id} does not exist.")
        self._session.expire_all()

    def set_active(self, vehicle_id: int) -> Vehicle:
        record = self._require(vehicle_id)
        self._session.execute(
            update(VehicleRecord).where(VehicleRecord.id != vehicle_id).values(is_active=False)
        )
        record.is_active = True
        self._flush()
        return Vehicle.model_validate(record)

    def get_active(self) -> Vehicle | None:
        record = self._session.scalars(
            select(VehicleRecord).where(VehicleRecord.is_active.is_(True))
        ).first()
        return Vehicle.model_validate(record) if record else None

    def remove_identifiers(self, vehicle_id: int) -> Vehicle:
        """Erase personally identifying fields (VIN and registration number)."""
        record = self._require(vehicle_id)
        record.vin = None
        record.registration_number = None
        self._flush()
        return Vehicle.model_validate(record)

    def _require(self, vehicle_id: int) -> VehicleRecord:
        record = self._session.get(VehicleRecord, vehicle_id)
        if record is None:
            raise RecordNotFoundError(f"Vehicle {vehicle_id} does not exist.")
        return record

    def _flush(self) -> None:
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            if "vehicles.vin" in str(exc.orig) or "uq_vehicles_vin" in str(exc.orig):
                raise DataValidationError(
                    "Another vehicle already uses this VIN.",
                    user_message="Another vehicle in the garage already uses this VIN.",
                ) from exc
            raise DataValidationError(f"Vehicle data violates a constraint: {exc.orig}") from exc
