"""Renders a :class:`ReportDocument` to PDF with ReportLab.

Design: A4, 18 mm margins, Helvetica, a slim branded header and a footer with report id and
"Page x of y" on every page. Backgrounds stay white; tables use a dark header row and light
banding, and severities are written out (with a marker shape) so the report remains readable in
grayscale. Long tables split across pages and repeat their header row. Document metadata holds
only the title, the application name and version — no file paths or user names.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)
from reportlab.platypus import PageBreak as RLPageBreak
from reportlab.platypus import Table as RLTable

from smartdrive.reporting.document import (
    BarChart,
    Block,
    Heading,
    KeyValues,
    LineChart,
    Notice,
    PageBreak,
    ReportDocument,
    Table,
    Text,
)
from smartdrive.utils.exceptions import ExportError

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN: Final = 18 * mm
CONTENT_WIDTH: Final = PAGE_WIDTH - 2 * MARGIN
INK: Final = colors.HexColor("#0F172A")
MUTED: Final = colors.HexColor("#475569")
RULE: Final = colors.HexColor("#CBD5E1")
HEADER_FILL: Final = colors.HexColor("#1E293B")
BAND: Final = colors.HexColor("#F1F5F9")
ACCENT: Final = colors.HexColor("#0891B2")
SERIES_COLOURS: Final = (
    colors.HexColor("#0E7490"),
    colors.HexColor("#B45309"),
    colors.HexColor("#334155"),
)
SEVERITY_MARKS: Final = {
    "CRITICAL": "[!!] CRITICAL",
    "WARNING": "[!] WARNING",
    "INFORMATION": "[i] INFORMATION",
    "NORMAL": "[ok] NORMAL",
}
_REPLACEMENTS: Final = {
    "→": "->",
    "←": "<-",
    "≥": ">=",
    "≤": "<=",
    "≈": "~",
    "✓": "yes",
    "✗": "no",
    "■": "#",
    "▲": "^",
    "●": "*",
    "○": "o",
    "·": "-",
}


def pdf_safe(text: str) -> str:
    """Map characters outside the standard PDF fonts' WinAnsi set to readable equivalents."""
    out = []
    for char in text:
        char = _REPLACEMENTS.get(char, char)
        try:
            char.encode("cp1252")
        except UnicodeEncodeError:
            char = "?"
        out.append(char)
    return "".join(out)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(pdf_safe(text)).replace("\n", "<br/>"), style)


_BASE: Final = ParagraphStyle(
    "base", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK, alignment=TA_LEFT
)
STYLES: Final = {
    "title": ParagraphStyle(
        "title", parent=_BASE, fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=2
    ),
    "h1": ParagraphStyle(
        "h1",
        parent=_BASE,
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        spaceBefore=10,
        spaceAfter=4,
    ),
    "h2": ParagraphStyle(
        "h2",
        parent=_BASE,
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        spaceBefore=8,
        spaceAfter=3,
    ),
    "body": _BASE,
    "muted": ParagraphStyle("muted", parent=_BASE, textColor=MUTED),
    "small": ParagraphStyle("small", parent=_BASE, fontSize=8, leading=10.5, textColor=MUTED),
    "cell": ParagraphStyle("cell", parent=_BASE, fontSize=8.5, leading=11),
    "head": ParagraphStyle(
        "head",
        parent=_BASE,
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    ),
    "key": ParagraphStyle("key", parent=_BASE, fontName="Helvetica-Bold", textColor=MUTED),
    "notice_title": ParagraphStyle("notice_title", parent=_BASE, fontName="Helvetica-Bold"),
}


class _NumberedCanvas(Canvas):  # type: ignore[misc]
    """Two-pass canvas so every page can show "Page x of y"."""

    def __init__(self, *args: Any, document: ReportDocument, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._document = document
        self._saved: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 - ReportLab API
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total: int) -> None:
        doc = self._document
        top = PAGE_HEIGHT - 12 * mm
        self.setStrokeColor(ACCENT)
        self.setFillColor(ACCENT)
        shield = self.beginPath()
        x, y = MARGIN, top - 1.5 * mm
        shield.moveTo(x + 2.2 * mm, y + 4.6 * mm)
        shield.lineTo(x + 4.4 * mm, y + 3.8 * mm)
        shield.lineTo(x + 4.4 * mm, y + 1.6 * mm)
        shield.curveTo(x + 4.4 * mm, y, x + 2.2 * mm, y - 0.8 * mm, x + 2.2 * mm, y - 0.8 * mm)
        shield.curveTo(x + 2.2 * mm, y - 0.8 * mm, x, y, x, y + 1.6 * mm)
        shield.lineTo(x, y + 3.8 * mm)
        shield.close()
        self.drawPath(shield, stroke=0, fill=1)
        self.setFillColor(INK)
        self.setFont("Helvetica-Bold", 9)
        self.drawString(MARGIN + 7 * mm, top, "SmartDrive Guardian AI")
        self.setFont("Helvetica", 8)
        self.setFillColor(MUTED)
        self.drawRightString(PAGE_WIDTH - MARGIN, top, pdf_safe(doc.title))
        self.setStrokeColor(RULE)
        self.setLineWidth(0.6)
        self.line(MARGIN, top - 3 * mm, PAGE_WIDTH - MARGIN, top - 3 * mm)
        bottom = 10 * mm
        self.line(MARGIN, bottom + 4 * mm, PAGE_WIDTH - MARGIN, bottom + 4 * mm)
        self.drawString(
            MARGIN,
            bottom,
            pdf_safe(
                f"Report {doc.report_id} · version {doc.app_version} · not a certified "
                "vehicle safety system"
            ),
        )
        self.drawRightString(PAGE_WIDTH - MARGIN, bottom, f"Page {self._pageNumber} of {total}")


