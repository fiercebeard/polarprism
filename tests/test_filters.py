from __future__ import annotations

import json
import math

import pytest

from signalk.filters import (
    DEFAULT_CUTOFF_HZ,
    AngularOnePoleFilter,
    FilterConfig,
    FilterManager,
    OnePoleFilter,
    _cutoff_to_alpha,
    _unwrap_deg,
    analyze_log,
)


class TestOnePoleFilter:
    def test_first_sample_seeds_output(self):
        f = OnePoleFilter(0.05)
        assert f.update(5.0) == 5.0

    def test_converges_to_constant(self):
        f = OnePoleFilter(0.05)
        for _ in range(500):
            f.update(10.0)
        assert abs(f.value - 10.0) < 0.01

    def test_attenuates_high_frequency(self):
        """A 0.25 Hz oscillation should be heavily attenuated at 0.05 Hz cutoff."""
        f = OnePoleFilter(0.05)
        outputs = []
        for i in range(200):
            v = 1.0 + 0.5 * math.sin(2 * math.pi * 0.25 * i)
            outputs.append(f.update(v))
        # After convergence, the amplitude of the residual oscillation
        # should be much smaller than the input amplitude (0.5).
        steady = outputs[-50:]
        mean = sum(steady) / len(steady)
        max_dev = max(abs(s - mean) for s in steady)
        assert max_dev < 0.1, f"residual {max_dev} should be << 0.5"

    def test_passes_low_frequency(self):
        """A slow drift passes through with moderate attenuation at 0.05 Hz.

        A one-pole filter at fc has gain ~0.9 at fc/3, so a 0.005 Hz
        signal (fc/10) should retain most of its amplitude.
        """
        f = OnePoleFilter(0.05)
        outputs = []
        for i in range(200):
            v = 1.0 + 0.5 * math.sin(2 * math.pi * 0.005 * i)  # 0.005 Hz
            outputs.append(f.update(v))
        # After convergence, the amplitude should be a significant fraction
        # of the input amplitude (0.5). One-pole gain at fc/10 is ~0.98.
        steady = outputs[-100:]
        peak = max(s for s in steady)
        trough = min(s for s in steady)
        assert (peak - trough) > 0.4, f"span {peak - trough} should retain most of 1.0"

    def test_reset_clears_state(self):
        f = OnePoleFilter(0.05)
        f.update(5.0)
        f.reset()
        assert f.value is None
        assert f.update(10.0) == 10.0

    def test_set_cutoff_updates_alpha(self):
        f = OnePoleFilter(0.05)
        old_alpha = f._alpha
        f.set_cutoff(0.1)
        assert f.cutoff_hz == 0.1
        assert f._alpha != old_alpha

    def test_time_aware_alpha(self):
        """A larger dt should produce a larger alpha (faster convergence)."""
        f = OnePoleFilter(0.05)
        a1 = f._alpha_for_dt(1.0)
        a10 = f._alpha_for_dt(10.0)
        assert a10 > a1


class TestAngularOnePoleFilter:
    def test_handles_wraparound(self):
        """Filtering near 0/360 should not jump."""
        f = AngularOnePoleFilter(0.05)
        # Start near 350 degrees, increment past 360
        for i in range(20):
            f.update(math.radians(350 + i))
        result_deg = math.degrees(f.value) % 360
        assert 350 <= result_deg <= 360 or 0 <= result_deg <= 10, f"got {result_deg}"

    def test_converges_to_constant_angle(self):
        f = AngularOnePoleFilter(0.05)
        for _ in range(500):
            f.update(math.radians(90))
        assert abs(math.degrees(f.value) - 90.0) < 0.5

    def test_output_normalized(self):
        f = AngularOnePoleFilter(0.05)
        for _ in range(100):
            f.update(math.radians(720))  # 2 full rotations
        assert 0 <= f.value < 2 * math.pi

    def test_reset(self):
        f = AngularOnePoleFilter(0.05)
        f.update(math.radians(45))
        f.reset()
        assert f.value is None


class TestCutoffToAlpha:
    def test_zero_cutoff_returns_one(self):
        assert _cutoff_to_alpha(0, 1.0) == 1.0

    def test_high_cutoff_faster_response(self):
        """Higher cutoff = larger alpha = less smoothing."""
        a_low = _cutoff_to_alpha(0.02, 1.0)
        a_high = _cutoff_to_alpha(0.1, 1.0)
        assert a_high > a_low


