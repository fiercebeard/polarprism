from __future__ import annotations

import math
import time
from unittest.mock import patch

from boatpolars.parser import PolarData, auto_select_tws_index
from pages.polar import (
    REC_REFRESH_SECONDS,
    _cached_polar_recommendation,
    _compute_polar_recommendation,
)
from signalk.models import State


def _make_polar() -> PolarData:
    twa_list = [0, 30, 60, 90, 120, 150, 180]
    tws_list = [6, 10, 14, 20]
    speed_grid: dict[float, dict[float, float]] = {
        0: {6: 0.0, 10: 0.0, 14: 0.0, 20: 0.0},
        30: {6: 3.5, 10: 4.5, 14: 5.5, 20: 6.5},
        60: {6: 5.0, 10: 6.5, 14: 7.5, 20: 8.5},
        90: {6: 5.5, 10: 7.0, 14: 8.0, 20: 9.0},
        120: {6: 5.0, 10: 6.5, 14: 7.5, 20: 8.5},
        150: {6: 3.5, 10: 4.5, 14: 5.5, 20: 6.5},
        180: {6: 2.0, 10: 2.5, 14: 3.0, 20: 3.5},
    }
    return PolarData("test", twa_list, tws_list, speed_grid)


def _make_state(
    *,
    awa_rad: float | None = math.radians(60),
    aws_ms: float | None = 7.72,  # ~15 kts apparent
    stw_ms: float | None = 2.57,  # ~5 kts boat speed
    heading_true: float | None = 0.0,
    wp_bearing_rad: float | None = math.radians(60),
) -> State:
    state = State()
    state.polar_data["test"] = _make_polar()
    state.polar_names = ["test"]
    state.polar_active = "test"
    state.values["windAngleApparent"] = awa_rad
    state.values["windSpeedApparent"] = aws_ms
    state.values["speedThroughWater"] = stw_ms
    if heading_true is not None:
        state.values["headingTrue"] = heading_true
    if wp_bearing_rad is not None:
        state.values["calcBearingTrue"] = wp_bearing_rad
    return state


# --- auto_select_tws_index (shared helper) ---


class TestAutoSelectTwsIndex:
    def test_picks_closest_band(self) -> None:
        polar = _make_polar()
        assert auto_select_tws_index(polar, 7.0) == 0
        assert auto_select_tws_index(polar, 11.0) == 1
        assert auto_select_tws_index(polar, 15.0) == 2
        assert auto_select_tws_index(polar, 1000.0) == 3

    def test_none_when_no_wind(self) -> None:
        polar = _make_polar()
        assert auto_select_tws_index(polar, None) is None

    def test_none_when_empty_polar(self) -> None:
        polar = PolarData("empty", [], [], {})
        assert auto_select_tws_index(polar, 10.0) is None


# --- _compute_polar_recommendation ---


class TestComputePolarRecommendation:
    def test_none_without_wind(self) -> None:
        state = _make_state(awa_rad=None, aws_ms=None)
        rec = _compute_polar_recommendation(state, _make_polar())
        assert rec is None

    def test_action_rec_when_tacks_differ(self) -> None:
        # Default state: TWA ~79° stbd, WP to port of TWD -> best tack port
        # -> TACK or GYBE with the WP_ACTION color.
        from theme import WP_ACTION

        state = _make_state()
        rec = _compute_polar_recommendation(state, _make_polar())
        assert rec is not None
        assert rec["line1"].startswith(("TACK", "GYBE"))
        assert rec["color"] == WP_ACTION
        assert "VMC" in rec["line2"]

    def test_adjust_rec_when_heading_off(self) -> None:
        # WP bearing placed stbd of TWD so best tack matches current (stbd);
        # heading is well off hdg_to_sail -> HEAD UP or BEAR AWAY.
        from theme import WP_ADJUST

        state = _make_state(wp_bearing_rad=math.radians(139))
        rec = _compute_polar_recommendation(state, _make_polar())
        assert rec is not None
        assert rec["line1"].startswith(("HEAD UP", "BEAR AWAY"))
        assert rec["color"] == WP_ADJUST
        assert "VMC" in rec["line2"]

    def test_no_wp_falls_back_to_vmg(self) -> None:
        # Without waypoint bearing, vmc_data is None but vmg is available.
        state = _make_state(wp_bearing_rad=None)
        rec = _compute_polar_recommendation(state, _make_polar())
        assert rec is not None
        # Either an upwind/downwind angle hint or "Sail on".
        assert isinstance(rec["line1"], str)


# --- _cached_polar_recommendation (throttle) ---


class TestCachedPolarRecommendation:
    def test_first_call_computes_immediately(self) -> None:
        state = _make_state()
        polar = _make_polar()
        assert not state._polar_rec_computed
        rec = _cached_polar_recommendation(state, polar)
        assert rec is not None
        assert state._polar_rec_computed is True
        assert state._polar_rec_ts > 0.0

    def test_holds_result_within_refresh_window(self) -> None:
        state = _make_state()
        polar = _make_polar()
        first = _cached_polar_recommendation(state, polar)
        assert first is not None
        held_line1 = first["line1"]

        # Simulate wind shift that would change the recommendation, but the
        # cache should hold the previous result because the throttle window
        # has not elapsed.
        state.values["windAngleApparent"] = math.radians(-60)
        state.values["calcBearingTrue"] = math.radians(60)

        # Force monotonic to advance only a tiny amount.
        base = time.monotonic()
        with patch("pages.polar.time.monotonic", side_effect=lambda: base + 0.5):
            second = _cached_polar_recommendation(state, polar)
        assert second is not None
        assert second["line1"] == held_line1

    def test_recomputes_after_window_elapses(self) -> None:
        state = _make_state()
        polar = _make_polar()
        first = _cached_polar_recommendation(state, polar)
        assert first is not None
        first_line = first["line1"]

        # Change wind so a recomputation would produce a different line.
        state.values["windAngleApparent"] = math.radians(-60)
        state.values["calcBearingTrue"] = math.radians(60)

        base = time.monotonic()
        with patch(
            "pages.polar.time.monotonic", side_effect=lambda: base + REC_REFRESH_SECONDS + 0.1
        ):
            second = _cached_polar_recommendation(state, polar)
        assert second is not None
        assert second["line1"] != first_line

    def test_returns_none_when_no_wind_and_caches_it(self) -> None:
        state = _make_state(awa_rad=None, aws_ms=None)
        polar = _make_polar()
        assert _cached_polar_recommendation(state, polar) is None
        assert state._polar_rec_computed is True
