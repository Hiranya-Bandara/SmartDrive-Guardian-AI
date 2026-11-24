from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from smartdrive.database.connection import Database
from smartdrive.database.repositories import VehicleRepository
from smartdrive.models.vehicle import VehicleProfile
from smartdrive.utils.exceptions import BackupError

pytestmark = pytest.mark.integration


def _names(db: Database) -> list[str]:
    with db.session() as session:
        return [v.name for v in VehicleRepository(session).list_vehicles()]


def _add(db: Database, profile: VehicleProfile, name: str) -> None:
    with db.session() as session:
        VehicleRepository(session).add(profile.model_copy(update={"name": name, "vin": None}))


def test_backup_then_restore_recovers_previous_state(
    database: Database, vehicle_profile: VehicleProfile, tmp_path: Path
) -> None:
    _add(database, vehicle_profile, "Before backup")
    backup = database.backup(tmp_path / "backup.db")
    _add(database, vehicle_profile, "After backup")
    assert _names(database) == ["After backup", "Before backup"]

    safety = database.restore(backup, safety_backup_dir=tmp_path / "safety")

    assert _names(database) == ["Before backup"]
    assert safety.is_file()
    assert database.current_revision() == database.head_revision()


def test_safety_backup_allows_undoing_a_restore(
    database: Database, vehicle_profile: VehicleProfile, tmp_path: Path
) -> None:
    backup = database.backup(tmp_path / "empty.db")
    _add(database, vehicle_profile, "Keep me")
    safety = database.restore(backup, safety_backup_dir=tmp_path / "safety")
    assert _names(database) == []
    database.restore(safety, safety_backup_dir=tmp_path / "safety")
    assert _names(database) == ["Keep me"]


def test_backup_refuses_to_overwrite_or_target_live_file(
    database: Database, tmp_path: Path
) -> None:
    target = database.backup(tmp_path / "b.db")
    with pytest.raises(BackupError):
        database.backup(target)
    with pytest.raises(BackupError):
        database.backup(database.path, overwrite=True)


def test_rotating_backups_keep_only_requested_count(database: Database, tmp_path: Path) -> None:
    directory = tmp_path / "rotating"
    for _ in range(4):
        database.backup_to_directory(directory, keep=2)
    assert len(list(directory.glob("*.db"))) == 2


def test_restore_rejects_non_sqlite_file(database: Database, tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.db"
    bogus.write_bytes(b"not a database at all")
    with pytest.raises(BackupError, match="not a SQLite"):
        database.restore(bogus, safety_backup_dir=tmp_path / "safety")
    assert not (tmp_path / "safety").exists()


def test_restore_rejects_foreign_sqlite_database(database: Database, tmp_path: Path) -> None:
    foreign = tmp_path / "foreign.db"
    with closing(sqlite3.connect(foreign)) as conn:
        conn.execute("CREATE TABLE something (id INTEGER)")
        conn.commit()
    with pytest.raises(BackupError, match="not a SmartDrive database"):
        database.validate_backup(foreign)


def test_restore_rejects_backup_from_newer_version(database: Database, tmp_path: Path) -> None:
    newer = database.backup(tmp_path / "newer.db")
    with closing(sqlite3.connect(newer)) as conn:
        conn.execute("UPDATE alembic_version SET version_num = 'ffff_future'")
        conn.commit()
    with pytest.raises(BackupError, match="unknown to this application"):
        database.validate_backup(newer)
