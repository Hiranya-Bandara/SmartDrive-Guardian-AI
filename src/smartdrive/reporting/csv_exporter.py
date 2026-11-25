"""Safe CSV export.

- UTF-8 with a byte-order mark so common spreadsheet programs detect the encoding.
- RFC 4180 quoting via :mod:`csv` (quotes, commas and line breaks are escaped).
- Missing values are written as empty cells, never as zero.
- Timestamps are ISO 8601 in UTC; units are part of the column names.
- Text cells that a spreadsheet could interpret as a formula (starting with ``=``, ``+``,
  ``-``, ``@``, tab or carriage return) are prefixed with an apostrophe (CSV injection
  protection). Numbers are written as numbers.
- Files are written to a temporary file and moved into place; an existing file is only
  replaced when ``overwrite`` is true.
"""

from __future__ import annotations

import csv
import math
import os
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Final

from smartdrive.utils.exceptions import ExportError

FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    description: str = ""


def sanitise_text(value: str) -> str:
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def format_cell(value: Any) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return "" if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return sanitise_text(str(value.value))
    return sanitise_text(str(value))


def write_csv(
    path: Path,
    columns: Sequence[Column],
    rows: Iterable[Sequence[Any]],
    *,
    overwrite: bool = False,
) -> int:
    """Write rows and return how many were written."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise ExportError(
            f"{path} already exists", user_message="A file with that name already exists."
        )
    if not path.parent.is_dir():
        raise ExportError(
            f"Folder {path.parent} does not exist",
            user_message="The selected folder does not exist.",
        )
    count = 0
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".smartdrive-", suffix=".csv.tmp")
    except PermissionError as exc:
        raise ExportError(
            f"Permission denied in {path.parent}: {exc}",
            user_message="SmartDrive does not have permission to write to that location.",
        ) from exc
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL)
            writer.writerow([c.name for c in columns])
            for row in rows:
                if len(row) != len(columns):
                    raise ValueError(f"Row has {len(row)} values for {len(columns)} columns")
                writer.writerow([format_cell(v) for v in row])
                count += 1
        tmp.replace(path)
    except PermissionError as exc:
        raise ExportError(
            f"Permission denied writing {path}: {exc}",
            user_message="SmartDrive does not have permission to write to that location.",
        ) from exc
    except OSError as exc:
        raise ExportError(
            f"Could not write {path}: {exc}", user_message="The CSV file could not be written."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return count
