"""Save-location selection for exports, and opening finished files with the system viewer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QWidget

from smartdrive.config.settings import AppSettings

PDF_FILTER = "PDF documents (*.pdf)"
CSV_FILTER = "CSV files (*.csv)"


def default_directory(settings: AppSettings) -> Path:
    configured = settings.reports.output_directory
    if configured and Path(configured).is_dir():
        return Path(configured)
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(documents) if documents else Path.home()


def choose_save_path(
    parent: QWidget | None, title: str, directory: Path, file_name: str, file_filter: str
) -> Path | None:
    """Ask where to save. The dialog itself asks before replacing an existing file."""
    chosen, _ = QFileDialog.getSaveFileName(parent, title, str(directory / file_name), file_filter)
    if not chosen:
        return None
    path = Path(chosen)
    suffix = ".pdf" if file_filter == PDF_FILTER else ".csv"
    return path if path.suffix.lower() == suffix else path.with_suffix(suffix)


def choose_directory(parent: QWidget | None, title: str, directory: Path) -> Path | None:
    chosen = QFileDialog.getExistingDirectory(parent, title, str(directory))
    return Path(chosen) if chosen else None


def open_path(path: Path) -> bool:
    """Open a file or folder with the operating system. Returns False if that failed."""
    if not path.exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
