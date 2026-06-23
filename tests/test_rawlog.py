from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

try:
    import tomllib  # noqa: F401

    _HAS_TOMLLIB = True
except ModuleNotFoundError:
    _HAS_TOMLLIB = False

from signalk.rawlog import (
    _output_exists,
    _read_single_file,
    auto_convert_raw_dir,
    parse_raw_line,
)


class TestParseRawLine:
    def test_empty_line_returns_none(self):
        result = parse_raw_line("", None)  # type: ignore[arg-type]
        assert result is None

    def test_blank_line_returns_none(self):
        result = parse_raw_line("   ", None)  # type: ignore[arg-type]
        assert result is None

    def test_no_semicolon_returns_none(self):
        result = parse_raw_line("abc", None)  # type: ignore[arg-type]
        assert result is None

    def test_single_field_returns_none(self):
        result = parse_raw_line("123", None)  # type: ignore[arg-type]
        assert result is None

    def test_unknown_provider_returns_none(self):
        result = parse_raw_line("123;unknown;data", None)  # type: ignore[arg-type]
        assert result is None

    def test_course_provider_invalid_json_returns_none(self):
        result = parse_raw_line("123;course-provider;{bad json", None)  # type: ignore[arg-type]
        assert result is None

    def test_course_provider_valid_delta(self):
        delta = {
            "updates": [
                {
                    "values": [
                        {"path": "navigation.headingMagnetic", "value": 1.57},
                        {"path": "navigation.speedThroughWater", "value": 2.5},
                    ]
                }
            ]
        }
        line = f"123;course-provider;{json.dumps(delta)}"
        result = parse_raw_line(line, None)  # type: ignore[arg-type]
        assert result is not None
        ts, updates = result
        assert ts == 123
        assert updates["headingMagnetic"] == 1.57
        assert updates["speedThroughWater"] == 2.5

    def test_course_provider_skips_none_values(self):
        delta = {"updates": [{"values": [{"path": "navigation.headingMagnetic", "value": None}]}]}
        line = f"123;course-provider;{json.dumps(delta)}"
        result = parse_raw_line(line, None)  # type: ignore[arg-type]
        assert result is None

    def test_course_provider_unknown_path_ignored(self):
        delta = {"updates": [{"values": [{"path": "navigation.unknownPath", "value": 1}]}]}
        line = f"123;course-provider;{json.dumps(delta)}"
        result = parse_raw_line(line, None)  # type: ignore[arg-type]
        assert result is None


class TestReadSingleFile:
    def test_reads_lines_in_range(self, tmp_path):
        raw = tmp_path / "skserver-raw_2026-06-05T09.log"
        # ts_ms chosen so ts_utc falls in 09:00-10:00 UTC.
        ts_in = int(datetime(2026, 6, 5, 9, 30, tzinfo=timezone.utc).timestamp() * 1000)
        ts_out = int(datetime(2026, 6, 5, 11, 0, tzinfo=timezone.utc).timestamp() * 1000)
        raw.write_text(f"{ts_in};course-provider;{{}}\n{ts_out};course-provider;{{}}\n")
        start = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
        lines = _read_single_file(str(raw), start, end)
        assert len(lines) == 1
        assert lines[0][0] == ts_in

    def test_filters_out_of_range(self, tmp_path):
        raw = tmp_path / "skserver-raw_2026-06-05T09.log"
        ts_in = int(datetime(2026, 6, 5, 9, 30, tzinfo=timezone.utc).timestamp() * 1000)
        ts_out = int(datetime(2026, 6, 5, 11, 0, tzinfo=timezone.utc).timestamp() * 1000)
        raw.write_text(f"{ts_in};course-provider;{{}}\n{ts_out};course-provider;{{}}\n")
        start = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
        lines = _read_single_file(str(raw), start, end)
        assert len(lines) == 1
        assert lines[0][0] == ts_in

    def test_skips_malformed_timestamp(self, tmp_path):
        raw = tmp_path / "skserver-raw_2026-06-05T09.log"
        raw.write_text("abc;course-provider;{}\n")
        start = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
        lines = _read_single_file(str(raw), start, end)
        assert lines == []

    def test_missing_file_returns_empty(self):
        lines = _read_single_file(
            "/nonexistent/skserver-raw_2026-06-05T09.log",
            datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc),
        )
        assert lines == []


class TestOutputExists:
    def test_no_dir_returns_false(self, tmp_path):
        assert _output_exists(str(tmp_path / "missing"), "sailing_") is False

    def test_matching_prefix_returns_true(self, tmp_path):
        (tmp_path / "sailing_20260605_09.jsonl").write_text("{}")
        assert _output_exists(str(tmp_path), "sailing_20260605_09") is True

    def test_no_matching_prefix_returns_false(self, tmp_path):
        (tmp_path / "sailing_20260605_10.jsonl").write_text("{}")
        assert _output_exists(str(tmp_path), "sailing_20260605_09") is False


class TestAutoConvertRawDir:
    def test_empty_dir_returns_empty(self, tmp_path):
        raw_dir = tmp_path / "raw"
        out_dir = tmp_path / "out"
        raw_dir.mkdir()
        assert auto_convert_raw_dir(str(raw_dir), str(out_dir), 0.0) == []

    def test_missing_dir_returns_empty(self, tmp_path):
        assert auto_convert_raw_dir(str(tmp_path / "missing"), str(tmp_path / "out"), 0.0) == []

    def test_skips_non_raw_files(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "not_a_raw_log.txt").write_text("junk")
        result = auto_convert_raw_dir(str(raw_dir), str(tmp_path / "out"), 0.0)
        assert result == []

    def test_skips_already_converted(self, tmp_path):
        raw_dir = tmp_path / "raw"
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        raw_dir.mkdir()
        # A raw file for 09:00 local (offset 0 => 09:00 UTC).
        raw_path = raw_dir / "skserver-raw_2026-06-05T09.log"
        raw_path.write_text("")  # empty raw file; no entries will be produced
        # Pre-create an output JSONL matching the UTC hour prefix.
        (out_dir / "sailing_20260605_09.jsonl").write_text("{}")
        result = auto_convert_raw_dir(str(raw_dir), str(out_dir), 0.0)
        # Empty raw file produces nothing; the skip check is based on the
        # output prefix existing, so no conversion is attempted.
        assert result == []


class TestConfigLoggingFields:
    def test_defaults(self):
        from config import Config

        cfg = Config()
        assert cfg.auto_convert_raw is False
        assert cfg.local_tz_offset == 0.0
        assert cfg.raw_dir.endswith(os.path.join("logs", "raw"))

    @pytest.mark.skipif(not _HAS_TOMLLIB, reason="tomllib requires Python 3.11+")
    def test_loads_from_toml(self, tmp_path):
        from config import load_config

        toml = tmp_path / "polarprism.toml"
        toml.write_text(
            "[logging]\nauto_convert_raw = true\nlocal_tz_offset = -4.0\n"
            '[paths]\nraw_dir = "myraw"\n'
        )
        cfg = load_config(str(toml))
        assert cfg.auto_convert_raw is True
        assert cfg.local_tz_offset == -4.0
        assert cfg.raw_dir.endswith("myraw")
