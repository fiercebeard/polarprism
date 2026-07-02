from __future__ import annotations

import math

import pytest

from boatpolars.parser import (
    PolarData,
    calc_vmc,
    calc_vmg,
    compute_true_wind,
    lookup_speed,
)


def make_test_polar() -> PolarData:
    twa_list = [0, 30, 60, 90, 120, 150, 180]
    tws_list = [6, 10, 14, 20]
    speed_grid: dict[float, dict[float, float]] = {
        0: {6: 0.0, 10: 0.0},
        30: {6: 3.5, 10: 4.5},
        60: {6: 5.0, 10: 6.5},
        90: {6: 5.5, 10: 7.0},
        120: {6: 5.0, 10: 6.5},
        150: {6: 3.5, 10: 4.5},
        180: {6: 2.0, 10: 2.5},
    }
    return PolarData("test", twa_list, tws_list, speed_grid)


# --- PolarData class ---


class TestPolarData:
    def test_creation(self) -> None:
        polar = make_test_polar()
        assert polar.name == "test"
        assert polar.twa_list == [0, 30, 60, 90, 120, 150, 180]
        assert polar.tws_list == [6, 10, 14, 20]

    def test_attribute_access(self) -> None:
        polar = make_test_polar()
        assert polar.speed_grid[30][6] == 3.5
        assert polar.speed_grid[90][10] == 7.0
        assert polar.speed_grid[0][6] == 0.0

    def test_slots(self) -> None:
        polar = make_test_polar()
        with pytest.raises(AttributeError):
            polar.nonexistent = 42  # type: ignore[attr-defined]


# --- lookup_speed ---


class TestLookupSpeed:
    def test_exact_match(self) -> None:
        polar = make_test_polar()
        assert lookup_speed(polar, 30, 6) == 3.5
        assert lookup_speed(polar, 90, 10) == 7.0
        assert lookup_speed(polar, 180, 6) == 2.0

    def test_negative_twa(self) -> None:
        polar = make_test_polar()
        assert lookup_speed(polar, -30, 6) == 3.5
        assert lookup_speed(polar, -90, 10) == 7.0

    def test_interpolated_twa(self) -> None:
        polar = make_test_polar()
        speed_45 = lookup_speed(polar, 45, 6)
        assert speed_45 is not None
        expected = 3.5 + (5.0 - 3.5) * 0.5
        assert abs(speed_45 - expected) < 0.01

    def test_interpolated_tws(self) -> None:
        polar = make_test_polar()
        speed = lookup_speed(polar, 30, 8)
        assert speed is not None
        expected = 3.5 + (4.5 - 3.5) * 0.5
        assert abs(speed - expected) < 0.01

    def test_interpolated_both(self) -> None:
        polar = make_test_polar()
        speed = lookup_speed(polar, 45, 8)
        assert speed is not None
        s_30_6 = 3.5
        s_30_10 = 4.5
        s_60_6 = 5.0
        s_60_10 = 6.5
        s_30_8 = s_30_6 + (s_30_10 - s_30_6) * 0.5
        s_60_8 = s_60_6 + (s_60_10 - s_60_6) * 0.5
        expected = s_30_8 + (s_60_8 - s_30_8) * 0.5
        assert abs(speed - expected) < 0.01

    def test_tws_below_range(self) -> None:
        polar = make_test_polar()
        assert lookup_speed(polar, 60, 0) == 5.0

    def test_tws_above_range(self) -> None:
        polar = make_test_polar()
        speed = lookup_speed(polar, 60, 100)
        assert speed is not None
        assert speed == 0.0

    def test_twa_below_range(self) -> None:
        polar = make_test_polar()
        speed = lookup_speed(polar, -5, 6)
        assert speed is not None
        assert speed >= 0.0

    def test_twa_above_range(self) -> None:
        polar = make_test_polar()
        assert lookup_speed(polar, 200, 6) == 2.0

    def test_none_polar(self) -> None:
        assert lookup_speed(None, 60, 10) is None  # type: ignore[arg-type]

    def test_empty_lists(self) -> None:
        polar = PolarData("empty", [], [], {})
        assert lookup_speed(polar, 60, 10) is None

    def test_zero_twa(self) -> None:
        polar = make_test_polar()
        assert lookup_speed(polar, 0, 6) == 0.0


# --- compute_true_wind ---


