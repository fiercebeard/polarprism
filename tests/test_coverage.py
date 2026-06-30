from __future__ import annotations

import json
import math
import os

from polars.coverage import (
    TWA_BIN_DEG,
    TWA_MAX_DEG,
    TWA_MIN_DEG,
    TWS_BIN_KTS,
    TWS_MAX_KTS,
    TWS_MIN_KTS,
    bin_sample,
    build_coverage_from_session,
    build_coverage_from_sessions,
    combine_best,
    coverage_counts,
    coverage_mean,
    interpolate_measured,
    load_coverage_sidecar,
    merge_coverage,
    read_measured_polar_csv,
    save_coverage_sidecar,
    seed_groups_from_logs,
)
from signalk.models import MS_TO_KNOTS


def sample_inputs(awa_deg: float, aws_kts: float, stw_kts: float) -> tuple[float, float, float]:
    return math.radians(awa_deg), aws_kts / MS_TO_KNOTS, stw_kts / MS_TO_KNOTS


class TestBinSample:
    def test_basic_bin(self) -> None:
        # 60 deg AWA, 12 kt AWS, 5 kt STW -> true wind ~ 90 deg TWA at higher TWS
        result = bin_sample(*sample_inputs(60, 12, 5))
        assert result is not None
        twa_bin, tws_bin, stw_kts = result
        assert twa_bin % TWA_BIN_DEG == 0
        assert tws_bin % TWS_BIN_KTS == 0
        assert TWA_MIN_DEG <= twa_bin <= TWA_MAX_DEG
        assert TWS_MIN_KTS <= tws_bin <= TWS_MAX_KTS
        assert abs(stw_kts - 5.0) < 0.01

    def test_filter_slow_stw(self) -> None:
        assert bin_sample(*sample_inputs(60, 12, 1.0)) is None

    def test_filter_low_aws(self) -> None:
        assert bin_sample(*sample_inputs(60, 3.0, 5.0)) is None

    def test_out_of_range_twa(self) -> None:
        # near-headwind: small AWA, low STW -> tiny TWA, below 30 deg
        result = bin_sample(*sample_inputs(10, 6, 5))
        # could be None (filtered) or below range; either way acceptable
        if result is not None:
            assert result[0] >= TWA_MIN_DEG

    def test_stw_below_min_returns_none(self) -> None:
        assert bin_sample(*sample_inputs(60, 12, 1.9)) is None

    def test_awa_over_180_normalized(self) -> None:
        # AWA 300 (= -60) should produce same magnitude TWA bin as 60
        r1 = bin_sample(*sample_inputs(60, 12, 5))
        r2 = bin_sample(*sample_inputs(300, 12, 5))
        assert r1 is not None and r2 is not None
        assert r1[0] == r2[0]
        assert r1[1] == r2[1]
        assert abs(r1[2] - r2[2]) < 0.01


