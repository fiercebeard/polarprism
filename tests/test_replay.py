"""Tests for replay engine and session management."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from replay.engine import ReplaySession, _parse_ts_to_float, _wall_from_ts


class TestReplaySessionLoad:
    def test_loads_valid_log_file(self, tmp_path: str) -> None:
        entries = [
            {
                "ts": "2026-01-01T10:00:00.000000+00:00",
                "position": None,
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
        ]
        f = tmp_path / "sailing_test.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        session = ReplaySession(str(f))
        assert session.entry_count == 1
        assert session.wall_start == "10:00:00"
        assert session.wall_end == "10:00:00"
        assert session.wall_current == "10:00:00"
        assert session.polar_name == "TEST"
        assert session.active_log_name == "sailing_test.jsonl"
        assert session.entry_count == 1
        assert session.is_done is False
        assert session.is_paused is False

    def test_skips_blank_lines(self, tmp_path: str) -> None:
        f = tmp_path / "sailing_blank.jsonl"
        f.write_text("\n\n\nhello\n\n")
        session = ReplaySession(str(f))
        assert session.entry_count == 0

    def test_unchanged_by_events(self, tmp_path: str) -> None:
        entries = [
            {"ts": "2026-01-01T10:00:00.000000+00:00", "event": "log_start", "polar": "X"},
            {
                "ts": "2026-01-01T10:00:01.000000+00:00",
                "position": None,
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
        ]
        f = tmp_path / "sailing_events.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        session = ReplaySession(str(f))
        assert session.entry_count == 2

    def test_empty_file_gives_zero_entries(self, tmp_path: str) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        session = ReplaySession(str(f))
        assert session.entry_count == 0
        assert session.wall_start == ""
        assert session.wall_end == ""
        assert session.progress_ratio == 0.0
        assert session.is_done is False

    def test_polar_name_property(self, tmp_path: str) -> None:
        entries = [
            {
                "ts": "2026-01-01T10:00:00.000000+00:00",
                "position": None,
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "MyPolar",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
        ]
        f = tmp_path / "sailing_pn.jsonl"
        f.write_text(json.dumps(entries[0]) + "\n")
        session = ReplaySession(str(f))
        assert session.polar_name == "MyPolar"

    def test_mixed_entries_with_events(self, tmp_path: str) -> None:
        entries = [
            {"ts": "2026-01-01T10:00:00.000000+00:00", "event": "log_start", "polar": "X"},
            {
                "ts": "2026-01-01T10:00:01.000000+00:00",
                "position": {"lat": 1.0, "lon": 2.0},
                "headingTrue": 180.0,
                "cogTrue": 175.0,
                "sog": 5.0,
                "stw": 5.5,
                "twa": -90.0,
                "tws": 15.0,
                "twd": 200.0,
                "awa": 270.0,
                "aws": 12.0,
                "sailing_state": "sailing",
                "active_sails": ["Jib"],
                "polar_name": "Test1",
                "polar_target_speed": 6.0,
                "polar_performance_pct": 75.0,
            },
            {
                "ts": "2026-01-01T10:00:02.000000+00:00",
                "event": "sail_change",
                "active_sails": ["Jib", "Mainsail"],
            },
            {
                "ts": "2026-01-01T10:00:03.000000+00:00",
                "position": {"lat": 1.1, "lon": 2.1},
                "headingTrue": 181.0,
                "cogTrue": 176.0,
                "sog": 5.1,
                "stw": 5.6,
                "twa": -89.0,
                "tws": 15.5,
                "twd": 201.0,
                "awa": 271.0,
                "aws": 12.5,
                "sailing_state": "sailing",
                "active_sails": ["Jib", "Mainsail"],
                "polar_name": "Test1",
                "polar_target_speed": 6.1,
                "polar_performance_pct": 74.5,
            },
        ]
        f = tmp_path / "sailing_mixed.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        session = ReplaySession(str(f))
        assert session.entry_count == 4
        assert session.wall_start == "10:00:00"
        assert session.wall_end == "10:00:03"


class TestReplaySessionAdvance:
    def test_advance_updates_state(self, tmp_path: str) -> None:
        entries = [
            {
                "ts": "2026-01-01T10:00:00.000000+00:00",
                "position": None,
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
            {
                "ts": "2026-01-01T10:00:01.000000+00:00",
                "position": {"lat": 41.5, "lon": -82.0},
                "headingTrue": 90.0,
                "cogTrue": 88.0,
                "sog": 6.0,
                "stw": 6.5,
                "twa": -100.0,
                "tws": 16.0,
                "twd": 200.0,
                "awa": 260.0,
                "aws": 13.0,
                "sailing_state": "sailing",
                "active_sails": ["Jib"],
                "polar_name": "TEST",
                "polar_target_speed": 7.0,
                "polar_performance_pct": 85.0,
            },
        ]
        f = tmp_path / "sailing_adv.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        session = ReplaySession(str(f))
        import math

        from signalk.models import State

        state = State()
        state.polar_data["TEST"] = MagicMock()
        for _ in range(6):
            session.advance(state, 50)
        assert state.position["lat"] == 41.5
        assert state.position["lon"] == -82.0
        assert state.values["headingTrue"] == math.radians(90.0)
        assert state.values["cogTrue"] == math.radians(88.0)
        assert state.values["speedOverGround"] == 6.0 * (1.0 / 1.94384)
        assert state.values["speedThroughWater"] == 6.5 * (1.0 / 1.94384)
        assert state.active_sails == ["Jib"]
        assert state.polar_active == "TEST"
        assert state.connected is True

    def test_advance_respects_speed(self, tmp_path: str) -> None:
        lines = []
        for i in range(100):
            ts = f"2026-01-01T10:00:{i:02d}.000000+00:00"
            entry = {
                "ts": ts,
                "position": None,
                "headingTrue": 180.0,
                "cogTrue": 175.0,
                "sog": 5.0,
                "stw": 5.5,
                "twa": -90.0,
                "tws": 15.0,
                "twd": 200.0,
                "awa": 270.0,
                "aws": 12.0,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            }
            lines.append(json.dumps(entry))
        f = tmp_path / "sailing_speed.jsonl"
        f.write_text("\n".join(lines) + "\n")
        session = ReplaySession(str(f))
        session._speed_index = 0  # 1x
        state = MagicMock()
        old_idx = session._sample_idx
        session.advance(state, 1000)  # 1 second at 1x
        assert session._sample_idx > old_idx  # advanced at least 1 sample

    def test_pause_resumes(self, tmp_path: str) -> None:
        entries = [
            {
                "ts": "2026-01-01T10:00:00.000000+00:00",
                "position": None,
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
            {
                "ts": "2026-01-01T10:00:01.000000+00:00",
                "position": {"lat": 41.0, "lon": -82.0},
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
        ]
        f = tmp_path / "sailing_pause.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        session = ReplaySession(str(f))
        # advance 100ms
        session.advance(state=MagicMock(), dt_ms=100)
        first_idx = session._sample_idx
        session.toggle_pause()
        assert session.is_paused is True
        session.advance(state=MagicMock(), dt_ms=100)
        assert session._sample_idx == first_idx  # should not advance while paused
        session.toggle_pause()
        assert session.is_paused is False

    def test_reset(self, tmp_path: str) -> None:
        entries = [
            {
                "ts": "2026-01-01T10:00:00.000000+00:00",
                "position": None,
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
            {
                "ts": "2026-01-01T10:00:01.000000+00:00",
                "position": {"lat": 41.0, "lon": -82.0},
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
        ]
        f = tmp_path / "sailing_reset.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        session = ReplaySession(str(f))
        session.advance(state=MagicMock(), dt_ms=500)
        session.reset()
        assert session.is_done is False
        assert session.is_paused is False
        assert session._sample_idx == 0

    def test_speed_control_stepping(self, tmp_path: str) -> None:
        entries = [
            {
                "ts": "2026-01-01T10:00:00.000000+00:00",
                "position": None,
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
        ]
        f = tmp_path / "sailing_speed_step.jsonl"
        f.write_text(json.dumps(entries[0]) + "\n")
        session = ReplaySession(str(f))
        assert session.speed_label == "5x"
        session.speed_up()
        assert session.speed_label == "10x"
        session.speed_up()
        assert session.speed_label == "20x"
        session.speed_up()  # at max, should stay
        assert session.speed_label == "20x"
        session.speed_down()
        assert session.speed_label == "10x"
        session._speed_index = 0
        assert session.speed_label == "1x"

    def test_seek_to_sample(self, tmp_path: str) -> None:
        entries = [
            {
                "ts": "2026-01-01T10:00:00.000000+00:00",
                "position": {"lat": 0.0, "lon": 0.0},
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
            {
                "ts": "2026-01-01T10:00:01.000000+00:00",
                "position": {"lat": 1.0, "lon": 1.0},
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
            {
                "ts": "2026-01-01T10:00:02.000000+00:00",
                "position": {"lat": 2.0, "lon": 2.0},
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
        ]
        f = tmp_path / "sailing_seek.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        session = ReplaySession(str(f))
        session.seek_to(1)
        assert session._sample_idx == 1


class TestHelperFunctions:
    def test_parse_ts_to_float_handles_valid_iso(self) -> None:
        ts = "2026-01-01T10:30:45.123456+00:00"
        result = _parse_ts_to_float(ts)
        assert result > 0
        assert isinstance(result, float)

    def test_parse_ts_to_float_handles_edge_cases(self) -> None:
        assert _parse_ts_to_float("") == 0
        assert _parse_ts_to_float(None) == 0

    def test_wall_from_iso(self) -> None:
        result = _wall_from_ts("2026-01-01T14:23:45.678900+00:00")
        assert result == "14:23:45"

    def test_wall_from_plain_string(self) -> None:
        result = _wall_from_ts("14:23:45")
        assert result == "14:23:45"

    def test_wall_from_short_string(self) -> None:
        result = _wall_from_ts("abc")
        assert result == "abc"


class TestReplaySessionEdgeCases:
    def test_event_entries_does_not_affect_progress(self, tmp_path: str) -> None:
        entries = [
            {"ts": "2026-01-01T10:00:00.000000+00:00", "event": "log_start"},
            {
                "ts": "2026-01-01T10:00:01.000000+00:00",
                "position": {"lat": 1.0, "lon": 1.0},
                "headingTrue": None,
                "cogTrue": None,
                "sog": None,
                "stw": None,
                "twa": None,
                "tws": None,
                "twd": None,
                "awa": None,
                "aws": None,
                "sailing_state": "sailing",
                "active_sails": [],
                "polar_name": "TEST",
                "polar_target_speed": None,
                "polar_performance_pct": None,
            },
        ]
        f = tmp_path / "sailing_evt.jsonl"
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        session = ReplaySession(str(f))
        assert session.entry_count == 2  # both entries are loaded
        assert session.wall_start == "10:00:00"
        # advance to second entry
        state = MagicMock()
        session.advance(state, 5000)
        assert session._sample_idx == 2  # advanced past the event entry
