"""Convert Signal K server raw logs (N2K CAN data) to PolarPrism sailing log format.

This module is the generic, reusable core of the raw-log conversion. It reads
raw log files produced by the Signal K server's `skserver-raw` recorder,
decodes N2K PGNs using the `nmea2000` library, maps them to Signal K paths,
and produces sailing log JSONL files in the same format as PolarPrism's
performance logger.

Raw log file format (one entry per line):

    <unix_ms>;<provider>;<payload>

where `<provider>` is `A` (NMEA 2000 ASCII-hex frame) or `course-provider`
(a Signal K delta JSON object), and `<payload>` is either the comma-separated
N2K frame fields or the JSON delta respectively. Raw log filenames follow the
convention `skserver-raw_YYYY-MM-DDTHH.log` and use **local time** of the
recorder; the caller supplies the UTC offset so file filtering can be done in
UTC.

Used by:
  - `main.py` on startup, when `[logging] auto_convert_raw = true`, to import
    any new raw logs found in `logs/raw/` automatically.
  - `log_analysis.py convert`, a CLI front-end for manual one-off conversions.
"""

from __future__ import annotations

import glob
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from nmea2000 import NMEA2000Decoder

from polars.parser import compute_true_wind, discover_polars, lookup_speed
from signalk.models import (
    MS_TO_KNOTS,
    PATH_MAP,
    derive_true_heading_from_values,
    rad_to_deg,
)

logger = logging.getLogger("polarprism")

# N2K PGN -> short Signal K key (matching keys in PATH_MAP / State.values).
# 127237 (headingOrder) is tracked for source counts but emits no values.
PGN_SK_MAP: dict[int, str] = {
    127250: "heading",
    127251: "rateOfTurn",
    127257: "attitude",
    127245: "rudder",
    127258: "magneticVariation",
    128259: "speed",
    129026: "cogSog",
    129029: "position",
    130306: "wind",
    65359: "seatalkHeading",
    65360: "seatalkPilotHeading",
    127237: "headingOrder",
}

# Output sampling interval. The raw log may have many frames per second; we
# emit one sailing-log entry per second of consolidated state.
OUTPUT_INTERVAL_MS = 1000

RAW_LOG_GLOB = "skserver-raw_*.log"
RAW_LOG_DATE_FORMAT = "%Y-%m-%dT%H"


def parse_raw_line(line: str, decoder: NMEA2000Decoder) -> tuple[int, dict[str, Any]] | None:
    """Parse a single raw log line; return (timestamp_ms, updates) or None.

    `updates` maps Signal K short keys (matching PATH_MAP) to values, and
    uses the key ``"position"`` for a ``{"lat", "lon"}`` dict.
    """
    line = line.strip()
    if not line:
        return None

    parts = line.split(";", 2)
    if len(parts) < 2:
        return None

    ts_ms = int(parts[0])
    provider = parts[1]

    if provider == "A":
        if len(parts) < 3:
            return None
        data_str = parts[2]
        data_parts = data_str.split(",", 5)
        if len(data_parts) < 6:
            return None
        try:
            pgn = int(data_parts[2])
        except ValueError:
            return None
        sk_key = PGN_SK_MAP.get(pgn)
        if sk_key is None:
            return None

        try:
            is_fast = decoder.is_fast_pgn(pgn)
            msg = decoder.decode_basic_string(data_str, already_combined=is_fast)
        except Exception:
            logger.debug("failed to decode PGN %s frame", pgn, exc_info=True)
            return None

        if msg is None:
            return None

        updates: dict[str, Any] = _extract_pgn_values(msg, sk_key)
        return (ts_ms, updates) if updates else None

    if provider == "course-provider":
        if len(parts) < 3:
            return None
        try:
            delta = json.loads(parts[2])
        except json.JSONDecodeError:
            return None

        updates = {}
        for update in delta.get("updates", []):
            for item in update.get("values", []):
                path = item.get("path", "")
                val = item.get("value")
                if val is None:
                    continue
                for key, sk_path in PATH_MAP.items():
                    if path == sk_path:
                        updates[key] = val
                        break
        return (ts_ms, updates) if updates else None

    return None


