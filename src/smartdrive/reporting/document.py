"""Format-independent report model. Templates build it; the PDF generator renders it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class Heading:
    text: str
    level: int = 1


@dataclass(frozen=True, slots=True)
class Text:
    text: str
    style: Literal["body", "muted", "small"] = "body"


@dataclass(frozen=True, slots=True)
class KeyValues:
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Table:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    widths: tuple[float, ...] | None = None
    """Relative column widths; they are scaled to the page width."""
    severity_column: int | None = None
    empty_text: str = "No records."


@dataclass(frozen=True, slots=True)
class Series:
    name: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class LineChart:
    title: str
    x_label: str
    y_label: str
    series: tuple[Series, ...]


@dataclass(frozen=True, slots=True)
class BarChart:
    title: str
    labels: tuple[str, ...]
    values: tuple[float, ...]
    value_label: str


@dataclass(frozen=True, slots=True)
class Notice:
    kind: Literal["limitation", "warning", "info"]
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class PageBreak:
    pass


Block = Heading | Text | KeyValues | Table | LineChart | BarChart | Notice | PageBreak


@dataclass(frozen=True, slots=True)
class ReportDocument:
    title: str
    report_id: str
    generated_at: datetime
    app_version: str
    data_source_label: str
    period_label: str
    vehicle_label: str
    blocks: tuple[Block, ...] = field(default_factory=tuple)

    def text_content(self) -> str:
        """Plain text of every block, used for previews and content checks."""
        parts = [self.title, self.vehicle_label, self.period_label, self.data_source_label]
        for block in self.blocks:
            if isinstance(block, Heading | Text):
                parts.append(block.text)
            elif isinstance(block, KeyValues):
                parts.extend(f"{k}: {v}" for k, v in block.rows)
            elif isinstance(block, Table):
                parts.append(" | ".join(block.columns))
                parts.extend(" | ".join(row) for row in block.rows)
            elif isinstance(block, Notice):
                parts.extend((block.title, block.text))
            elif isinstance(block, LineChart | BarChart):
                parts.append(block.title)
        return "\n".join(parts)
