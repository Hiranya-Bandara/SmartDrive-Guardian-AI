"""Resolution of writable per-user directories.

Runtime data never lives next to the code or inside an installation directory. By default the
operating-system conventions from ``platformdirs`` are used (``%LOCALAPPDATA%`` on Windows).
Setting the ``SMARTDRIVE_HOME`` environment variable relocates everything under one folder,
which is used for the portable distribution and for isolated tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

from smartdrive.config.constants import (
    APP_AUTHOR,
    APP_ID,
    DATABASE_FILENAME,
    HOME_ENV_VAR,
    LOG_FILENAME,
    SETTINGS_FILENAME,
)
from smartdrive.utils.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class AppPaths:
    data_dir: Path
    config_dir: Path
    log_dir: Path
    backup_dir: Path
    export_dir: Path

    @property
    def database_file(self) -> Path:
        return self.data_dir / DATABASE_FILENAME

    @property
    def settings_file(self) -> Path:
        return self.config_dir / SETTINGS_FILENAME

    @property
    def log_file(self) -> Path:
        return self.log_dir / LOG_FILENAME

    @classmethod
    def under(cls, root: Path) -> AppPaths:
        root = root.expanduser().resolve()
        return cls(
            data_dir=root / "data",
            config_dir=root / "config",
            log_dir=root / "logs",
            backup_dir=root / "backups",
            export_dir=root / "exports",
        )

    @classmethod
    def resolve(cls, override: Path | None = None) -> AppPaths:
        """Pick the directory set: explicit override, then environment variable, then OS default."""
        if override is not None:
            return cls.under(override)
        env_home = os.environ.get(HOME_ENV_VAR, "").strip()
        if env_home:
            return cls.under(Path(env_home))
        dirs = PlatformDirs(appname=APP_ID, appauthor=APP_AUTHOR, roaming=False)
        data_dir = Path(dirs.user_data_dir)
        return cls(
            data_dir=data_dir,
            config_dir=Path(dirs.user_config_dir),
            log_dir=Path(dirs.user_log_dir),
            backup_dir=data_dir / "backups",
            export_dir=Path(dirs.user_documents_dir) / APP_ID,
        )

    def ensure(self) -> AppPaths:
        """Create the directories that the application writes to at startup."""
        for directory in (self.data_dir, self.config_dir, self.log_dir, self.backup_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ConfigurationError(
                    f"Cannot create application directory {directory}: {exc}",
                    user_message="The application data folder could not be created.",
                ) from exc
        return self