def _extract_pgn_values(msg: Any, sk_key: str) -> dict[str, Any]:
    """Extract relevant Signal K values from a decoded N2K message."""
    updates: dict[str, Any] = {}

    if sk_key == "heading":
        ref = None
        for f in msg.fields:
            if f.id == "reference" and f.value is not None:
                ref = str(f.value)
        for f in msg.fields:
            if f.id == "heading" and f.value is not None:
                if ref == "True":
                    updates["headingTrue"] = f.value
                else:
                    updates["headingMagnetic"] = f.value

    elif sk_key == "rateOfTurn":
        for f in msg.fields:
            if f.id == "rate" and f.value is not None:
                updates["rateOfTurn"] = f.value

    elif sk_key == "attitude":
        for f in msg.fields:
            if f.id == "roll" and f.value is not None:
                updates["roll"] = f.value
            elif f.id == "pitch" and f.value is not None:
                updates["pitch"] = f.value
            elif f.id == "yaw" and f.value is not None:
                updates["yaw"] = f.value

    elif sk_key == "rudder":
        for f in msg.fields:
            if f.id == "position" and f.value is not None:
                updates["rudderAngle"] = f.value

    elif sk_key == "magneticVariation":
        for f in msg.fields:
            if f.id == "variation" and f.value is not None:
                updates["magneticVariation"] = f.value

    elif sk_key == "speed":
        for f in msg.fields:
            if f.id == "speedWaterReferenced" and f.value is not None:
                updates["speedThroughWater"] = f.value

    elif sk_key == "cogSog":
        for f in msg.fields:
            if f.id == "cog" and f.value is not None:
                updates["cogTrue"] = f.value
            elif f.id == "sog" and f.value is not None:
                updates["speedOverGround"] = f.value

    elif sk_key == "position":
        lat = lon = None
        for f in msg.fields:
            if f.id == "latitude" and f.value is not None:
                lat = f.value
            elif f.id == "longitude" and f.value is not None:
                lon = f.value
        if lat is not None or lon is not None:
            pos: dict[str, float] = {}
            if lat is not None:
                pos["lat"] = lat
            if lon is not None:
                pos["lon"] = lon
            updates["position"] = pos

    elif sk_key == "wind":
        ref = None
        for f in msg.fields:
            if f.id == "reference" and f.value is not None:
                ref = str(f.value)
        for f in msg.fields:
            if f.id == "windAngle" and f.value is not None:
                if ref == "True":
                    updates["windAngleTrue"] = f.value
                else:
                    updates["windAngleApparent"] = f.value
            elif f.id == "windSpeed" and f.value is not None:
                if ref == "True":
                    updates["windSpeedTrue"] = f.value
                else:
                    updates["windSpeedApparent"] = f.value

    elif sk_key == "seatalkHeading":
        for f in msg.fields:
            if (
                f.id == "headingMagnetic"
                and f.value is not None
                and "headingMagnetic" not in updates
            ):
                updates["headingMagnetic"] = f.value

    elif sk_key == "seatalkPilotHeading":
        for f in msg.fields:
            if f.id == "targetHeadingMagnetic" and f.value is not None:
                updates["apTargetMagnetic"] = f.value

    return updates


