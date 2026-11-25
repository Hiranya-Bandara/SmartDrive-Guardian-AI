"""SQLite engine lifecycle, transactions, Alembic migrations, backup and restore."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from smartdrive.utils.exceptions import BackupError, DatabaseError, MigrationError

logger = logging.getLogger(__name__)

MIGRATIONS_DIR: Final = Path(__file__).resolve().parent / "migrations"
SQLITE_HEADER: Final = b"SQLite format 3\x00"
BACKUP_PREFIX: Final = "smartdrive-backup-"


def _apply_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def _integrity_ok(path: Path) -> bool:
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    return row is not None and row[0] == "ok"


class Database:
    """Owns one SQLite file. All application code obtains sessions through :meth:`session`."""

    def __init__(self, path: Path, *, echo: bool = False) -> None:
        self._path = path.expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = self._create_engine(echo)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        self._echo = echo

    @property
    def path(self) -> Path:
        return self._path

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def url(self) -> str:
        return f"sqlite:///{self._path.as_posix()}"

    def _create_engine(self, echo: bool) -> Engine:
        engine = create_engine(f"sqlite:///{self._path.as_posix()}", echo=echo, future=True)
        event.listen(engine, "connect", _apply_sqlite_pragmas)
        return engine

    # -- transactions -------------------------------------------------------------------------

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Unit of work: commits on success, rolls back on any exception."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Database transaction failed")
            raise DatabaseError(f"Database transaction failed: {exc}") from exc
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    # -- migrations ---------------------------------------------------------------------------

    def _alembic_config(self) -> Config:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        config.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        return config

    def head_revision(self) -> str | None:
        return ScriptDirectory.from_config(self._alembic_config()).get_current_head()

    def current_revision(self) -> str | None:
        with self._engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def upgrade(self, revision: str = "head") -> None:
        self._migrate(command.upgrade, revision, "Migration")
        logger.info("Database schema is current", extra={"revision": self.current_revision()})

    def downgrade(self, revision: str) -> None:
        self._migrate(command.downgrade, revision, "Downgrade")

    def _migrate(self, action: Callable[[Config, str], None], revision: str, name: str) -> None:
        """Run Alembic with foreign-key enforcement off, as SQLite requires for table rebuilds.

        On SQLite, batch mode rebuilds a table by copying it, dropping the original and renaming
        the copy. With foreign keys on, dropping the original would delete every child row
        through ``ON DELETE CASCADE`` (for example all telemetry of every trip). Enforcement is
        switched off for the migration and back on afterwards, and ``PRAGMA foreign_key_check``
        must report no violations before the migration is committed.
        """
        config = self._alembic_config()
        try:
            with self._engine.connect() as connection:
                # Must run outside a transaction to take effect.
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
                try:
                    with connection.begin():
                        config.attributes["connection"] = connection
                        action(config, revision)
                        violations = connection.exec_driver_sql(
                            "PRAGMA foreign_key_check"
                        ).fetchall()
                        if violations:
                            raise MigrationError(
                                f"{name} to {revision} would leave {len(violations)} broken "
                                f"references (first: {violations[0]})"
                            )
                finally:
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                    connection.commit()
        except (CommandError, SQLAlchemyError) as exc:
            raise MigrationError(f"{name} to {revision} failed: {exc}") from exc

    # -- maintenance --------------------------------------------------------------------------

    def integrity_check(self) -> bool:
        return _integrity_ok(self._path)

    def backup(self, destination: Path, *, overwrite: bool = False) -> Path:
        """Write a consistent online copy using SQLite's backup API, then verify it."""
        destination = destination.expanduser().resolve()
        if destination == self._path:
            raise BackupError("Backup destination cannot be the live database.")
        if destination.exists() and not overwrite:
            raise BackupError(f"Backup file already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".partial")
        try:
            with (
                closing(sqlite3.connect(self._path)) as src,
                closing(sqlite3.connect(partial)) as dst,
            ):
                src.backup(dst)
            if not _integrity_ok(partial):
                raise BackupError("Backup copy failed its integrity check.")
            partial.replace(destination)
        except (sqlite3.Error, OSError) as exc:
            raise BackupError(f"Backup to {destination} failed: {exc}") from exc
        finally:
            partial.unlink(missing_ok=True)
        logger.info("Database backup written", extra={"backup_file": destination.name})
        return destination

    def backup_to_directory(self, directory: Path, *, keep: int) -> Path:
        """Create a timestamped backup and prune the oldest so at most ``keep`` remain."""
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        created = self.backup(directory / f"{BACKUP_PREFIX}{stamp}.db")
        existing = sorted(directory.glob(f"{BACKUP_PREFIX}*.db"))
        for stale in existing[: max(0, len(existing) - keep)]:
            stale.unlink(missing_ok=True)
        return created

    def validate_backup(self, source: Path) -> str:
        """Return the schema revision of a backup file, or raise if it cannot be restored."""
        source = source.expanduser().resolve()
        if not source.is_file():
            raise BackupError(f"Backup file not found: {source}")
        with source.open("rb") as handle:
            if handle.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                raise BackupError(
                    f"{source.name} is not a SQLite database.",
                    user_message="The selected file is not a SmartDrive backup.",
                )
        try:
            if not _integrity_ok(source):
                raise BackupError(f"{source.name} failed its integrity check.")
            with closing(sqlite3.connect(source)) as conn:
                row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.Error as exc:
            raise BackupError(
                f"{source.name} is not a SmartDrive database: {exc}",
                user_message="The selected file is not a SmartDrive backup.",
            ) from exc
        if row is None:
            raise BackupError(f"{source.name} has no schema revision.")
        revision = str(row[0])
        script = ScriptDirectory.from_config(self._alembic_config())
        try:
            script.get_revision(revision)
        except CommandError as exc:
            raise BackupError(
                f"Backup revision {revision} is unknown to this application version.",
                user_message="This backup was created by a newer version of SmartDrive.",
            ) from exc
        return revision

    def restore(self, source: Path, *, safety_backup_dir: Path, keep: int = 5) -> Path:
        """Replace the live database with ``source``.

        A safety backup of the current database is written first and its path is returned,
        so a mistaken restore can itself be undone. The restored schema is then migrated
        forward to the current head.
        """
        source = source.expanduser().resolve()
        self.validate_backup(source)
        safety_backup = self.backup_to_directory(safety_backup_dir, keep=keep)
        self._engine.dispose()
        try:
            with (
                closing(sqlite3.connect(source)) as src,
                closing(sqlite3.connect(self._path)) as dst,
            ):
                src.backup(dst)
        except sqlite3.Error as exc:
            raise BackupError(f"Restore from {source.name} failed: {exc}") from exc
        finally:
            self._engine = self._create_engine(self._echo)
            self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        self.upgrade()
        logger.info("Database restored", extra={"backup_file": source.name})
        return safety_backup

    def dispose(self) -> None:
        """Release pooled connections and fold the WAL into the main file."""
        try:
            with closing(sqlite3.connect(self._path)) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            logger.warning("WAL checkpoint on shutdown failed", exc_info=True)
        self._engine.dispose()
