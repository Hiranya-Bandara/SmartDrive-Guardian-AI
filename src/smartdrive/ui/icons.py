"""Original line icons in a 24×24 stroke style, tinted to the active palette at runtime."""

from __future__ import annotations

from functools import lru_cache
from typing import Final

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SVG_TEMPLATE: Final = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    "{body}</svg>"
)

ICONS: Final[dict[str, str]] = {
    "dashboard": '<path d="M4 15a8 8 0 1 1 16 0"/><path d="M12 15l4-5"/><circle cx="12" cy="15" r="1.5"/>'
    '<path d="M4 19h16"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "car": '<path d="M5 16l1.5-5.5A2 2 0 0 1 8.4 9h7.2a2 2 0 0 1 1.9 1.5L19 16"/>'
    '<rect x="3" y="16" width="18" height="4" rx="1.5"/><circle cx="7" cy="20" r="1"/>'
    '<circle cx="17" cy="20" r="1"/><path d="M8 13h8"/>',
    "flask": '<path d="M9 3h6"/><path d="M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/>'
    '<path d="M7 15h10"/>',
    "settings": '<path d="M4 6h10"/><path d="M18 6h2"/><circle cx="16" cy="6" r="2"/>'
    '<path d="M4 12h2"/><path d="M10 12h10"/><circle cx="8" cy="12" r="2"/>'
    '<path d="M4 18h12"/><path d="M20 18h0"/><circle cx="18" cy="18" r="2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/>'
    '<path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "wrench": '<path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5"/>'
    '<path d="M14.5 6.5l3-3a4 4 0 0 1 3 3l-3 3"/>',
    "plug": '<path d="M9 2v5M15 2v5"/><path d="M6 7h12v4a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
    "route": '<circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/>'
    '<path d="M8.5 18H16a3 3 0 0 0 0-6H8a3 3 0 0 1 0-6h7.5"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
    '<path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
    "chevrons-left": '<path d="M11 17l-5-5 5-5"/><path d="M18 17l-5-5 5-5"/>',
    "chevrons-right": '<path d="M13 17l5-5-5-5"/><path d="M6 17l5-5-5-5"/>',
    "play": '<path d="M7 4l13 8-13 8z"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "alert": '<path d="M12 3l10 18H2z"/><path d="M12 10v5"/><path d="M12 18h.01"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/>'
    '<path d="M21 16l-5-5-9 9"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 3v5h5"/>'
    '<path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 21v-5h-5"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
    '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "record": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
    "shuffle": '<path d="M3 7h3l9 10h6"/><path d="M3 17h3l3-3.5"/><path d="M14 9.5L15 7h6"/>'
    '<path d="M18 4l3 3-3 3"/><path d="M18 14l3 3-3 3"/>',
}


def svg_markup(name: str, colour: str) -> str:
    return _SVG_TEMPLATE.format(colour=colour, body=ICONS[name])


@lru_cache(maxsize=512)
def pixmap(name: str, colour: str, size: int = 20, device_pixel_ratio: float = 2.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_markup(name, colour).encode("utf-8")))
    physical = max(1, round(size * device_pixel_ratio))
    image = QPixmap(physical, physical)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, physical, physical))
    painter.end()
    image.setDevicePixelRatio(device_pixel_ratio)
    return image


def icon(name: str, colour: str, *, disabled_colour: str | None = None, size: int = 20) -> QIcon:
    result = QIcon(pixmap(name, colour, size))
    if disabled_colour:
        result.addPixmap(pixmap(name, disabled_colour, size), QIcon.Mode.Disabled)
    return result


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """The application icon: the simplified mark up to 32 px, the full mark above."""
    from smartdrive.resources import APP_ICON_SMALL_SVG, APP_ICON_SVG, resource_path

    result = QIcon()
    small, full = resource_path(*APP_ICON_SMALL_SVG), resource_path(*APP_ICON_SVG)
    for size in (16, 24, 32):
        result.addFile(str(small), QSize(size, size))
    for size in (48, 64, 128, 256):
        result.addFile(str(full), QSize(size, size))
    return result


def brand_pixmap(size: int, device_pixel_ratio: float = 1.0) -> QPixmap:
    """The full brand mark rendered crisply for a logical size."""
    from smartdrive.resources import APP_ICON_SMALL_SVG, APP_ICON_SVG, resource_path

    parts = APP_ICON_SMALL_SVG if size <= 24 else APP_ICON_SVG
    physical = max(1, round(size * device_pixel_ratio))
    image = QPixmap(physical, physical)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(resource_path(*parts))).render(painter, QRectF(0, 0, physical, physical))
    painter.end()
    image.setDevicePixelRatio(device_pixel_ratio)
    return image