def load_raw_lines(
    raw_dir: str, start_utc: datetime, end_utc: datetime, local_tz_offset_hours: float
) -> list[tuple[int, str]]:
    """Load and sort all raw log lines within the given UTC time range.

    Raw log filenames use the recorder's local time. ``local_tz_offset_hours``
    (e.g. -4 for EDT, +1 for CET) is used to convert the filename hour into UTC
    so files can be filtered before reading.
    """
    all_files = sorted(glob.glob(os.path.join(raw_dir, RAW_LOG_GLOB)))
    lines: list[tuple[int, str]] = []
    offset = timedelta(hours=local_tz_offset_hours)

    for fpath in all_files:
        basename = os.path.basename(fpath)
        try:
            date_hour = basename.replace("skserver-raw_", "").replace(".log", "")
            file_dt = datetime.strptime(date_hour, RAW_LOG_DATE_FORMAT)
        except ValueError:
            logger.debug("skipping non-raw-log file: %s", basename)
            continue

        # Filename is local time; add the offset to get UTC.
        file_start_utc = file_dt.replace(tzinfo=timezone.utc) - offset
        file_end_utc = file_start_utc + timedelta(hours=1)

        if file_end_utc <= start_utc or file_start_utc >= end_utc:
            continue

        try:
            with open(fpath) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    semi = line.find(";")
                    if semi < 0:
                        continue
                    try:
                        ts_ms = int(line[:semi])
                    except ValueError:
                        continue
                    ts_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                    if ts_utc < start_utc or ts_utc >= end_utc:
                        continue
                    lines.append((ts_ms, line))
        except OSError:
            logger.warning("could not read raw log file: %s", fpath, exc_info=True)

    lines.sort(key=lambda x: x[0])
    return lines


def build_sailing_entry(
    ts_ms: int,
    values: dict[str, Any],
    position: dict[str, float | None],
    polar: Any | None,
    polar_name: str | None,
) -> dict[str, Any]:
    """Build a single sailing-log JSONL entry from current consolidated state."""
    ts_dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)

    awa_rad = values.get("windAngleApparent")
    aws_ms = values.get("windSpeedApparent")
    stw_ms = values.get("speedThroughWater")
    sog_ms = values.get("speedOverGround")
    cog_rad = values.get("cogTrue")

    ht_val = derive_true_heading_from_values(values, 0.0)
    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)

    twa_deg = math.degrees(twa_rad) if twa_rad is not None else None
    tws_kts = tws_ms * MS_TO_KNOTS if tws_ms is not None else None
    awa_deg = math.degrees(awa_rad) if awa_rad is not None else None
    aws_kts = aws_ms * MS_TO_KNOTS if aws_ms is not None else None
    stw_kts = stw_ms * MS_TO_KNOTS if stw_ms is not None else None
    sog_kts = sog_ms * MS_TO_KNOTS if sog_ms is not None else None

    ht_deg = rad_to_deg(ht_val) if ht_val is not None else None
    cog_deg = rad_to_deg(cog_rad) if cog_rad is not None else None

    twd_deg = None
    if ht_deg is not None and twa_deg is not None:
        twd_deg = (ht_deg + twa_deg) % 360

    polar_target = None
    polar_perf = None
    if twa_deg is not None and tws_kts is not None and polar is not None:
        polar_target = lookup_speed(polar, abs(twa_deg), tws_kts)
        if polar_target is not None and polar_target > 0 and stw_kts is not None:
            polar_perf = stw_kts / polar_target * 100.0

    return {
        "ts": ts_dt.isoformat(),
        "position": {
            "lat": position.get("lat"),
            "lon": position.get("lon"),
        },
        "headingTrue": round(ht_deg, 1) if ht_deg is not None else None,
        "cogTrue": round(cog_deg, 1) if cog_deg is not None else None,
        "sog": round(sog_kts, 2) if sog_kts is not None else None,
        "stw": round(stw_kts, 2) if stw_kts is not None else None,
        "twa": round(twa_deg, 1) if twa_deg is not None else None,
        "tws": round(tws_kts, 1) if tws_kts is not None else None,
        "twd": round(twd_deg, 1) if twd_deg is not None else None,
        "awa": round(awa_deg, 1) if awa_deg is not None else None,
        "aws": round(aws_kts, 1) if aws_kts is not None else None,
        "sailing_state": "sailing",
        "active_sails": [],
        "polar_name": polar_name or "",
        "polar_target_speed": round(polar_target, 2) if polar_target is not None else None,
        "polar_performance_pct": round(polar_perf, 1) if polar_perf is not None else None,
    }


