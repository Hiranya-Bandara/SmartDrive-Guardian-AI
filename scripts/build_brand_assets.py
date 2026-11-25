"""Render every SmartDrive Guardian AI brand asset from the two hand-written SVG masters.

Masters (edit these, then re-run this script):

* ``src/smartdrive/branding/smartdrive-icon.svg`` - shield, car silhouette and diagnostic pulse;
  used at 48 px and above.
* ``src/smartdrive/branding/smartdrive-icon-small.svg`` - shield and pulse only, legible at
  16-32 px.

Outputs are reproducible: the wordmark is converted to vector outlines with Qt (DejaVu Sans,
Bitstream Vera licence) so the SVG logos need no font, and nothing is downloaded.

    QT_QPA_PLATFORM=offscreen python scripts/build_brand_assets.py
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "src" / "smartdrive" / "branding"
DOCS = ROOT / "docs" / "branding"
INSTALLER = ROOT / "packaging" / "installer"

NAME = "SmartDrive Guardian AI"
TAGLINE = "Intelligent Diagnostics. Smarter Maintenance."
NAVY = "#0B1120"
TEXT_LIGHT = "#F8FAFC"
TEXT_DARK = "#0F172A"
MUTED_ON_DARK = "#94A3B8"
MUTED_ON_LIGHT = "#475569"
CYAN = "#06B6D4"
FONT_FAMILY = "DejaVu Sans"

SMALL_SIZES = (16, 24, 32)
LARGE_SIZES = (48, 64, 128, 256)


def svg_bytes(name: str) -> bytes:
    return (BRANDING / name).read_bytes()


def render_svg(data: bytes, width: int, height: int | None = None, bg: str | None = None) -> QImage:
    height = height or width
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(bg) if bg else QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(data)).render(painter, QRectF(0, 0, width, height))
    painter.end()
    return image


def to_pil(image: QImage) -> Image.Image:
    buffer = QByteArray()
    from PySide6.QtCore import QBuffer, QIODevice

    device = QBuffer(buffer)
    device.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(device, "PNG")
    device.close()
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def write_png(image: QImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_pil(image).save(path, optimize=True)
    print(f"wrote {path.relative_to(ROOT)}")


def build_ico() -> None:
    frames: list[Image.Image] = []
    for size in SMALL_SIZES:
        frames.append(to_pil(render_svg(svg_bytes("smartdrive-icon-small.svg"), size)))
    for size in LARGE_SIZES:
        frames.append(to_pil(render_svg(svg_bytes("smartdrive-icon.svg"), size)))
    largest = frames[-1]
    target = BRANDING / "smartdrive-icon.ico"
    largest.save(
        target,
        format="ICO",
        sizes=[(f.width, f.height) for f in frames],
        append_images=frames[:-1],
    )
    with Image.open(target) as check:
        found = sorted(check.info.get("sizes", set()))
    expected = sorted((s, s) for s in SMALL_SIZES + LARGE_SIZES)
    if found != expected:
        raise SystemExit(f"ICO sizes {found} != {expected}")
    print(f"wrote {target.relative_to(ROOT)} {[s[0] for s in found]}")


def text_path(text: str, size: float, weight: QFont.Weight, x: float, y: float) -> QPainterPath:
    font = QFont(FONT_FAMILY)
    font.setPixelSize(round(size))
    font.setWeight(weight)
    path = QPainterPath()
    path.addText(QPointF(x, y), font, text)
    return path


def path_to_svg(path: QPainterPath) -> str:
    parts: list[str] = []
    i = 0
    count = path.elementCount()
    while i < count:
        element = path.elementAt(i)
        if element.type == QPainterPath.ElementType.MoveToElement:
            parts.append(f"M{element.x:.2f} {element.y:.2f}")
            i += 1
        elif element.type == QPainterPath.ElementType.LineToElement:
            parts.append(f"L{element.x:.2f} {element.y:.2f}")
            i += 1
        else:  # CurveToElement followed by two CurveToDataElements
            c2, end = path.elementAt(i + 1), path.elementAt(i + 2)
            parts.append(
                f"C{element.x:.2f} {element.y:.2f} {c2.x:.2f} {c2.y:.2f} {end.x:.2f} {end.y:.2f}"
            )
            i += 3
    return "".join(parts) + "Z"


def mark_inner(svg: bytes) -> tuple[str, str]:
    """Return the <defs> and drawing elements of an icon master, for embedding."""
    text = svg.decode("utf-8")
    defs = re.search(r"<defs>.*?</defs>", text, re.S)
    body = re.sub(r"<defs>.*?</defs>", "", text, flags=re.S)
    body = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", body, flags=re.S)
    return (defs.group(0) if defs else ""), body.strip()


def logo_svg(name_colour: str, tag_colour: str) -> str:
    """Horizontal logo: 256-unit mark plus outlined wordmark, 1260 x 256 units."""
    defs, body = mark_inner(svg_bytes("smartdrive-icon.svg"))
    title_path = text_path(NAME, 76, QFont.Weight.Bold, 290, 128)
    tag_path = text_path(TAGLINE, 38, QFont.Weight.Normal, 292, 186)
    width = logo_width(title_path, tag_path)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 256" '
        f'role="img" aria-label="{NAME}">'
        f"{defs}<g>{body}</g>"
        f'<path d="{path_to_svg(title_path)}" fill="{name_colour}"/>'
        f'<path d="{path_to_svg(tag_path)}" fill="{tag_colour}"/></svg>\n'
    )


def logo_width(*paths: QPainterPath) -> int:
    right = max(path.boundingRect().right() for path in paths)
    return int(right + 24)


def mono_mark_svg(colour: str) -> str:
    """Single-colour mark: shield outline, car and pulse, no fills of other colours."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" '
        f'aria-label="{NAME}">'
        f'<path d="M128 14 L220 46 V118 C220 178 181 222 128 244 C75 222 36 178 36 118 V46 Z '
        'M128 30 L50 57 V118 C50 169 83 207 128 227 C173 207 206 169 206 118 V57 Z" '
        f'fill="{colour}" fill-rule="evenodd"/>'
        '<path d="M64 136 V129 Q64 119 76 117 L98 114 L115 94 Q121 87 130 87 H152 Q161 87 167 95 '
        "L183 114 Q194 117 194 129 V136 Z M108 114 L168 114 L157 100 Q154 96 150 96 H129 "
        f'Q124 96 121 99 Z" fill="{colour}" fill-rule="evenodd"/>'
        f'<circle cx="96" cy="155" r="12" fill="none" stroke="{colour}" stroke-width="8"/>'
        f'<circle cx="162" cy="155" r="12" fill="none" stroke="{colour}" stroke-width="8"/>'
        '<path d="M66 190 H104 L114 174 L128 206 L142 180 L150 190 H190" fill="none" '
        f'stroke="{colour}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>\n"
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)}")


