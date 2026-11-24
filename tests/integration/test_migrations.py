from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from smartdrive.database.connection import Database
from smartdrive.database.models import Base

pytestmark = pytest.mark.integration


def test_migrated_schema_matches_orm_models(database: Database) -> None:
    with database.engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_full_downgrade_and_upgrade_cycle(database: Database) -> None:
    database.downgrade("base")
    assert set(inspect(database.engine).get_table_names()) <= {"alembic_version"}
    assert database.current_revision() is None
    database.upgrade()
    assert database.current_revision() == database.head_revision()


def test_upgrade_is_idempotent(database: Database) -> None:
    database.upgrade()
    database.upgrade()
    assert database.current_revision() == database.head_revision()


def test_fresh_database_file_is_created_in_missing_folder(tmp_path: Path) -> None:
    db = Database(tmp_path / "nested" / "folder" / "new.db")
    db.upgrade()
    assert db.path.is_file()
    db.dispose()