def convert_raw_to_sailing_log(
    raw_path: str,
    output_dir: str,
    local_tz_offset_hours: float,
    polar_name: str | None = None,
    polars_dir: str | None = None,
    *,
    full_range: bool = True,
    start_local: str | None = None,
    end_local: str | None = None,
    date_str: str | None = None,
) -> str | None:
    """Convert a single raw log file (or a time-bounded slice of it) to JSONL.

    Returns the path of the written ``sailing_*.jsonl`` file, or None if no
    entries were produced.

    When ``full_range`` is True (the default, used by the startup auto-import),
    the entire raw file is converted and the output filename is derived from
    the first entry's timestamp. When False, ``start_local``/``end_local``/
    ``date_str`` (HH:MM / HH:MM / YYYY-MM-DD in recorder local time) define the
    slice — used by the manual CLI.
    """
    if full_range:
        # Derive the UTC span from the file's own filename hour, covering the
        # full hour. Lines outside the file's span are naturally filtered by
        # having no matching range only if start==end; instead we read all
        # lines by using a generous window around the file hour.
        basename = os.path.basename(raw_path)
        try:
            date_hour = basename.replace("skserver-raw_", "").replace(".log", "")
            file_dt = datetime.strptime(date_hour, RAW_LOG_DATE_FORMAT)
        except ValueError:
            logger.warning("unrecognized raw log filename: %s", basename)
            return None
        offset = timedelta(hours=local_tz_offset_hours)
        # Filename is local; UTC start = local - offset. Cover a generous 2h
        # window to catch any straddling entries.
        start_utc = (file_dt.replace(tzinfo=timezone.utc) - offset) - timedelta(minutes=5)
        end_utc = start_utc + timedelta(hours=2, minutes=10)
    else:
        if not (start_local and end_local and date_str):
            raise ValueError(
                "start_local, end_local, and date_str are required when full_range=False"
            )
        local_tz = timezone(timedelta(hours=local_tz_offset_hours))
        date_dt = datetime.strptime(date_str, "%Y-%m-%d")
        start_utc = datetime.combine(
            date_dt, datetime.strptime(start_local, "%H:%M").time(), tzinfo=local_tz
        ).astimezone(timezone.utc)
        end_utc = datetime.combine(
            date_dt, datetime.strptime(end_local, "%H:%M").time(), tzinfo=local_tz
        ).astimezone(timezone.utc)

    lines = _read_single_file(raw_path, start_utc, end_utc)

    if not lines:
        logger.info("no raw entries in %s for the requested range", raw_path)
        return None

    decoder = NMEA2000Decoder()
    values: dict[str, Any] = {}
    position: dict[str, float | None] = {"lat": None, "lon": None}
    last_output_ts: int | None = None
    entries: list[dict[str, Any]] = []

    polars_dir = polars_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "polars"
    )
    polars = discover_polars(polars_dir)
    polar_data = {p.name: p for p in polars}
    if not polar_name and polars:
        polar_name = polars[0].name
    polar = polar_data.get(polar_name) if polar_name else None
    if polar:
        logger.info("using polar: %s", polar_name)
    else:
        logger.info("no polar data available; polar fields will be None")

    source_counts: dict[str, int] = {}

    for ts_ms, line in lines:
        result = parse_raw_line(line, decoder)
        if result is None:
            continue
        _ts, updates = result
        source = line.split(";", 2)[1] if ";" in line else "?"
        source_counts[source] = source_counts.get(source, 0) + 1

        for key, val in updates.items():
            if key == "position" and isinstance(val, dict):
                if "lat" in val:
                    position["lat"] = val["lat"]
                if "lon" in val:
                    position["lon"] = val["lon"]
            else:
                values[key] = val

        if last_output_ts is None:
            last_output_ts = ts_ms - OUTPUT_INTERVAL_MS

        if ts_ms - last_output_ts >= OUTPUT_INTERVAL_MS:
            entry = build_sailing_entry(ts_ms, values, position, polar, polar_name)
            entries.append(entry)
            last_output_ts = ts_ms

    if not entries:
        logger.info("no sailing-log entries generated from %s", raw_path)
        return None

    os.makedirs(output_dir, exist_ok=True)
    first_ts = entries[0]["ts"]
    fname = f"sailing_{first_ts.replace('-', '').replace(':', '').replace('T', '_').split('.')[0]}.jsonl"
    outpath = os.path.join(output_dir, fname)

    with open(outpath, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    logger.info("wrote %d entries to %s (sources=%s)", len(entries), outpath, source_counts)
    return outpath


def _read_single_file(
    raw_path: str, start_utc: datetime, end_utc: datetime
) -> list[tuple[int, str]]:
    """Read one raw log file and return sorted (ts_ms, line) tuples in range."""
    lines: list[tuple[int, str]] = []
    try:
        with open(raw_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                semi = line.find(";")
                if semi < 0:
                    continue
                try:
                    ts_ms = int(line[:semi])
                except ValueError:
                    continue
                ts_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                if ts_utc < start_utc or ts_utc >= end_utc:
                    continue
                lines.append((ts_ms, line))
    except OSError:
        logger.warning("could not read raw log file: %s", raw_path, exc_info=True)
    lines.sort(key=lambda x: x[0])
    return lines


def auto_convert_raw_dir(
    raw_dir: str, output_dir: str, local_tz_offset_hours: float, polars_dir: str | None = None
) -> list[str]:
    """Auto-convert every raw log in ``raw_dir`` not already converted.

    Skips a raw file if a sailing log JSONL whose name is derived from the
    raw file's date/hour already exists in ``output_dir``. Returns the list of
    output JSONL paths produced this run (empty if nothing new to convert).
    Never raises — logs and continues on per-file errors.
    """
    if not os.path.isdir(raw_dir):
        return []

    raw_files = sorted(glob.glob(os.path.join(raw_dir, RAW_LOG_GLOB)))
    produced: list[str] = []

    for raw_path in raw_files:
        basename = os.path.basename(raw_path)
        try:
            date_hour = basename.replace("skserver-raw_", "").replace(".log", "")
            file_dt = datetime.strptime(date_hour, RAW_LOG_DATE_FORMAT)
        except ValueError:
            logger.debug("skipping non-raw-log file: %s", basename)
            continue

        # Skip if any output JSONL for this date/hour already exists. The
        # converter derives the output name from the first entry's timestamp,
        # so we approximate by checking for any sailing_*.jsonl starting with
        # the file's UTC-derived date/hour.
        offset = timedelta(hours=local_tz_offset_hours)
        utc_hour = file_dt.replace(tzinfo=timezone.utc) - offset
        expected_prefix = utc_hour.strftime("sailing_%Y%m%d_%H")
        if _output_exists(output_dir, expected_prefix):
            logger.debug("already converted, skipping: %s", basename)
            continue

        try:
            outpath = convert_raw_to_sailing_log(
                raw_path,
                output_dir,
                local_tz_offset_hours,
                polar_name=None,
                polars_dir=polars_dir,
                full_range=True,
            )
            if outpath:
                produced.append(outpath)
        except Exception:
            logger.warning("failed to convert %s", raw_path, exc_info=True)

    return produced


def _output_exists(output_dir: str, prefix: str) -> bool:
    """True if any file in output_dir starts with the given prefix."""
    if not os.path.isdir(output_dir):
        return False
    return any(name.startswith(prefix) for name in os.listdir(output_dir))