def build_logos() -> None:
    variants = {
        "smartdrive-logo-on-dark": logo_svg(TEXT_LIGHT, MUTED_ON_DARK),
        "smartdrive-logo-on-light": logo_svg(TEXT_DARK, MUTED_ON_LIGHT),
    }
    for stem, svg in variants.items():
        write_text(DOCS / f"{stem}.svg", svg)
        width = int(svg.split('viewBox="0 0 ', 1)[1].split(" ", 1)[0])
        write_png(render_svg(svg.encode(), width, 256), DOCS / f"{stem}.png")
    mono = mono_mark_svg(TEXT_DARK)
    write_text(DOCS / "smartdrive-mark-mono.svg", mono)
    write_png(render_svg(mono.encode(), 512), DOCS / "smartdrive-mark-mono.png")
    write_png(render_svg(svg_bytes("smartdrive-icon.svg"), 512), DOCS / "smartdrive-mark.png")
    icon_png = BRANDING / "smartdrive-icon-256.png"
    write_png(render_svg(svg_bytes("smartdrive-icon.svg"), 256), icon_png)


def build_banner() -> None:
    """1280 x 640 repository social preview / portfolio banner."""
    width, height = 1280, 640
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(NAVY))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(QRectF(0, height - 8, width, 8), QColor(CYAN))
    QSvgRenderer(QByteArray(svg_bytes("smartdrive-icon.svg"))).render(
        painter, QRectF(110, 170, 300, 300)
    )
    painter.setPen(Qt.PenStyle.NoPen)
    for text, size, weight, colour, y in (
        ("SmartDrive", 86, QFont.Weight.Bold, TEXT_LIGHT, 300),
        ("Guardian AI", 86, QFont.Weight.Bold, TEXT_LIGHT, 400),
        (TAGLINE, 30, QFont.Weight.Normal, MUTED_ON_DARK, 462),
        ("Version 2.0.0  ·  Offline desktop app for Windows", 24, QFont.Weight.Normal, CYAN, 516),
    ):
        painter.setBrush(QColor(colour))
        painter.drawPath(text_path(text, size, weight, 460, y))
    painter.end()
    write_png(image, DOCS / "social-preview.png")


def build_installer_images() -> None:
    """Inno Setup wizard bitmaps (24-bit BMP) at 100 % and 200 % scale."""
    for scale in (1, 2):
        large_w, large_h = 164 * scale, 314 * scale
        large = QImage(large_w, large_h, QImage.Format.Format_ARGB32_Premultiplied)
        large.fill(QColor(NAVY))
        painter = QPainter(large)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = 120 * scale
        QSvgRenderer(QByteArray(svg_bytes("smartdrive-icon.svg"))).render(
            painter, QRectF((large_w - size) / 2, 60 * scale, size, size)
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TEXT_LIGHT))
        for i, word in enumerate(("SmartDrive", "Guardian AI")):
            path = text_path(word, 19 * scale, QFont.Weight.Bold, 0, 0)
            offset = (large_w - path.boundingRect().width()) / 2
            painter.drawPath(path.translated(offset, (222 + i * 26) * scale))
        painter.end()
        small_size = 55 * scale, 58 * scale
        small = render_svg(
            svg_bytes("smartdrive-icon.svg"), small_size[0], small_size[1], "#FFFFFF"
        )
        suffix = "" if scale == 1 else f"-{scale * 100}"
        for image, stem in ((large, "wizard-image"), (small, "wizard-small")):
            target = INSTALLER / f"{stem}{suffix}.bmp"
            target.parent.mkdir(parents=True, exist_ok=True)
            to_pil(image).convert("RGB").save(target, format="BMP")
            print(f"wrote {target.relative_to(ROOT)}")


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    build_ico()
    build_logos()
    build_banner()
    build_installer_images()
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
