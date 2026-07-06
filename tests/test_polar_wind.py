from __future__ import annotations

import math
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from boatpolars.parser import PolarData
from pages.polar import draw_polar_rose, format_awa, signed_wind_deg
from pages.rose import angle_to_screen
from signalk.models import MS_TO_KNOTS, State
from theme import WIND_APPARENT

pygame.init()
pygame.display.set_mode((1400, 900))
_FONT = pygame.font.SysFont("monospace", 20, bold=True)
_FONT_SM = pygame.font.SysFont("monospace", 14)

RECT = (300, 40, 1000, 700)


def _make_polar() -> PolarData:
    twa_list = [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0]
    tws_list = [6.0, 10.0]
    grid: dict[float, dict[float, float]] = {
        0.0: {6.0: 0.0, 10.0: 0.0},
        30.0: {6.0: 3.5, 10.0: 4.5},
        60.0: {6.0: 5.0, 10.0: 6.5},
        90.0: {6.0: 5.5, 10.0: 7.0},
        120.0: {6.0: 5.0, 10.0: 6.5},
        150.0: {6.0: 3.5, 10.0: 4.5},
        180.0: {6.0: 2.0, 10.0: 2.5},
    }
    return PolarData("test", twa_list, tws_list, grid)


def _make_state(with_wind: bool) -> State:
    st = State()
    p = _make_polar()
    st.polar_data[p.name] = p
    st.polar_names.append(p.name)
    st.polar_active = p.name
    st.polar_tws_index = 0
    if with_wind:
        st.values["windAngleApparent"] = math.radians(170.0)
        st.values["windSpeedApparent"] = 12.0 / MS_TO_KNOTS
        st.values["speedThroughWater"] = 5.0 / MS_TO_KNOTS
    return st


def _awa_shaft_midpoint() -> tuple[int, int]:
    """Screen pixel at the middle of where the AWA rim arrow is drawn."""
    x, y, w, h = RECT
    chart_w = int(w * 0.60)
    cx = x + chart_w // 2
    cy = y + h // 2
    r = min(chart_w, h) // 2 - 20
    px, py = angle_to_screen(cx, cy, r - 1, 170.0)
    return int(px), int(py)


class TestFormatting:
    def test_signed_wind_deg_wraps(self):
        assert signed_wind_deg(math.radians(350.0)) == -10.0
        assert signed_wind_deg(math.radians(-190.0)) == 170.0
        assert signed_wind_deg(math.radians(90.0)) == 90.0

    def test_format_awa_sides(self):
        assert format_awa(34.2) == "34°S"
        assert format_awa(-120.0) == "120°P"
        assert format_awa(0.0) == "0°"


class TestWindPointers:
    def test_apparent_arrow_drawn_on_rim(self):
        st = _make_state(with_wind=True)
        surf = pygame.Surface((1400, 900))
        draw_polar_rose(surf, _FONT, _FONT_SM, st, RECT)
        assert surf.get_at(_awa_shaft_midpoint())[:3] == WIND_APPARENT

    def test_no_wind_draws_without_pointer(self):
        st = _make_state(with_wind=False)
        surf = pygame.Surface((1400, 900))
        draw_polar_rose(surf, _FONT, _FONT_SM, st, RECT)  # must not raise
        assert surf.get_at(_awa_shaft_midpoint())[:3] != WIND_APPARENT

    def test_true_tick_drawn_at_computed_twa(self):
        from boatpolars.parser import compute_true_wind
        from pages.polar import signed_wind_deg
        from theme import WIND_TRUE

        st = _make_state(with_wind=True)
        twa_rad, _ = compute_true_wind(
            st.values["windAngleApparent"],
            st.values["windSpeedApparent"],
            st.values["speedThroughWater"],
        )
        tdeg = signed_wind_deg(twa_rad)

        surf = pygame.Surface((1400, 900))
        draw_polar_rose(surf, _FONT, _FONT_SM, st, RECT)

        x, y, w, h = RECT
        chart_w = int(w * 0.60)
        cx = x + chart_w // 2
        cy = y + h // 2
        r = min(chart_w, h) // 2 - 20
        px, py = angle_to_screen(cx, cy, r + 3, tdeg)  # tick spans r-6..r+6
        assert surf.get_at((int(px), int(py)))[:3] == WIND_TRUE
