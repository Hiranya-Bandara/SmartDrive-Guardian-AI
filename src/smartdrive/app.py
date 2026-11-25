"""Application bootstrap and shutdown, shared by the CLI and (from Phase 2) the desktop shell."""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from smartdrive import APP_NAME, __version__
from smartdrive.config.paths import AppPaths
from smartdrive.config.settings import AppSettings, SettingsStore
from smartdrive.database.connection import Database
from smartdrive.database.repositories import TelemetryRepository
from smartdrive.utils.logger import configure_logging, shutdown_logging

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationContext:
    paths: AppPaths
    settings_store: SettingsStore
    settings: AppSettings
    database: Database

    def save_settings(self) -> None:
        self.settings_store.save(self.settings)


def bootstrap(
    *, home: Path | None = None, console_logging: bool = True, apply_retention: bool = True
) -> ApplicationContext:
    """Prepare directories, settings, logging and an up-to-date database."""
    paths = AppPaths.resolve(home).ensure()
    store = SettingsStore(paths.settings_file)
    settings = store.load()
    if not store.path.exists():
        store.save(settings)
    configure_logging(
        paths.log_file,
        level=settings.logging.level,
        redact=settings.privacy.redact_identifiers_in_logs,
        console=console_logging,
    )
    logger.info(
        "Starting application",
        extra={
            "app_version": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(terse=True),
        },
    )
    database = Database(paths.database_file)
    backup_before_upgrade(database, paths.backup_dir)
    database.upgrade()
    context = ApplicationContext(
        paths=paths, settings_store=store, settings=settings, database=database
    )
    if apply_retention:
        enforce_retention(context)
    return context


def backup_before_upgrade(database: Database, backup_dir: Path) -> Path | None:
    """Copy an existing database before its schema is upgraded, so an upgrade can be undone."""
    current = database.current_revision()
    if current is None or current == database.head_revision():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"smartdrive-pre-upgrade-{current}-{stamp}.db"
    path = database.backup(target)
    logger.info("Backed up the database before upgrading it", extra={"revision": current})
    return path


def enforce_retention(context: ApplicationContext) -> int:
    days = context.settings.retention.telemetry_retention_days
    if days is None:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with context.database.session() as session:
        removed = TelemetryRepository(session).purge_sessions_before(cutoff)
    if removed:
        logger.info("Retention policy removed old sessions", extra={"sessions_removed": removed})
    return removed


def shutdown(context: ApplicationContext) -> None:
    logger.info("Shutting down %s", APP_NAME)
    context.database.dispose()
    shutdown_logging()
