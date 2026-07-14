from __future__ import annotations

import math
import time

from signalk.models import (
    MS_TO_KNOTS,
    STALE_VALUE_AGE_SEC,
    State,
    angle_diff,
    calc_age,
    derive_true_heading,
    is_calc_stale,
    is_stale,
    norm_angle,
    rad_to_deg,
    rad_to_deg_signed,
    signal_age,
    toggle_sail,
    update_from_delta,
)


def test_ms_to_knots_value():
    assert MS_TO_KNOTS == 1.94384


def test_norm_angle_none():
    assert norm_angle(None) is None


def test_norm_angle_zero():
    assert norm_angle(0.0) == 0.0


def test_norm_angle_positive_within_range():
    val = norm_angle(math.pi)
    assert abs(val - math.pi) < 1e-12


def test_norm_angle_positive_over_2pi():
    val = norm_angle(3 * math.pi)
    assert abs(val - math.pi) < 1e-12


def test_norm_angle_exactly_2pi():
    val = norm_angle(2 * math.pi)
    assert abs(val) < 1e-12


def test_norm_angle_negative():
    val = norm_angle(-0.5)
    expected = 2 * math.pi - 0.5
    assert abs(val - expected) < 1e-12


def test_norm_angle_large_negative():
    val = norm_angle(-3 * math.pi)
    assert abs(val - math.pi) < 1e-12


def test_rad_to_deg_none():
    assert rad_to_deg(None) is None


def test_rad_to_deg_zero():
    assert rad_to_deg(0.0) == 0.0


def test_rad_to_deg_pi_over_2():
    assert abs(rad_to_deg(math.pi / 2) - 90.0) < 1e-12


def test_rad_to_deg_pi():
    assert abs(rad_to_deg(math.pi) - 180.0) < 1e-12


def test_rad_to_deg_2pi():
    assert abs(rad_to_deg(2 * math.pi)) < 1e-12


def test_rad_to_deg_3pi_wraps():
    result = rad_to_deg(3 * math.pi)
    assert abs(result - 180.0) < 1e-12


def test_rad_to_deg_signed_none():
    assert rad_to_deg_signed(None) is None


def test_rad_to_deg_signed_zero():
    assert rad_to_deg_signed(0.0) == 0.0


def test_rad_to_deg_signed_positive():
    result = rad_to_deg_signed(math.pi / 2)
    assert abs(result - 90.0) < 1e-12


def test_rad_to_deg_signed_pi():
    assert abs(rad_to_deg_signed(math.pi) - 180.0) < 1e-12


def test_rad_to_deg_signed_negative():
    result = rad_to_deg_signed(-math.pi / 2)
    assert abs(result - (-90.0)) < 1e-12


def test_rad_to_deg_signed_beyond_pi():
    result = rad_to_deg_signed(3 * math.pi / 2)
    assert abs(result - 270.0) < 1e-12


def test_angle_diff_same_angle():
    assert abs(angle_diff(1.0, 1.0)) < 1e-12


def test_angle_diff_forward():
    result = angle_diff(2.0, 1.0)
    assert abs(result - 1.0) < 1e-12


def test_angle_diff_backward():
    result = angle_diff(1.0, 2.0)
    assert abs(result - (-1.0)) < 1e-12


def test_angle_diff_wraparound():
    a = 0.1
    b = 2 * math.pi - 0.1
    result = angle_diff(a, b)
    expected = 0.2
    assert abs(result - expected) < 1e-9


def test_angle_diff_antisymmetric():
    a, b = 1.0, 2.5
    assert abs(angle_diff(a, b) + angle_diff(b, a)) < 1e-12


def test_angle_diff_exactly_pi():
    result = angle_diff(math.pi, 0.0)
    assert abs(abs(result) - math.pi) < 1e-12


def _make_state(**kwargs: float | None) -> State:
    state = State()
    for key, val in kwargs.items():
        state.values[key] = val
    return state


def test_derive_true_heading_from_heading_true():
    state = _make_state(headingTrue=1.0)
    result = derive_true_heading(state)
    assert result is not None
    assert abs(result - norm_angle(1.0)) < 1e-12


def test_derive_true_heading_from_magnetic_with_variation():
    state = _make_state(headingMagnetic=1.0, magneticVariation=0.5)
    result = derive_true_heading(state)
    assert result is not None
    assert abs(result - norm_angle(1.5)) < 1e-12


