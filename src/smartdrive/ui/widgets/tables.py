"""Read-only data tables used by the record pages (trips, codes, maintenance, alerts, reports)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from smartdrive.config.constants import Severity

MISSING = "—"

SEVERITY_TEXT = {
    Severity.CRITICAL: "‼ Critical",
    Severity.WARNING: "! Warning",
    Severity.INFORMATION: "i Information",
    Severity.NORMAL: "Normal",
    Severity.UNKNOWN: "Not assessed",
}
"""Severity labels carry a symbol so they do not rely on colour alone."""


def make_table(columns: Sequence[str], name: str, *, stretch: int = 0) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setAccessibleName(name)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return table


def fill_table(table: QTableWidget, rows: Sequence[Sequence[str]], data: Sequence[Any]) -> None:
    """Replace the rows. ``data[i]`` is attached to row ``i`` and returned by :func:`row_data`."""
    selected = row_data(table)
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    restore = -1
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            if c == 0:
                item.setData(Qt.ItemDataRole.UserRole, data[r])
            table.setItem(r, c, item)
        if selected is not None and data[r] == selected:
            restore = r
    if restore >= 0:
        table.selectRow(restore)


def row_data(table: QTableWidget, row: int | None = None) -> Any:
    if row is None:
        rows = table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
    item = table.item(row, 0)
    return None if item is None else item.data(Qt.ItemDataRole.UserRole)


def select_data(table: QTableWidget, value: Any) -> bool:
    for row in range(table.rowCount()):
        if row_data(table, row) == value:
            table.selectRow(row)
            return True
    return False


def local_time(moment: datetime | None, *, seconds: bool = False) -> str:
    if moment is None:
        return MISSING
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")


def day(value: date | None) -> str:
    return MISSING if value is None else value.isoformat()


def number(value: float | None, digits: int = 1, unit: str = "") -> str:
    if value is None:
        return MISSING
    text = f"{value:,.{digits}f}"
    return f"{text} {unit}".strip()
