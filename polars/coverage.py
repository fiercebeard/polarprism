"""Coverage binning for the Polar Builder page.

Single source of truth for converting (AWA, AWS, STW) samples into a
(TWA, TWS) polar grid and aggregating observed boat speeds per bin.

Constants and the binning grid match `log_analysis.py`'s measured-polar
pipeline so the live builder and the offline CLI stay consistent.
"""

from __future__ import annotations

import json
import math
import os

from polars.parser import compute_true_wind
from signalk.models import MS_TO_KNOTS

# --- coverage grid constants (single source of truth; log_analysis re-uses) --
MIN_STW_KTS = 2.0
MIN_AWS_KTS = 4.0
TWA_BIN_DEG = 5
TWS_BIN_KTS = 2
TWA_MIN_DEG = 30
TWA_MAX_DEG = 180
TWS_MIN_KTS = 6
TWS_MAX_KTS = 30
MIN_SAMPLES_PER_BIN = 3

DEFAULT_TWS_STEPS = [6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30]
DEFAULT_TWA_STEPS = list(range(30, 181, 2))

BinKey = tuple[int, int]
Coverage = dict[BinKey, list[float]]


def bin_sample(awa_rad: float, aws_ms: float, stw_ms: float) -> tuple[int, int, float] | None:
    """Convert one apparent-wind sample into a coverage bin key + STW.

    Returns ``(twa_bin_deg, tws_bin_kts, stw_kts)`` or ``None`` if the sample
    is filtered out (too slow, too little wind, or out of grid range).
    """
    stw_kts = stw_ms * MS_TO_KNOTS
    aws_kts = aws_ms * MS_TO_KNOTS
    if stw_kts < MIN_STW_KTS or aws_kts < MIN_AWS_KTS:
        return None

    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)
    if twa_rad is None or tws_ms is None:
        return None

    twa_deg = abs(math.degrees(twa_rad))
    if twa_deg > 180:
        twa_deg = 360 - twa_deg
    tws_kts = tws_ms * MS_TO_KNOTS

    twa_bin = round(twa_deg / TWA_BIN_DEG) * TWA_BIN_DEG
    tws_bin = round(tws_kts / TWS_BIN_KTS) * TWS_BIN_KTS
    if twa_bin < TWA_MIN_DEG or twa_bin > TWA_MAX_DEG:
        return None
    if tws_bin < TWS_MIN_KTS or tws_bin > TWS_MAX_KTS:
        return None
    return twa_bin, tws_bin, stw_kts


def _bin_from_entry(entry: dict) -> tuple[int, int, float] | None:
    """Extract a coverage bin from a sailing-log JSONL entry."""
    awa = entry.get("awa")
    aws = entry.get("aws")
    stw = entry.get("stw")
    if awa is None or aws is None or stw is None:
        return None
    awa_norm = awa if awa <= 180 else awa - 360
    return bin_sample(math.radians(awa_norm), aws / MS_TO_KNOTS, stw / MS_TO_KNOTS)


def build_coverage_from_session(path: str) -> Coverage:
    """Read a sailing-log JSONL file and return bin -> list of STW samples."""
    coverage: Coverage = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "event" in entry:
                    continue
                binned = _bin_from_entry(entry)
                if binned is None:
                    continue
                twa_bin, tws_bin, stw_kts = binned
                coverage.setdefault((twa_bin, tws_bin), []).append(stw_kts)
    except OSError:
        return {}
    return coverage


def merge_coverage(*coverages: Coverage) -> Coverage:
    """Merge multiple coverage dicts into one, concatenating sample lists."""
    merged: Coverage = {}
    for cov in coverages:
        for key, speeds in cov.items():
            merged.setdefault(key, []).extend(speeds)
    return merged


def build_coverage_from_sessions(paths: list[str]) -> Coverage:
    """Build merged coverage from multiple sailing-log files."""
    return merge_coverage(*[build_coverage_from_session(p) for p in paths if p])


# --- coverage sidecar (accumulation state for measured polars) ---------------
COVERAGE_SUFFIX = ".cov.json"


def _cov_path_for(csv_path: str) -> str:
    """Return the sidecar coverage path paired with a measured polar CSV path."""
    return os.path.splitext(csv_path)[0] + COVERAGE_SUFFIX


def save_coverage_sidecar(coverage: Coverage, csv_path: str) -> str:
    """Write the coverage dict (raw binned sample lists) to the sidecar next to
    ``csv_path``. Keys are written as ``"twa,tws"`` strings (JSON object keys
    must be strings); sample lists are JSON arrays of floats.

    Returns the sidecar path.
    """
    side = _cov_path_for(csv_path)
    payload = {f"{twa},{tws}": speeds for (twa, tws), speeds in coverage.items()}
    tmp = side + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, side)
    return side


def load_coverage_sidecar(csv_path: str) -> Coverage:
    """Read the coverage sidecar paired with ``csv_path``.

    Returns an empty Coverage dict when the sidecar is missing or unreadable
    (treated as "no prior accumulation state" — start fresh).
    """
    side = _cov_path_for(csv_path)
    try:
        with open(side) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    coverage: Coverage = {}
    for key, speeds in payload.items():
        try:
            twa_s, tws_s = key.split(",")
            twa = int(twa_s)
            tws = int(tws_s)
        except ValueError:
            continue
        if not isinstance(speeds, list):
            continue
        coverage[(twa, tws)] = [float(s) for s in speeds]
    return coverage