def test_derive_true_heading_missing_both():
    state = _make_state()
    result = derive_true_heading(state)
    assert result is None


def test_derive_true_heading_heading_true_takes_precedence():
    state = _make_state(headingTrue=1.0, headingMagnetic=2.0, magneticVariation=0.5)
    result = derive_true_heading(state)
    assert result is not None
    assert abs(result - norm_angle(1.0)) < 1e-12


def test_derive_true_heading_with_offset():
    state = _make_state(headingTrue=1.0)
    state.heading_offset = 10.0
    result = derive_true_heading(state)
    assert result is not None
    expected = norm_angle(1.0 + math.radians(10.0))
    assert abs(result - expected) < 1e-12


def test_derive_true_heading_magnetic_missing_variation():
    state = _make_state(headingMagnetic=1.0)
    result = derive_true_heading(state)
    assert result is None


def test_derive_true_heading_variation_missing_heading():
    state = _make_state(magneticVariation=0.5)
    result = derive_true_heading(state)
    assert result is None


def _make_sail_state():
    state = State()
    state.sail_groups = [
        ("headsail", ["Jib", "Code0"]),
        ("downwind", ["Asym"]),
    ]
    state.sail_to_polar = {
        "Jib": "Jib",
        "Code0": "Code0",
        "Asym": "Asym",
    }
    state.available_sails = ["Jib", "Code0", "Asym"]
    state.active_sails = []
    state.polar_data = {
        "Jib": type("P", (), {"tws_list": [6, 10, 15, 20]}),
        "Code0": type("P", (), {"tws_list": [6, 10, 15, 20]}),
        "Asym": type("P", (), {"tws_list": [6, 10, 15, 20]}),
    }
    state.polar_names = ["Jib", "Code0", "Asym"]
    state.polar_active = "Jib"
    state.polar_tws_index = 0
    return state


def test_toggle_sail_adds_sail():
    state = _make_sail_state()
    toggle_sail(state, "Jib")
    assert "Jib" in state.active_sails


def test_toggle_sail_removes_sail():
    state = _make_sail_state()
    toggle_sail(state, "Jib")
    toggle_sail(state, "Jib")
    assert "Jib" not in state.active_sails


def test_toggle_sail_headsail_mutually_exclusive():
    state = _make_sail_state()
    toggle_sail(state, "Jib")
    toggle_sail(state, "Code0")
    assert "Jib" not in state.active_sails
    assert "Code0" in state.active_sails


def test_toggle_sail_different_groups_independent():
    state = _make_sail_state()
    toggle_sail(state, "Jib")
    toggle_sail(state, "Asym")
    assert "Jib" in state.active_sails
    assert "Asym" in state.active_sails


def test_toggle_sail_does_not_switch_polar():
    state = _make_sail_state()
    toggle_sail(state, "Code0")
    assert state.polar_active == "Jib"
    assert "Code0" in state.active_sails


def test_toggle_sail_remove_does_not_switch_polar():
    state = _make_sail_state()
    toggle_sail(state, "Jib")
    assert state.polar_active == "Jib"
    toggle_sail(state, "Jib")
    assert state.polar_active == "Jib"


def test_update_from_delta_updates_form_sets_last_update():
    state = State()
    msg = (
        '{"updates":[{"$source":"src1","timestamp":"2024-01-01T00:00:00Z",'
        '"values":[{"path":"navigation.headingMagnetic","value":1.2}]}]}'
    )
    before = time.time()
    update_from_delta(state, msg)
    after = time.time()
    assert "headingMagnetic" in state.values
    t = state.last_update.get("headingMagnetic")
    assert t is not None
    assert before <= t <= after


def test_update_from_delta_vessels_form_sets_last_update():
    state = State()
    msg = '{"vessels":{"self":{"navigation":{"headingMagnetic":{"value":0.9,"$source":"src2"}}}}}'
    before = time.time()
    update_from_delta(state, msg)
    after = time.time()
    assert state.values.get("headingMagnetic") == 0.9
    t = state.last_update.get("headingMagnetic")
    assert t is not None
    assert before <= t <= after


def test_update_from_delta_skips_null_value_no_last_update():
    state = State()
    msg = (
        '{"updates":[{"$source":"src1","timestamp":"2024-01-01T00:00:00Z",'
        '"values":[{"path":"navigation.headingMagnetic","value":null}]}]}'
    )
    update_from_delta(state, msg)
    assert "headingMagnetic" not in state.last_update


