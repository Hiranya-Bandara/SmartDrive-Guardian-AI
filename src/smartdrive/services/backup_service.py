"""Database backup and restore for the presentation layer."""

from __future__ import annotations

from pathlib import Path

from smartdrive.config.paths import AppPaths
from smartdrive.config.settings import AppSettings
from smartdrive.database.connection import Database


class BackupService:
    def __init__(self, database: Database, paths: AppPaths, settings: AppSettings) -> None:
        self._db = database
        self._paths = paths
        self._settings = settings

    @property
    def default_directory(self) -> Path:
        return self._paths.backup_dir

    def backup(self, destination: Path | None = None) -> Path:
        if destination is None:
            return self._db.backup_to_directory(
                self._paths.backup_dir, keep=self._settings.retention.keep_backups
            )
        return self._db.backup(destination, overwrite=True)

    def restore(self, source: Path) -> Path:
        """Restore ``source``; returns the safety backup of the replaced database."""
        return self._db.restore(
            source,
            safety_backup_dir=self._paths.backup_dir,
            keep=self._settings.retention.keep_backups,
        )