def _table(block: Table) -> list[Any]:
    if not block.rows:
        return [_p(block.empty_text, STYLES["muted"])]
    widths = block.widths or tuple(1.0 for _ in block.columns)
    scale = CONTENT_WIDTH / sum(widths)
    header = [_p(c, STYLES["head"]) for c in block.columns]
    rows: list[list[Any]] = [header]
    for row in block.rows:
        cells = []
        for index, value in enumerate(row):
            text = value
            if index == block.severity_column:
                text = SEVERITY_MARKS.get(value.upper(), value)
            cells.append(_p(text, STYLES["cell"]))
        rows.append(cells)
    table = RLTable(rows, colWidths=[w * scale for w in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for index in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, index), (-1, index), BAND))
    table.setStyle(TableStyle(style))
    return [table, Spacer(1, 4)]


def _key_values(block: KeyValues) -> list[Any]:
    rows = [[_p(k, STYLES["key"]), _p(v, STYLES["body"])] for k, v in block.rows]
    table = RLTable(rows, colWidths=[CONTENT_WIDTH * 0.32, CONTENT_WIDTH * 0.68])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [table, Spacer(1, 4)]


def _notice(block: Notice) -> list[Any]:
    label = {"limitation": "Limitation", "warning": "Important", "info": "Note"}[block.kind]
    inner = [
        _p(f"{label}: {block.title}", STYLES["notice_title"]),
        _p(block.text, STYLES["body"]),
    ]
    table = RLTable([[inner]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, MUTED if block.kind != "warning" else INK),
                ("LINEBEFORE", (0, 0), (0, -1), 3, MUTED if block.kind != "warning" else INK),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [KeepTogether([table]), Spacer(1, 6)]


def _line_chart(block: LineChart) -> list[Any]:
    series = [s for s in block.series if len(s.points) >= 2]
    if not series:
        return [_p(f"{block.title}: not enough data to plot.", STYLES["muted"])]
    height = 62 * mm
    drawing = Drawing(CONTENT_WIDTH, height)
    plot = LinePlot()
    plot.x, plot.y = 14 * mm, 12 * mm
    plot.width, plot.height = CONTENT_WIDTH - 20 * mm, height - 24 * mm
    plot.data = [list(s.points) for s in series]
    for index in range(len(series)):
        line = plot.lines[index]
        line.strokeColor = SERIES_COLOURS[index % len(SERIES_COLOURS)]
        line.strokeWidth = 1.2
        if index == 1:
            line.strokeDashArray = (4, 2)
        elif index == 2:
            line.strokeDashArray = (1, 2)
    plot.xValueAxis.labels.fontName = plot.yValueAxis.labels.fontName = "Helvetica"
    plot.xValueAxis.labels.fontSize = plot.yValueAxis.labels.fontSize = 7
    plot.yValueAxis.gridStrokeColor = RULE
    plot.yValueAxis.visibleGrid = True
    drawing.add(plot)
    drawing.add(String(0, height - 6, pdf_safe(block.title), fontName="Helvetica-Bold", fontSize=9))
    drawing.add(
        String(
            plot.x + plot.width / 2,
            1,
            pdf_safe(block.x_label),
            fontName="Helvetica",
            fontSize=7,
            fillColor=MUTED,
            textAnchor="middle",
        )
    )
    label = String(0, 0, pdf_safe(block.y_label), fontName="Helvetica", fontSize=7, fillColor=MUTED)
    label.x, label.y = 2, plot.y + plot.height + 3
    drawing.add(label)
    if len(series) > 1:
        legend = Legend()
        legend.x, legend.y = CONTENT_WIDTH - 60 * mm, height - 4
        legend.fontName, legend.fontSize = "Helvetica", 7
        legend.columnMaximum = 1
        legend.alignment = "right"
        legend.colorNamePairs = [
            (SERIES_COLOURS[i % len(SERIES_COLOURS)], pdf_safe(s.name))
            for i, s in enumerate(series)
        ]
        legend.dxTextSpace = 3
        legend.deltax = 50 * mm
        drawing.add(legend)
    return [KeepTogether([drawing]), Spacer(1, 6)]


def _bar_chart(block: BarChart) -> list[Any]:
    if not block.values:
        return [_p(f"{block.title}: no data.", STYLES["muted"])]
    rows = len(block.values)
    height = max(30 * mm, rows * 6 * mm + 18 * mm)
    drawing = Drawing(CONTENT_WIDTH, height)
    chart = HorizontalBarChart()
    chart.x, chart.y = 62 * mm, 10 * mm
    chart.width, chart.height = CONTENT_WIDTH - 70 * mm, height - 22 * mm
    chart.data = [list(reversed(block.values))]
    chart.categoryAxis.categoryNames = [pdf_safe(x) for x in reversed(block.labels)]
    chart.categoryAxis.labels.fontName = chart.valueAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = chart.valueAxis.labels.fontSize = 7
    chart.categoryAxis.labels.boxAnchor = "e"
    chart.bars[0].fillColor = SERIES_COLOURS[2]
    chart.valueAxis.valueMin = 0
    drawing.add(chart)
    drawing.add(String(0, height - 6, pdf_safe(block.title), fontName="Helvetica-Bold", fontSize=9))
    drawing.add(
        String(
            chart.x + chart.width / 2,
            0,
            pdf_safe(block.value_label),
            fontName="Helvetica",
            fontSize=7,
            fillColor=MUTED,
            textAnchor="middle",
        )
    )
    return [KeepTogether([drawing]), Spacer(1, 6)]


def _flowables(blocks: Sequence[Block]) -> list[Any]:
    story: list[Any] = []
    for block in blocks:
        if isinstance(block, Heading):
            story.append(_p(block.text, STYLES["h1" if block.level <= 1 else "h2"]))
        elif isinstance(block, Text):
            story.append(_p(block.text, STYLES[block.style]))
            story.append(Spacer(1, 3))
        elif isinstance(block, KeyValues):
            story.extend(_key_values(block))
        elif isinstance(block, Table):
            story.extend(_table(block))
        elif isinstance(block, LineChart):
            story.extend(_line_chart(block))
        elif isinstance(block, BarChart):
            story.extend(_bar_chart(block))
        elif isinstance(block, Notice):
            story.extend(_notice(block))
        elif isinstance(block, PageBreak):
            story.append(RLPageBreak())
    return story


def render_pdf(document: ReportDocument, path: Path, *, compress: bool = True) -> Path:
    """Write the PDF atomically. Raises :class:`ExportError` with a user-facing message."""
    path = Path(path)
    if not path.parent.is_dir():
        raise ExportError(
            f"Folder {path.parent} does not exist",
            user_message="The selected folder does not exist.",
        )
    story: list[Any] = [
        _p(document.title, STYLES["title"]),
        _p(
            f"{document.vehicle_label}\nPeriod: {document.period_label}\n"
            f"Data: {document.data_source_label}\n"
            f"Generated {document.generated_at:%Y-%m-%d %H:%M} UTC · report {document.report_id}",
            STYLES["muted"],
        ),
        Spacer(1, 8),
        *_flowables(document.blocks),
    ]
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".smartdrive-", suffix=".pdf.tmp")
    except PermissionError as exc:
        raise ExportError(
            f"Permission denied in {path.parent}: {exc}",
            user_message="SmartDrive does not have permission to write to that location.",
        ) from exc
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        template = SimpleDocTemplate(
            str(tmp),
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN + 6 * mm,
            bottomMargin=MARGIN,
            title=pdf_safe(document.title),
            author="SmartDrive Guardian AI",
            subject=pdf_safe(document.title),
            creator=f"SmartDrive Guardian AI {document.app_version}",
            keywords="",
            pageCompression=1 if compress else 0,
        )
        template.build(
            story,
            canvasmaker=lambda *a, **k: _NumberedCanvas(*a, document=document, **k),
        )
        tmp.replace(path)
    except PermissionError as exc:
        raise ExportError(
            f"Permission denied writing {path}: {exc}",
            user_message="SmartDrive does not have permission to write to that location.",
        ) from exc
    except OSError as exc:
        raise ExportError(
            f"Could not write {path}: {exc}", user_message="The report file could not be written."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return path