def test_update_from_delta_updates_form_keeps_first_source():
    """Regression: a second source sending the same signal must not overwrite
    state.sources[key] — otherwise the row jumps between device sections on
    the Diagnostics page every time a different source sends a delta."""
    state = State()
    msg1 = (
        '{"updates":[{"$source":"src1","timestamp":"2024-01-01T00:00:00Z",'
        '"values":[{"path":"navigation.magneticVariation","value":0.1}]}]}'
    )
    update_from_delta(state, msg1)
    assert state.sources["magneticVariation"] == "src1"
    msg2 = (
        '{"updates":[{"$source":"src2","timestamp":"2024-01-01T00:01:00Z",'
        '"values":[{"path":"navigation.magneticVariation","value":0.2}]}]}'
    )
    update_from_delta(state, msg2)
    assert state.sources["magneticVariation"] == "src1"
    assert state.values["magneticVariation"] == 0.2


def test_update_from_delta_vessels_form_keeps_first_source():
    state = State()
    msg1 = (
        '{"vessels":{"self":{"navigation":{"magneticVariation":{"value":0.1,"$source":"src1"}}}}}'
    )
    update_from_delta(state, msg1)
    assert state.sources["magneticVariation"] == "src1"
    msg2 = (
        '{"vessels":{"self":{"navigation":{"magneticVariation":{"value":0.2,"$source":"src2"}}}}}'
    )
    update_from_delta(state, msg2)
    assert state.sources["magneticVariation"] == "src1"
    assert state.values["magneticVariation"] == 0.2


def test_signal_age_none_when_never_received():
    state = State()
    assert signal_age(state, "headingMagnetic") is None


def test_signal_age_returns_seconds_since_update():
    state = State()
    now = 1000.0
    state.last_update["headingMagnetic"] = 990.0
    age = signal_age(state, "headingMagnetic", now=now)
    assert age == 10.0


def test_signal_age_uses_time_time_by_default():
    state = State()
    before = time.time()
    state.last_update["headingMagnetic"] = before
    age = signal_age(state, "headingMagnetic")
    assert age is not None
    assert 0.0 <= age < 1.0


def test_is_stale_false_when_never_received():
    state = State()
    assert is_stale(state, "headingMagnetic") is False


def test_is_stale_false_when_fresh():
    state = State()
    state.last_update["headingMagnetic"] = time.time() - 5.0
    assert is_stale(state, "headingMagnetic") is False


def test_is_stale_true_past_threshold():
    state = State()
    state.last_update["headingMagnetic"] = time.time() - (STALE_VALUE_AGE_SEC + 5.0)
    assert is_stale(state, "headingMagnetic") is True


def test_is_stale_custom_threshold():
    state = State()
    state.last_update["headingMagnetic"] = time.time() - 15.0
    assert is_stale(state, "headingMagnetic", threshold=10.0) is True
    assert is_stale(state, "headingMagnetic", threshold=20.0) is False


def test_calc_age_none_when_no_inputs_received():
    state = State()
    age, latest = calc_age(state, ["headingMagnetic", "cogTrue"])
    assert age is None
    assert latest is None


def test_calc_age_returns_freshest_input():
    state = State()
    now = 1000.0
    state.last_update["headingMagnetic"] = 980.0
    state.last_update["cogTrue"] = 995.0
    age, latest = calc_age(state, ["headingMagnetic", "cogTrue"], now=now)
    assert age == 5.0
    assert latest == 995.0


def test_is_calc_stale_true_when_all_inputs_stale():
    state = State()
    state.last_update["headingMagnetic"] = time.time() - (STALE_VALUE_AGE_SEC + 10.0)
    state.last_update["cogTrue"] = time.time() - (STALE_VALUE_AGE_SEC + 5.0)
    assert is_calc_stale(state, ["headingMagnetic", "cogTrue"]) is True


def test_is_calc_stale_false_when_any_input_fresh():
    state = State()
    state.last_update["headingMagnetic"] = time.time() - (STALE_VALUE_AGE_SEC + 10.0)
    state.last_update["cogTrue"] = time.time() - 5.0
    assert is_calc_stale(state, ["headingMagnetic", "cogTrue"]) is False


def test_is_calc_stale_true_when_no_inputs_received():
    state = State()
    assert is_calc_stale(state, ["headingMagnetic", "cogTrue"]) is True
