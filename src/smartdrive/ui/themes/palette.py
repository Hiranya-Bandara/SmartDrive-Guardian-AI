"""Colour palettes. The dark palette follows the project specification exactly; the light palette
uses darker accents and status colours so text meets WCAG AA contrast on light surfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class ThemePalette:
    name: str
    is_dark: bool
    background: str
    background_secondary: str
    surface: str
    surface_hover: str
    accent: str
    accent_secondary: str
    on_accent: str
    text: str
    text_secondary: str
    border: str
    normal: str
    warning: str
    critical: str
    offline: str
    simulation: str

    def tokens(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if isinstance(v, str)}


DARK: Final = ThemePalette(
    name="dark",
    is_dark=True,
    background="#0B1120",
    background_secondary="#151E2D",
    surface="#1E293B",
    surface_hover="#273449",
    accent="#06B6D4",
    accent_secondary="#3B82F6",
    on_accent="#0B1120",
    text="#F8FAFC",
    text_secondary="#94A3B8",
    border="#334155",
    normal="#22C55E",
    warning="#F59E0B",
    critical="#EF4444",
    offline="#64748B",
    simulation="#A78BFA",
)

LIGHT: Final = ThemePalette(
    name="light",
    is_dark=False,
    background="#F1F5F9",
    background_secondary="#FFFFFF",
    surface="#FFFFFF",
    surface_hover="#E2E8F0",
    accent="#0E7490",
    accent_secondary="#1D4ED8",
    on_accent="#FFFFFF",
    text="#0F172A",
    text_secondary="#475569",
    border="#CBD5E1",
    normal="#15803D",
    warning="#B45309",
    critical="#B91C1C",
    offline="#64748B",
    simulation="#6D28D9",
)


def relative_luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)