class TestComputeTrueWind:
    def test_none_awa(self) -> None:
        twa, tws = compute_true_wind(None, 10.0, 5.0)
        assert twa is None
        assert tws is None

    def test_none_aws(self) -> None:
        twa, tws = compute_true_wind(0.5, None, 5.0)
        assert twa is None
        assert tws is None

    def test_none_stw_uses_zero(self) -> None:
        twa, tws = compute_true_wind(0.0, 10.0, None)
        assert twa is not None
        assert tws is not None
        assert abs(twa) < 0.01
        assert abs(tws - 10.0) < 0.01

    def test_zero_stw(self) -> None:
        twa, tws = compute_true_wind(0.0, 10.0, 0.0)
        assert twa is not None
        assert tws is not None
        assert abs(tws - 10.0) < 0.01

    def test_close_hauled(self) -> None:
        awa = math.radians(30)
        aws = 10.0
        stw = 5.0
        twa, tws = compute_true_wind(awa, aws, stw)
        assert twa is not None
        assert tws is not None
        assert twa > 0
        assert tws > 0

    def test_running_awa_zero(self) -> None:
        awa = math.radians(0)
        aws = 10.0
        stw = 5.0
        twa, tws = compute_true_wind(awa, aws, stw)
        assert twa is not None
        assert tws is not None
        assert abs(twa) < 0.01
        expected_tws = abs(aws - stw)
        assert abs(tws - expected_tws) < 0.01

    def test_running_awa_180(self) -> None:
        awa = math.radians(180)
        aws = 10.0
        stw = 5.0
        twa, tws = compute_true_wind(awa, aws, stw)
        assert twa is not None
        assert tws is not None
        assert abs(abs(twa) - math.pi) < 0.01
        expected_tws = aws + stw
        assert abs(tws - expected_tws) < 0.01

    def test_beam_reach(self) -> None:
        awa = math.radians(90)
        aws = 10.0
        stw = 5.0
        twa, tws = compute_true_wind(awa, aws, stw)
        assert twa is not None
        assert tws is not None
        x = aws * math.sin(awa)
        y = aws * math.cos(awa) - stw
        expected_twa = math.atan2(x, y)
        expected_tws = math.sqrt(x * x + y * y)
        assert abs(twa - expected_twa) < 0.001
        assert abs(tws - expected_tws) < 0.01

    def test_symmetry_positive_negative_awa(self) -> None:
        awa_pos = math.radians(45)
        awa_neg = math.radians(-45)
        aws = 10.0
        stw = 5.0
        twa_pos, tws_pos = compute_true_wind(awa_pos, aws, stw)
        twa_neg, tws_neg = compute_true_wind(awa_neg, aws, stw)
        assert twa_pos is not None
        assert twa_neg is not None
        assert abs(abs(twa_pos) - abs(twa_neg)) < 0.01
        assert abs(tws_pos - tws_neg) < 0.01

    def test_all_none(self) -> None:
        twa, tws = compute_true_wind(None, None, None)
        assert twa is None
        assert tws is None

    def test_close_hauled_precise(self) -> None:
        awa = math.radians(30)
        aws = 10.0
        stw = 5.0
        twa, tws = compute_true_wind(awa, aws, stw)
        assert twa is not None
        assert tws is not None
        x = aws * math.sin(awa)
        y = aws * math.cos(awa) - stw
        expected_twa = math.atan2(x, y)
        expected_tws = math.sqrt(x * x + y * y)
        assert abs(twa - expected_twa) < 0.001
        assert abs(tws - expected_tws) < 0.01

    def test_roundtrip_forward(self) -> None:
        twa_in = math.radians(45)
        tws_in = 10.0
        stw = 5.0
        aws = math.sqrt((tws_in * math.cos(twa_in) + stw) ** 2 + (tws_in * math.sin(twa_in)) ** 2)
        awa = math.atan2(tws_in * math.sin(twa_in), tws_in * math.cos(twa_in) + stw)
        twa_out, tws_out = compute_true_wind(awa, aws, stw)
        assert twa_out is not None
        assert tws_out is not None
        assert abs(twa_out - twa_in) < 0.001
        assert abs(tws_out - tws_in) < 0.01

    def test_roundtrip_broad_reach(self) -> None:
        twa_in = math.radians(135)
        tws_in = 8.0
        stw = 4.0
        aws = math.sqrt((tws_in * math.cos(twa_in) + stw) ** 2 + (tws_in * math.sin(twa_in)) ** 2)
        awa = math.atan2(tws_in * math.sin(twa_in), tws_in * math.cos(twa_in) + stw)
        twa_out, tws_out = compute_true_wind(awa, aws, stw)
        assert twa_out is not None
        assert tws_out is not None
        assert abs(twa_out - twa_in) < 0.001
        assert abs(tws_out - tws_in) < 0.01

    def test_roundtrip_running(self) -> None:
        twa_in = math.radians(180)
        tws_in = 10.0
        stw = 5.0
        aws = tws_in - stw
        awa = math.pi
        twa_out, tws_out = compute_true_wind(awa, aws, stw)
        assert twa_out is not None
        assert tws_out is not None
        assert abs(abs(twa_out) - abs(twa_in)) < 0.001
        assert abs(tws_out - tws_in) < 0.01

    def test_roundtrip_close_hauled_port(self) -> None:
        twa_in = math.radians(-40)
        tws_in = 12.0
        stw = 6.0
        aws = math.sqrt((tws_in * math.cos(twa_in) + stw) ** 2 + (tws_in * math.sin(twa_in)) ** 2)
        awa = math.atan2(tws_in * math.sin(twa_in), tws_in * math.cos(twa_in) + stw)
        twa_out, tws_out = compute_true_wind(awa, aws, stw)
        assert twa_out is not None
        assert tws_out is not None
        assert abs(twa_out - twa_in) < 0.001
        assert abs(tws_out - tws_in) < 0.01