class TestFilterManager:
    def test_disabled_returns_raw(self):
        cfg = FilterConfig(enabled=False)
        mgr = FilterManager(cfg)
        assert mgr.get("cogTrue", 1.5) == 1.5
        assert mgr.get("speedOverGround", 3.0) == 3.0

    def test_enabled_returns_filtered(self):
        cfg = FilterConfig(enabled=True)
        mgr = FilterManager(cfg)
        mgr.update("speedOverGround", 5.0)
        assert mgr.get("speedOverGround", None) == 5.0  # first sample seeds
        mgr.update("speedOverGround", 6.0)
        result = mgr.get("speedOverGround", None)
        assert 5.0 < result < 6.0  # smoothed

    def test_unknown_signal_returns_raw(self):
        cfg = FilterConfig(enabled=True)
        mgr = FilterManager(cfg)
        assert mgr.get("unknownSignal", 42.0) == 42.0

    def test_no_filter_returns_raw(self):
        cfg = FilterConfig(enabled=True)
        mgr = FilterManager(cfg)
        assert mgr.get("cogTrue", None) is None

    def test_reset(self):
        cfg = FilterConfig(enabled=True)
        mgr = FilterManager(cfg)
        mgr.update("cogTrue", math.radians(45))
        mgr.reset()
        assert mgr.get("cogTrue", 99.0) == 99.0  # falls back to raw

    def test_reconfigure(self):
        cfg = FilterConfig(enabled=True, cutoffs={"cogTrue": 0.1})
        mgr = FilterManager(cfg)
        mgr.update("cogTrue", math.radians(45))
        new_cfg = FilterConfig(enabled=True, cutoffs={"cogTrue": 0.02})
        mgr.reconfigure(new_cfg)
        assert mgr.get("cogTrue", None) is None  # reset


class TestAnalyzeLog:
    @pytest.fixture
    def synthetic_log(self, tmp_path):
        """Create a sailing log with a 0.25 Hz artifact on COG/SOG."""
        from datetime import datetime, timezone

        path = tmp_path / "test_sailing.jsonl"
        entries = []
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(600):  # 10 minutes at 1 Hz
            ts = base + timedelta_seconds(i)
            cog_artifact = 5.0 * math.sin(2 * math.pi * 0.25 * i)  # 0.25 Hz
            sog_artifact = 0.3 * math.sin(2 * math.pi * 0.25 * i)
            entry = {
                "ts": ts.isoformat(),
                "position": {"lat": 41.0, "lon": -81.0},
                "headingTrue": 180.0,
                "cogTrue": 180.0 + cog_artifact,
                "sog": 6.0 + sog_artifact,
                "stw": 6.0,
                "twa": 45.0,
                "tws": 10.0,
                "twd": 225.0,
                "awa": 40.0,
                "aws": 12.0,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "",
            }
            entries.append(entry)
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return str(path)

    def test_finds_artifact(self, synthetic_log):
        suggestions = analyze_log(synthetic_log)
        assert len(suggestions) == 2
        sigs = {s.signal for s in suggestions}
        assert sigs == {"cogTrue", "speedOverGround"}
        for s in suggestions:
            assert s.artifact_hz is not None
            assert 0.1 < s.artifact_hz < 0.4, f"artifact {s.artifact_hz} near 0.25 Hz"
            assert s.cutoff_hz > 0

    def test_short_log_returns_empty(self, tmp_path):
        path = tmp_path / "short.jsonl"
        from datetime import datetime, timezone

        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with open(path, "w") as f:
            for i in range(10):  # too short
                e = {
                    "ts": (base + timedelta_seconds(i)).isoformat(),
                    "cogTrue": 180.0,
                    "sog": 6.0,
                }
                f.write(json.dumps(e) + "\n")
        assert analyze_log(str(path)) == []

    def test_event_entries_skipped(self, tmp_path):
        path = tmp_path / "events.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"ts": "2026-01-01T00:00:00+00:00", "event": "log_start"}) + "\n")
            f.write(json.dumps({"ts": "2026-01-01T00:00:01+00:00", "event": "log_stop"}) + "\n")
        assert analyze_log(str(path)) == []


class TestUnwrapDeg:
    def test_unwraps_wraparound(self):
        vals = [350, 355, 0, 5, 10]
        unwrapped = _unwrap_deg(vals)
        assert unwrapped == [350, 355, 360, 365, 370]

    def test_unwraps_negative(self):
        vals = [10, 5, 0, 355, 350]
        unwrapped = _unwrap_deg(vals)
        assert unwrapped == [10, 5, 0, -5, -10]


class TestFilterConfigDefaults:
    def test_default_cutoff(self):
        cfg = FilterConfig()
        assert cfg.cutoff_for("cogTrue") == DEFAULT_CUTOFF_HZ

    def test_custom_cutoff(self):
        cfg = FilterConfig(cutoffs={"cogTrue": 0.03})
        assert cfg.cutoff_for("cogTrue") == 0.03
        assert cfg.cutoff_for("speedOverGround") == DEFAULT_CUTOFF_HZ


class TestFilteredValue:
    def test_no_manager_returns_raw(self):
        from signalk.models import State, filtered_value

        st = State()
        st.values["cogTrue"] = 1.5
        assert filtered_value(st, "cogTrue") == 1.5

    def test_disabled_returns_raw(self):
        from signalk.models import State, filtered_value

        st = State()
        st.values["cogTrue"] = 1.5
        cfg = FilterConfig(enabled=False)
        st.filter_manager = FilterManager(cfg)
        assert filtered_value(st, "cogTrue") == 1.5

    def test_enabled_returns_filtered(self):
        from signalk.models import State, filtered_value

        st = State()
        st.values["speedOverGround"] = 5.0
        cfg = FilterConfig(enabled=True)
        st.filter_manager = FilterManager(cfg)
        st.filter_manager.update("speedOverGround", 5.0)
        st.values["speedOverGround"] = 6.0
        st.filter_manager.update("speedOverGround", 6.0)
        result = filtered_value(st, "speedOverGround")
        assert 5.0 < result < 6.0


def timedelta_seconds(s):
    from datetime import timedelta

    return timedelta(seconds=s)
