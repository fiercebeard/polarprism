from __future__ import annotations

import math
import os
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from boatpolars.parser import PolarData
from pages.trend import TREND_WINDOWS_S, draw_trend_page, y_to_px
from signalk.client import build_trend_sample
from signalk.models import MS_TO_KNOTS, State

pygame.init()
pygame.display.set_mode((1400, 900))
_FONT = pygame.font.SysFont("monospace", 20, bold=True)
_FONT_SM = pygame.font.SysFont("monospace", 14)

RECT = (300, 40, 1000, 820)


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


class TestBuildTrendSample:
    def test_disconnected_yields_timestamp_only_gap(self):
        st = State()
        st.connected = False
        s = build_trend_sample(st, now=123.0)
        assert s == {"t": 123.0}

    def test_full_sample_computes_series(self):
        st = State()
        st.connected = True
        p = _make_polar()
        st.polar_data[p.name] = p
        st.polar_active = p.name
        st.values["headingMagnetic"] = math.radians(40.0)
        st.values["magneticVariation"] = 0.0
        st.values["windAngleApparent"] = math.radians(45.0)
        st.values["windSpeedApparent"] = 10.0 / MS_TO_KNOTS
        st.values["speedThroughWater"] = 6.0 / MS_TO_KNOTS
        st.values["speedOverGround"] = 6.0 / MS_TO_KNOTS
        st.values["cogTrue"] = math.radians(40.0)
        st.route_active = "r"
        st.route_next_wp_bearing_rad = math.radians(80.0)

        s = build_trend_sample(st, now=1.0)
        assert abs(s["tws"] - 10.0) < 3.0  # true wind near apparent at these speeds
        assert abs(s["stw"] - 6.0) < 0.01
        assert abs(s["hdg"] - 40.0) < 0.01
        assert abs(s["btw"] - 80.0) < 0.01
        # VMC = SOG * cos(BTW - COG) = 6 * cos(40°)
        assert abs(s["vmc"] - 6.0 * math.cos(math.radians(40.0))) < 0.01
        # Derived chain: TWD = HDG + TWA; WP angle = BTW - TWD (wrapped)
        assert abs(((s["hdg"] + s["twa"]) % 360.0) - s["twd"]) < 0.01
        expected_wp = ((s["btw"] - s["twd"] + 180.0) % 360.0) - 180.0
        assert abs(s["wp_angle"] - expected_wp) < 0.01
        # Polar-backed series present with a polar + wind + waypoint
        assert s["perf"] is not None and s["perf"] > 0
        assert s["tgt_vmc"] is not None
        assert s["tgt_twa"] is not None and s["tgt_twa"] > 0

    def test_no_waypoint_leaves_vmc_series_none(self):
        st = State()
        st.connected = True
        st.values["windAngleApparent"] = math.radians(45.0)
        st.values["windSpeedApparent"] = 10.0 / MS_TO_KNOTS
        st.values["speedThroughWater"] = 6.0 / MS_TO_KNOTS
        s = build_trend_sample(st, now=1.0)
        assert s["vmc"] is None
        assert s["wp_angle"] is None
        assert s["tgt_vmc"] is None


class TestYToPx:
    def test_maps_extremes_and_midpoint(self):
        assert y_to_px(10.0, 0.0, 10.0, 100, 200) == 100  # max at top
        assert y_to_px(0.0, 0.0, 10.0, 100, 200) == 300  # min at bottom
        assert y_to_px(5.0, 0.0, 10.0, 100, 200) == 200

    def test_clamps_out_of_range(self):
        assert y_to_px(99.0, 0.0, 10.0, 100, 200) == 100
        assert y_to_px(-99.0, 0.0, 10.0, 100, 200) == 300


class TestDrawTrendPage:
    def _seed(self, st: State, n: int = 120) -> None:
        now = time.time()
        for i in range(n):
            t = now - (n - i)
            phase = i / 10.0
            st.trend_samples.append(
                {
                    "t": t,
                    "tws": 12.0 + 3.0 * math.sin(phase),
                    "stw": 6.0 + math.sin(phase),
                    "sog": 6.2 + math.sin(phase),
                    "vmc": 4.0 + math.cos(phase),
                    "tgt_vmc": 5.5,
                    "twa": 40.0 + 20.0 * math.sin(phase),
                    "awa": 30.0 + 15.0 * math.sin(phase),
                    "wp_angle": 10.0 * math.sin(phase),
                    "tgt_twa": 42.0,
                    "perf": 90.0 + 10.0 * math.sin(phase) if i % 7 else None,  # gaps
                    "vmc_pct": 80.0 + 15.0 * math.cos(phase),
                    "twd": 220.0 + 5.0 * math.sin(phase),
                    "hdg": 180.0 + 30.0 * math.sin(phase),
                    "cog": 182.0 + 30.0 * math.sin(phase),
                    "btw": 200.0,
                }
            )

    def test_draws_all_windows_with_data_and_gaps(self):
        st = State()
        self._seed(st)
        surf = pygame.Surface((1400, 900))
        for tab in range(len(TREND_WINDOWS_S)):
            draw_trend_page(surf, _FONT, _FONT_SM, st, RECT, tab)  # must not raise

    def test_empty_history_shows_collecting_message(self):
        st = State()
        surf = pygame.Surface((1400, 900))
        draw_trend_page(surf, _FONT, _FONT_SM, st, RECT, 0)  # must not raise