# --- calc_vmg ---


class TestCalcVmg:
    def test_basic(self) -> None:
        polar = make_test_polar()
        result = calc_vmg(polar, 6)
        assert result is not None
        assert "upwind_twa" in result
        assert "upwind_vmg" in result
        assert "downwind_twa" in result
        assert "downwind_vmg" in result

    def test_upwind_at_30_deg(self) -> None:
        polar = make_test_polar()
        result = calc_vmg(polar, 6)
        assert result is not None
        vmg_30 = 3.5 * math.cos(math.radians(30))
        vmg_60 = 5.0 * math.cos(math.radians(60))
        assert abs(result["upwind_vmg"] - max(vmg_30, vmg_60)) < 0.01

    def test_downwind_at_150_deg(self) -> None:
        polar = make_test_polar()
        result = calc_vmg(polar, 6)
        assert result is not None
        vmg_150 = 3.5 * math.cos(math.radians(150))
        vmg_120 = 5.0 * math.cos(math.radians(120))
        vmg_180 = 2.0 * math.cos(math.radians(180))
        expected_downwind = max(-vmg_150, -vmg_120, -vmg_180)
        assert abs(result["downwind_vmg"] - expected_downwind) < 0.01

    def test_none_polar(self) -> None:
        assert calc_vmg(None, 10) is None  # type: ignore[arg-type]

    def test_none_tws(self) -> None:
        polar = make_test_polar()
        assert calc_vmg(polar, None) is None  # type: ignore[arg-type]


# --- calc_vmc ---


class TestCalcVmc:
    def test_course_along_best_twa(self) -> None:
        polar = make_test_polar()
        result = calc_vmc(polar, 6, 60)
        assert result is not None
        assert abs(result["best_twa"]) == 60
        assert abs(result["best_speed"] - 5.0) < 0.01

    def test_course_upwind(self) -> None:
        polar = make_test_polar()
        result = calc_vmc(polar, 6, 30)
        assert result is not None
        assert result["best_vmc"] > 0

    def test_course_downwind(self) -> None:
        polar = make_test_polar()
        result = calc_vmc(polar, 6, 150)
        assert result is not None
        assert result["best_vmc"] > 0

    def test_tack_selection(self) -> None:
        polar = make_test_polar()
        result = calc_vmc(polar, 6, 45)
        assert result is not None
        assert result["best_tack"] in ("port", "starboard")

    def test_none_inputs(self) -> None:
        polar = make_test_polar()
        assert calc_vmc(None, 6, 45) is None  # type: ignore[arg-type]
        assert calc_vmc(polar, None, 45) is None  # type: ignore[arg-type]
        assert calc_vmc(polar, 6, None) is None  # type: ignore[arg-type]

    def test_returns_course_twa(self) -> None:
        polar = make_test_polar()
        result = calc_vmc(polar, 6, 90)
        assert result is not None
        assert result["course_twa"] == 90


class TestExamplePolarFiltering:
    """Shipped example_ polars load only when no real polars exist."""

    CSV = "TWA\\TWS;6;10\n45;4.0;5.0\n90;5.5;7.0\n"

    def _write(self, directory: str, name: str) -> None:
        import os

        with open(os.path.join(directory, name), "w") as f:
            f.write(self.CSV)

    def test_examples_load_when_alone(self) -> None:
        import tempfile

        from boatpolars.parser import discover_polars, list_polar_csvs

        with tempfile.TemporaryDirectory() as d:
            self._write(d, "example_J105_Jib.csv")
            self._write(d, "example_J105_Asym.csv")
            assert len(list_polar_csvs(d)) == 2
            names = [p.name for p in discover_polars(d)]
            assert names == ["example_J105_Asym", "example_J105_Jib"]

    def test_examples_hidden_when_real_polar_present(self) -> None:
        import tempfile

        from boatpolars.parser import discover_polars, list_polar_csvs

        with tempfile.TemporaryDirectory() as d:
            self._write(d, "example_J105_Jib.csv")
            self._write(d, "example_J105_Asym.csv")
            self._write(d, "MyBoat_Jib.csv")
            assert len(list_polar_csvs(d)) == 1
            names = [p.name for p in discover_polars(d)]
            assert names == ["MyBoat_Jib"]

    def test_real_only_dir_unaffected(self) -> None:
        import tempfile

        from boatpolars.parser import discover_polars

        with tempfile.TemporaryDirectory() as d:
            self._write(d, "MyBoat_Jib.csv")
            self._write(d, "MyBoat_Code0.csv")
            names = [p.name for p in discover_polars(d)]
            assert names == ["MyBoat_Code0", "MyBoat_Jib"]

    def test_missing_dir_returns_empty(self) -> None:
        from boatpolars.parser import list_polar_csvs

        assert list_polar_csvs("/nonexistent/polars") == []
