from __future__ import annotations

import pytest

from smartdrive.ui.themes.palette import DARK, LIGHT, ThemePalette, contrast_ratio

WCAG_AA_TEXT = 4.5
WCAG_AA_LARGE_OR_UI = 3.0


def test_dark_palette_matches_specification() -> None:
    assert (DARK.background, DARK.background_secondary, DARK.surface) == (
        "#0B1120",
        "#151E2D",
        "#1E293B",
    )
    assert (DARK.accent, DARK.accent_secondary, DARK.text, DARK.text_secondary) == (
        "#06B6D4",
        "#3B82F6",
        "#F8FAFC",
        "#94A3B8",
    )
    assert (DARK.border, DARK.normal, DARK.warning, DARK.critical, DARK.offline) == (
        "#334155",
        "#22C55E",
        "#F59E0B",
        "#EF4444",
        "#64748B",
    )


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_text_meets_wcag_aa_on_every_surface(palette: ThemePalette) -> None:
    for background in (palette.background, palette.background_secondary, palette.surface):
        assert contrast_ratio(palette.text, background) >= WCAG_AA_TEXT
        assert contrast_ratio(palette.text_secondary, background) >= WCAG_AA_TEXT


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_status_and_accent_colours_are_distinguishable(palette: ThemePalette) -> None:
    for colour in (palette.accent, palette.normal, palette.warning, palette.critical):
        assert contrast_ratio(colour, palette.surface) >= WCAG_AA_LARGE_OR_UI
    assert contrast_ratio(palette.on_accent, palette.accent) >= WCAG_AA_TEXT


def test_contrast_ratio_reference_values() -> None:
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)
