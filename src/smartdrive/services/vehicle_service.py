"""Vehicle garage operations for the presentation layer, including optional vehicle images."""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Final

from smartdrive.config.constants import FuelType
from smartdrive.database.connection import Database
from smartdrive.database.repositories import VehicleRepository
from smartdrive.models.vehicle import Vehicle, VehicleProfile
from smartdrive.utils.exceptions import DataValidationError

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES: Final = 8 * 1024 * 1024
_IMAGE_SIGNATURES: Final[dict[str, tuple[bytes, ...]]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".bmp": (b"BM",),
}
IMAGE_SUFFIXES: Final = frozenset(_IMAGE_SIGNATURES)


class VehicleService:
    def __init__(self, database: Database, images_dir: Path) -> None:
        self._db = database
        self._images_dir = images_dir

    def list_vehicles(
        self, *, search: str | None = None, fuel_type: FuelType | None = None
    ) -> list[Vehicle]:
        with self._db.session() as session:
            return VehicleRepository(session).list_vehicles(search=search, fuel_type=fuel_type)

    def get(self, vehicle_id: int) -> Vehicle:
        with self._db.session() as session:
            return VehicleRepository(session).get(vehicle_id)

    def get_active(self) -> Vehicle | None:
        with self._db.session() as session:
            return VehicleRepository(session).get_active()

    def add(self, profile: VehicleProfile) -> Vehicle:
        with self._db.session() as session:
            vehicle = VehicleRepository(session).add(profile)
        logger.info("Vehicle added", extra={"vehicle_id": vehicle.id})
        return vehicle

    def update(self, vehicle_id: int, profile: VehicleProfile) -> Vehicle:
        previous = self.get(vehicle_id)
        with self._db.session() as session:
            vehicle = VehicleRepository(session).update(vehicle_id, profile)
        if previous.image_path and previous.image_path != vehicle.image_path:
            self._discard_image(previous.image_path)
        logger.info("Vehicle updated", extra={"vehicle_id": vehicle_id})
        return vehicle

    def delete(self, vehicle_id: int) -> None:
        vehicle = self.get(vehicle_id)
        with self._db.session() as session:
            VehicleRepository(session).delete(vehicle_id)
        if vehicle.image_path:
            self._discard_image(vehicle.image_path)
        logger.info("Vehicle deleted", extra={"vehicle_id": vehicle_id})

    def set_active(self, vehicle_id: int) -> Vehicle:
        with self._db.session() as session:
            return VehicleRepository(session).set_active(vehicle_id)

    def remove_identifiers(self, vehicle_id: int) -> Vehicle:
        with self._db.session() as session:
            return VehicleRepository(session).remove_identifiers(vehicle_id)

    # -- images -------------------------------------------------------------------------------

    def import_image(self, source: Path) -> str:
        """Validate and copy an image into the application data folder.

        Returns the stored file name, which is what ``VehicleProfile.image_path`` holds.
        """
        source = source.expanduser().resolve()
        suffix = source.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise DataValidationError(
                f"Unsupported image type: {suffix or 'none'}",
                user_message="Choose a PNG, JPEG or BMP image.",
            )
        if not source.is_file():
            raise DataValidationError(f"Image not found: {source}")
        size = source.stat().st_size
        if size == 0 or size > MAX_IMAGE_BYTES:
            raise DataValidationError(
                f"Image size {size} bytes is outside the allowed range.",
                user_message="Images must be smaller than 8 MB.",
            )
        with source.open("rb") as handle:
            header = handle.read(8)
        if not any(header.startswith(sig) for sig in _IMAGE_SIGNATURES[suffix]):
            raise DataValidationError(
                "File content does not match its image extension.",
                user_message="The selected file is not a valid image.",
            )
        self._images_dir.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{'.jpg' if suffix == '.jpeg' else suffix}"
        shutil.copyfile(source, self._images_dir / name)
        return name

    def image_file(self, vehicle: Vehicle) -> Path | None:
        return self.resolve_image(vehicle.image_path)

    def resolve_image(self, name: str | None) -> Path | None:
        """Path of a stored image. Only bare file names inside the images folder resolve."""
        if not name:
            return None
        candidate = (self._images_dir / Path(name).name).resolve()
        return candidate if candidate.is_file() else None

    def discard_unused_image(self, name: str) -> None:
        """Remove an imported image that was never saved to a vehicle (dialog cancelled)."""
        self._discard_image(name)

    def _discard_image(self, name: str) -> None:
        target = self._images_dir / Path(name).name
        try:
            target.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete vehicle image", exc_info=True)