def coverage_mean(
    coverage: Coverage, min_samples: int = MIN_SAMPLES_PER_BIN
) -> dict[BinKey, float]:
    """Reduce coverage to mean STW per bin, dropping bins below ``min_samples``."""
    return {
        key: sum(speeds) / len(speeds)
        for key, speeds in coverage.items()
        if len(speeds) >= min_samples
    }


def coverage_counts(coverage: Coverage) -> dict[BinKey, int]:
    """Return sample count per bin (no minimum filtering)."""
    return {key: len(speeds) for key, speeds in coverage.items()}


def read_measured_polar_csv(csv_path: str) -> dict[BinKey, float]:
    """Read a measured-polar CSV (PolarPrism format) back into a measured dict.

    Inverse of ``log_analysis.write_polar_csv``: parses the ``TWA\\TWS`` header
    and each row, returning ``(twa, tws) -> STW`` for non-empty cells. Empty
    cells are skipped. Used by the combine-best envelope operation.
    """
    measured: dict[BinKey, float] = {}
    try:
        with open(csv_path) as f:
            lines = [line.strip() for line in f if line.strip()]
    except OSError:
        return measured
    if not lines:
        return measured

    header = lines[0]
    sep = ";" if ";" in header else ","
    tws_steps = [float(v) for v in header.split(sep)[1:]]

    for line in lines[1:]:
        parts = line.split(sep)
        if len(parts) < 2:
            continue
        try:
            twa = int(float(parts[0]))
        except ValueError:
            continue
        for i, cell in enumerate(parts[1:]):
            if i >= len(tws_steps) or cell == "":
                continue
            try:
                measured[(twa, int(tws_steps[i]))] = float(cell)
            except ValueError:
                continue
    return measured


def combine_best(*measured_dicts: dict[BinKey, float]) -> dict[BinKey, float]:
    """Envelope (max STW) across multiple measured polar dicts.

    For each bin present in any input, returns the maximum STW across all
    inputs — i.e. the fastest achievable speed at that (TWA, TWS) point given
    the set of measured polars (e.g. jib + code0 + asym). Bins absent from all
    inputs are absent from the output.
    """
    combined: dict[BinKey, float] = {}
    for md in measured_dicts:
        for key, speed in md.items():
            prev = combined.get(key)
            if prev is None or speed > prev:
                combined[key] = speed
    return combined


def interpolate_measured(measured: dict[BinKey, float], twa: float, tws: float) -> float | None:
    """Inverse-distance-weighted interpolation of measured polar data."""
    twa_bin = round(twa / TWA_BIN_DEG) * TWA_BIN_DEG
    tws_bin = round(tws / TWS_BIN_KTS) * TWS_BIN_KTS

    direct = measured.get((twa_bin, tws_bin))
    if direct is not None:
        return direct

    nearby: list[tuple[int, int, float]] = []
    for dt in (-TWA_BIN_DEG, 0, TWA_BIN_DEG):
        for dw in (-TWS_BIN_KTS, 0, TWS_BIN_KTS):
            key = (twa_bin + dt, tws_bin + dw)
            if key in measured:
                nearby.append((twa_bin + dt, tws_bin + dw, measured[key]))

    if len(nearby) >= 3:
        total_weight = 0.0
        weighted_speed = 0.0
        for t, w, s in nearby:
            dist = math.sqrt((t - twa) ** 2 + (w - tws) ** 2)
            weight = 1.0 / max(dist, 0.1)
            total_weight += weight
            weighted_speed += s * weight
        return weighted_speed / total_weight if total_weight > 0 else None

    return None


def _session_meta(path: str) -> tuple[str | None, tuple[str, ...]]:
    """Read a sailing-log JSONL's polar name + active-sails combo from its
    first non-event sample (or log_start event). Returns ``(polar, sails)``.
    """
    polar: str | None = None
    sails: tuple[str, ...] = ()
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("event") == "log_start":
                    p = entry.get("polar")
                    s = entry.get("active_sails")
                    if isinstance(p, str) and isinstance(s, list):
                        return p, tuple(sorted(str(x) for x in s))
                    continue
                # first data sample
                p = entry.get("polar_name")
                s = entry.get("active_sails")
                if isinstance(p, str) and isinstance(s, list):
                    return p, tuple(sorted(str(x) for x in s))
                # fall through to next line if incomplete
    except OSError:
        pass
    return polar, sails


def seed_groups_from_logs(log_dir: str, polar_names: list[str]) -> list[dict]:
    """Auto-build starter Polar Builder groups from on-disk sailing logs.

    Scans ``log_dir`` for ``sailing_*.jsonl``, groups them by the
    ``(polar_name, active_sails)`` combo recorded in each file's first
    sample, and returns a list of group dicts:
        ``{"name": str, "polar": str, "sessions": list[str]}``
    Groups whose polar is not in ``polar_names`` still get created (the user
    may rename/re-target later); ``polar`` defaults to the first known polar.
    """
    try:
        files = sorted(
            f for f in os.listdir(log_dir) if f.startswith("sailing_") and f.endswith(".jsonl")
        )
    except OSError:
        return []
    if not files:
        return []

    fallback_polar = polar_names[0] if polar_names else ""
    buckets: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for fname in files:
        fpath = os.path.join(log_dir, fname)
        polar, sails = _session_meta(fpath)
        if polar is None:
            polar = fallback_polar
        buckets.setdefault((polar, sails), []).append(fpath)

    groups: list[dict] = []
    for (polar, sails), sessions in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        name = polar + " / " + " + ".join(sails) if sails else polar
        groups.append({"name": name, "polar": polar, "sessions": sessions})
    return groups