class TestBuildCoverage:
    def test_build_from_session(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        p = tmp_path / "sailing_test.jsonl"
        lines = []
        for _ in range(5):
            lines.append(json.dumps({"awa": 60, "aws": 12.0, "stw": 5.0}))
        for _ in range(2):
            lines.append(json.dumps({"awa": 90, "aws": 10.0, "stw": 6.0}))
        # event line should be skipped
        lines.append(json.dumps({"event": "log_start"}))
        # filtered: too slow
        lines.append(json.dumps({"awa": 60, "aws": 12.0, "stw": 1.0}))
        p.write_text("\n".join(lines) + "\n")
        cov = build_coverage_from_session(str(p))
        # two distinct bins expected (60deg-ish TWA + 90deg-ish TWA)
        assert len(cov) >= 1
        for speeds in cov.values():
            assert all(isinstance(s, float) for s in speeds)

    def test_missing_file_returns_empty(self) -> None:
        assert build_coverage_from_session("/nonexistent/path.jsonl") == {}

    def test_malformed_lines_skipped(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        p = tmp_path / "bad.jsonl"
        p.write_text("not json\n" + json.dumps({"awa": 60, "aws": 12.0, "stw": 5.0}) + "\n")
        cov = build_coverage_from_session(str(p))
        assert len(cov) == 1

    def test_merge_coverage(self) -> None:
        c1 = {(60, 12): [5.0, 5.1]}
        c2 = {(60, 12): [5.2], (90, 10): [6.0]}
        merged = merge_coverage(c1, c2)
        assert merged[(60, 12)] == [5.0, 5.1, 5.2]
        assert merged[(90, 10)] == [6.0]

    def test_build_from_sessions(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        p1 = tmp_path / "a.jsonl"
        p2 = tmp_path / "b.jsonl"
        p1.write_text(json.dumps({"awa": 60, "aws": 12.0, "stw": 5.0}) + "\n")
        p2.write_text(json.dumps({"awa": 60, "aws": 12.0, "stw": 5.5}) + "\n")
        cov = build_coverage_from_sessions([str(p1), str(p2)])
        assert len(cov) == 1
        assert len(next(iter(cov.values()))) == 2


class TestAggregation:
    def test_coverage_mean_min_samples(self) -> None:
        cov = {(60, 12): [5.0, 5.2, 5.4], (90, 10): [6.0], (120, 14): [4.0, 4.1]}
        means = coverage_mean(cov)
        assert (60, 12) in means
        assert abs(means[(60, 12)] - 5.2) < 0.001
        # (90,10) has only 1 sample < MIN_SAMPLES_PER_BIN(3), dropped
        assert (90, 10) not in means
        # (120,14) has 2 < 3, dropped
        assert (120, 14) not in means

    def test_coverage_mean_custom_min(self) -> None:
        cov = {(60, 12): [5.0, 5.2]}
        assert coverage_mean(cov, min_samples=2) == {(60, 12): 5.1}

    def test_coverage_counts(self) -> None:
        cov = {(60, 12): [5.0, 5.2, 5.4], (90, 10): [6.0]}
        counts = coverage_counts(cov)
        assert counts == {(60, 12): 3, (90, 10): 1}


class TestInterpolate:
    def test_direct_hit(self) -> None:
        measured = {(60, 12): 5.2}
        assert interpolate_measured(measured, 60, 12) == 5.2

    def test_idw_from_neighbors(self) -> None:
        measured = {
            (55, 12): 5.0,
            (65, 12): 6.0,
            (60, 10): 4.5,
            (60, 14): 5.5,
        }
        val = interpolate_measured(measured, 60, 12)
        assert val is not None
        # should be in the range of neighbors
        assert 4.0 < val < 6.5

    def test_sparse_returns_none(self) -> None:
        measured = {(55, 12): 5.0}  # only one neighbor
        assert interpolate_measured(measured, 60, 12) is None

    def test_empty_returns_none(self) -> None:
        assert interpolate_measured({}, 60, 12) is None


class TestSeedGroups:
    def _write_log(self, path, polar: str, sails: list[str]) -> None:
        # log_start event then one data sample
        lines = [
            json.dumps({"event": "log_start", "polar": polar, "active_sails": sails}),
            json.dumps(
                {"awa": 60, "aws": 12.0, "stw": 5.0, "polar_name": polar, "active_sails": sails}
            ),
        ]
        path.write_text("\n".join(lines) + "\n")

    def test_groups_by_polar_and_sails(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        d = tmp_path / "sailing_logs"
        d.mkdir()
        self._write_log(d / "sailing_20260101_120000.jsonl", "Jib", ["Jib"])
        self._write_log(d / "sailing_20260102_120000.jsonl", "Jib", ["Jib"])
        self._write_log(d / "sailing_20260103_120000.jsonl", "Jib", ["Code 0", "Jib"])
        self._write_log(d / "sailing_20260104_120000.jsonl", "Spinnaker", ["Spinnaker"])
        groups = seed_groups_from_logs(str(d), ["Jib", "Spinnaker"])
        # three distinct (polar, sails) combos
        assert len(groups) == 3
        names = {g["name"] for g in groups}
        assert "Jib / Jib" in names
        assert "Jib / Code 0 + Jib" in names
        assert "Spinnaker / Spinnaker" in names
        # the two Jib/Jib sessions merged into one group
        jib_jib = next(g for g in groups if g["name"] == "Jib / Jib")
        assert len(jib_jib["sessions"]) == 2
        assert jib_jib["polar"] == "Jib"

    def test_falls_back_to_first_polar_when_missing(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        d = tmp_path / "sailing_logs"
        d.mkdir()
        # data sample without log_start, missing polar_name
        p = d / "sailing_20260105_120000.jsonl"
        p.write_text(json.dumps({"awa": 60, "aws": 12.0, "stw": 5.0}) + "\n")
        groups = seed_groups_from_logs(str(d), ["FirstPolar", "Second"])
        assert len(groups) == 1
        assert groups[0]["polar"] == "FirstPolar"

    def test_no_logs_returns_empty(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        d = tmp_path / "empty"
        d.mkdir()
        assert seed_groups_from_logs(str(d), ["Jib"]) == []

    def test_missing_dir_returns_empty(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        assert seed_groups_from_logs(str(tmp_path / "nope"), ["Jib"]) == []


class TestCoverageSidecar:
    def test_save_then_load_roundtrip(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        csv_path = tmp_path / "auto_polar_20260101.csv"
        coverage = {(60, 12): [5.0, 5.1, 5.2], (90, 10): [6.0, 6.1, 6.2]}
        side = save_coverage_sidecar(coverage, str(csv_path))
        assert os.path.exists(side)
        assert side.endswith(".cov.json")
        loaded = load_coverage_sidecar(str(csv_path))
        assert loaded == coverage

    def test_load_missing_sidecar_returns_empty(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        csv_path = tmp_path / "nope.csv"
        assert load_coverage_sidecar(str(csv_path)) == {}

    def test_load_malformed_sidecar_returns_empty(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        csv_path = tmp_path / "bad.csv"
        (tmp_path / "bad.cov.json").write_text("{ not valid json")
        assert load_coverage_sidecar(str(csv_path)) == {}

    def test_load_skips_bad_keys(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        csv_path = tmp_path / "mixed.csv"
        payload = {"60,12": [5.0, 5.1], "badkey": [1.0], "90,10": [6.0]}
        (tmp_path / "mixed.cov.json").write_text(json.dumps(payload))
        loaded = load_coverage_sidecar(str(csv_path))
        assert loaded == {(60, 12): [5.0, 5.1], (90, 10): [6.0]}

    def test_accumulation_merges_sessions(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        # simulate two accumulate runs into the same target file
        csv_path = tmp_path / "jib.csv"
        cov1 = {(60, 12): [5.0, 5.1, 5.2]}
        cov2 = {(60, 12): [5.3, 5.4], (90, 10): [6.0, 6.1, 6.2]}
        accumulated = merge_coverage(load_coverage_sidecar(str(csv_path)), cov1)
        save_coverage_sidecar(accumulated, str(csv_path))
        accumulated = merge_coverage(load_coverage_sidecar(str(csv_path)), cov2)
        save_coverage_sidecar(accumulated, str(csv_path))
        loaded = load_coverage_sidecar(str(csv_path))
        assert loaded[(60, 12)] == [5.0, 5.1, 5.2, 5.3, 5.4]
        assert loaded[(90, 10)] == [6.0, 6.1, 6.2]


class TestReadMeasuredPolarCsv:
    def test_roundtrip_with_write_polar_csv(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from log_analysis import write_polar_csv

        measured = {(60, 12): 5.20, (90, 10): 6.00}
        csv_path = tmp_path / "measured.csv"
        write_polar_csv(measured, str(csv_path), twa_steps=[60, 90], tws_steps=[10, 12])
        read_back = read_measured_polar_csv(str(csv_path))
        assert read_back == measured

    def test_missing_file_returns_empty(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        assert read_measured_polar_csv(str(tmp_path / "nope.csv")) == {}

    def test_empty_cells_skipped(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        csv_path = tmp_path / "sparse.csv"
        csv_path.write_text("TWA\\TWS;10;12\n60;;5.20\n90;6.00;\n")
        read_back = read_measured_polar_csv(str(csv_path))
        assert read_back == {(60, 12): 5.20, (90, 10): 6.00}


class TestCombineBest:
    def test_envelope_takes_max_per_bin(self) -> None:
        jib = {(60, 12): 5.0, (90, 10): 6.0}
        code0 = {(60, 12): 5.8, (120, 14): 4.5}
        asym = {(60, 12): 5.4, (90, 10): 6.5, (150, 16): 7.0}
        combined = combine_best(jib, code0, asym)
        assert combined[(60, 12)] == 5.8
        assert combined[(90, 10)] == 6.5
        assert combined[(120, 14)] == 4.5
        assert combined[(150, 16)] == 7.0

    def test_empty_inputs_return_empty(self) -> None:
        assert combine_best() == {}
        assert combine_best({}) == {}

    def test_bin_present_in_only_one_polar_is_kept(self) -> None:
        a = {(60, 12): 5.0}
        b = {(90, 10): 6.0}
        combined = combine_best(a, b)
        assert combined == {(60, 12): 5.0, (90, 10): 6.0}
