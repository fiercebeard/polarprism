#!/usr/bin/env python3
"""PolarPrism sailing-log analysis CLI.

Two subcommands form a pipeline that starts from a raw Signal K server log and
ends with a measured polar you can compare to a theoretical polar:

    raw log (skserver-raw_*.log)
        |
        |  convert   (decodes N2K PGNs via signalk.rawlog)
        v
    sailing log (sailing_*.jsonl, one JSON entry per sample)
        |
        |  polar     (bins (TWA, TWS, STW) into a polar grid)
        v
    measured polar CSV (+ optional matplotlib comparison plot)

This is a general tool. There are no boat-specific defaults — supply paths,
polar names, timezone offset, and time windows explicitly.

## `convert` — raw log -> sailing log

Used by `main.py` on startup when `[logging] auto_convert_raw = true`; this
subcommand is the manual front-end for one-off conversions with a specific
time range or for forcing re-conversion.

Raw log filenames use the recorder's local time, so pass your UTC offset with
`--tz-offset` (e.g. `-4` for EDT, `+1` for CET). There are no baked-in
defaults for date, time range, or timezone — supply them explicitly.

    python log_analysis.py convert --date 2026-06-05 \\
        --start 05:40 --end 18:30 --tz-offset -4 \\
        --raw-dir logs/raw --output-dir sailing_logs

    # Convert the entire span of every file in a directory:
    python log_analysis.py convert --raw-dir logs/raw --tz-offset -4 --full-range

## `polar` — sailing log -> measured polar

Feed it any sailing log produced by PolarPrism (or by `convert`) and it will
bin observed (TWA, TWS, STW) samples into a polar grid. Each run **accumulates**
into the target measured polar: raw binned samples are kept in a sidecar
`<name>.cov.json` next to the CSV, and bin means are recomputed across all
accumulated sessions — so the polar gets richer as you sail more.

Target selection (first match wins):
  1. `--measured-name X` → `X.csv` (created if absent, else accumulated into).
  2. Most-recently-modified `*.csv` in the output dir (accumulate into it —
     rename it and you keep building that same polar under its new name).
  3. `auto_polar_<YYYYMMDD>` derived from the sailing log filename (fresh start).

    python log_analysis.py polar [--input INPUT.jsonl] \\
        [--output-dir DIR] [--polars-dir DIR] [--comparison-polar NAME.csv] \\
        [--measured-name NAME]

## `polar --combine-best` — envelope across measured polars

Produce a best-performance polar (max STW per bin) from several measured polar
CSVs — e.g. separate jib / code0 / asym polars combined for a race:

    python log_analysis.py polar --combine-best jib.csv code0.csv asym.csv \\
        --measured-name race_best
"""

from __future__ import annotations

import argparse
import datetime as _dt
import itertools
import json
import logging
import math
import os
import re
import sys
from typing import Any

from boatpolars.coverage import (
    DEFAULT_TWA_STEPS,
    DEFAULT_TWS_STEPS,
    TWA_BIN_DEG,
    TWS_BIN_KTS,
    combine_best,
    coverage_mean,
    interpolate_measured,
    load_coverage_sidecar,
    merge_coverage,
    read_measured_polar_csv,
    save_coverage_sidecar,
)
from boatpolars.parser import discover_polars, load_polar, lookup_speed
from signalk.rawlog import convert_raw_to_sailing_log

logger = logging.getLogger("polarprism")


# --- `convert` subcommand --------------------------------------------------
def _run_convert(args: argparse.Namespace, basedir: str) -> int:
    raw_dir = args.raw_dir or os.path.join(basedir, "logs", "raw")
    output_dir = args.output_dir or os.path.join(basedir, "sailing_logs")

    full_range = args.full_range or not (args.start and args.end and args.date)
    if not full_range and not (args.start and args.end and args.date):
        print(
            "--start, --end, and --date are required unless --full-range is given", file=sys.stderr
        )
        return 2

    if args.raw_file:
        files = [args.raw_file]
    else:
        if not os.path.isdir(raw_dir):
            print(f"Raw log directory not found: {raw_dir}", file=sys.stderr)
            return 1
        import glob

        files = sorted(glob.glob(os.path.join(raw_dir, "skserver-raw_*.log")))

    if not files:
        print("No skserver-raw_*.log files found.", file=sys.stderr)
        return 1

    produced = []
    for raw_path in files:
        try:
            outpath = convert_raw_to_sailing_log(
                raw_path=raw_path,
                output_dir=output_dir,
                local_tz_offset_hours=args.tz_offset,
                polar_name=args.polar,
                polars_dir=os.path.join(basedir, "polars"),
                full_range=full_range,
                start_local=args.start,
                end_local=args.end,
                date_str=args.date,
            )
            if outpath:
                produced.append(outpath)
                print(f"Wrote {outpath}")
            else:
                print(f"No entries from {raw_path}")
        except Exception as exc:
            print(f"Failed to convert {raw_path}: {exc}", file=sys.stderr)

    print(f"Done. {len(produced)} file(s) written to {output_dir}")
    return 0


def _add_convert_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "convert",
        help="Convert Signal K raw logs to PolarPrism sailing log format",
        description="Convert Signal K raw logs (N2K CAN data) to PolarPrism sailing log JSONL.",
    )
    p.add_argument(
        "--raw-dir",
        default=None,
        help="Directory containing skserver-raw_*.log files (default: logs/raw/)",
    )
    p.add_argument(
        "--raw-file",
        default=None,
        help="Convert a single raw log file instead of a directory",
    )
    p.add_argument("--output-dir", default=None, help="Output directory (default: sailing_logs/)")
    p.add_argument("--polar", default=None, help="Polar name to use (default: first available)")
    p.add_argument(
        "--tz-offset",
        type=float,
        default=0.0,
        help="Local timezone UTC offset in hours (e.g. -4 for EDT, +1 for CET). "
        "Required when raw filenames use local time.",
    )

    time_group = p.add_argument_group("time-bounded conversion")
    time_group.add_argument("--start", default=None, help="Start time (local, HH:MM)")
    time_group.add_argument("--end", default=None, help="End time (local, HH:MM)")
    time_group.add_argument("--date", default=None, help="Date (YYYY-MM-DD)")
    time_group.add_argument(
        "--full-range",
        action="store_true",
        help="Convert the full span of each raw file (ignores --start/--end/--date)",
    )
    p.set_defaults(func=_run_convert)


# --- `polar` subcommand ----------------------------------------------------
def write_polar_csv(
    measured: dict[tuple[int, int], float],
    output_path: str,
    twa_steps: list[int] | None = None,
    tws_steps: list[int] | None = None,
) -> None:
    """Write measured polar data to CSV in PolarPrism format."""
    if twa_steps is None:
        twa_steps = DEFAULT_TWA_STEPS
    if tws_steps is None:
        tws_steps = DEFAULT_TWS_STEPS

    header = "TWA\\TWS;" + ";".join(f"{t:.0f}" for t in tws_steps)
    lines = [header]

    for twa in twa_steps:
        parts = [f"{twa}"]
        for tws in tws_steps:
            key = (twa, tws)
            if key in measured:
                parts.append(f"{measured[key]:.2f}")
            else:
                speed = interpolate_measured(measured, twa, tws)
                if speed is not None:
                    parts.append(f"{speed:.6f}")
                else:
                    parts.append("")
        lines.append(";".join(parts))

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def generate_comparison_image(
    measured: dict[tuple[int, int], float],
    comparison_polar: Any | None,
    comparison_label: str,
    output_path: str,
) -> None:
    """Generate a side-by-side polar comparison image (requires matplotlib)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    tws_values = [6, 8, 10, 12, 14, 16, 20, 24]
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, len(tws_values)))

    fig, axes = plt.subplots(1, 2, figsize=(20, 9), subplot_kw={"projection": "polar"})
    fig.suptitle(
        f"Polar Comparison: Measured vs Theoretical ({comparison_label})",
        fontsize=16,
        fontweight="bold",
    )

    for ax_idx, (ax, title) in enumerate(
        zip(axes, ["Measured", f"Theoretical - {comparison_label}"], strict=False)
    ):
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_title(title, pad=20, fontsize=14, fontweight="bold")

        speed_max = 0.0
        for i, tws_kts in enumerate(tws_values):
            angles_measured: list[float] = []
            speeds_measured: list[float] = []
            angles_theory: list[float] = []
            speeds_theory: list[float] = []

            for twa in np.arange(1, 181, 1):
                twa_bin = round(twa / TWA_BIN_DEG) * TWA_BIN_DEG

                if ax_idx == 0:
                    key = (twa_bin, round(tws_kts / TWS_BIN_KTS) * TWS_BIN_KTS)
                    if key in measured:
                        speed = measured[key]
                        angles_measured.append(math.radians(twa))
                        speeds_measured.append(speed)
                        speed_max = max(speed_max, speed)

                if ax_idx == 1 and comparison_polar:
                    speed = lookup_speed(comparison_polar, twa, tws_kts)
                    if speed and speed > 0:
                        angles_theory.append(math.radians(twa))
                        speeds_theory.append(speed)
                        speed_max = max(speed_max, speed)

            if ax_idx == 0 and angles_measured:
                ax.plot(
                    angles_measured,
                    speeds_measured,
                    "-",
                    color=colors[i],
                    linewidth=1.5,
                    label=f"{tws_kts:.0f} kt TWS",
                    alpha=0.8,
                )
                ax.plot(
                    angles_measured, speeds_measured, "o", color=colors[i], markersize=2, alpha=0.5
                )
            elif ax_idx == 1 and angles_theory:
                ax.plot(
                    angles_theory,
                    speeds_theory,
                    "-",
                    color=colors[i],
                    linewidth=2,
                    label=f"{tws_kts:.0f} kt TWS",
                )

        ax.set_rmax(min(speed_max * 1.15, 12))
        ax.set_rticks(range(0, int(speed_max * 1.15) + 1, 2))
        ax.set_yticklabels([f"{v:.0f}" for v in range(0, int(speed_max * 1.15) + 1, 2)], fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_thetagrids(
            [0, 30, 60, 90, 120, 150, 180], ["0°", "30°", "60°", "90°", "120°", "150°", "180°"]
        )

    axes[1].legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=9)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved comparison image to {output_path}")


def _resolve_comparison_polar(
    polars_dir: str, comparison_csv_name: str | None
) -> tuple[Any | None, str]:
    """Return (polar, label) for the comparison polar, or (None, 'none')."""
    if comparison_csv_name:
        csv_path = (
            comparison_csv_name
            if os.path.isabs(comparison_csv_name)
            else os.path.join(polars_dir, comparison_csv_name)
        )
        if os.path.exists(csv_path):
            return load_polar(csv_path), os.path.splitext(os.path.basename(csv_path))[0]
        logger.warning("comparison polar not found: %s", csv_path)
        return None, os.path.splitext(os.path.basename(comparison_csv_name))[0]

    polars = discover_polars(polars_dir)
    if polars:
        first = polars[0]
        return first, first.name
    return None, "none"


def _default_measured_name(input_path: str) -> str:
    """Derive a default polar name `auto_polar_<YYYYMMDD>` from a sailing log path.

    Looks for an 8-digit date in the filename (e.g. `sailing_20260605_214000.jsonl`
    -> `auto_polar_20260605`). Falls back to today's UTC date when no date is
    found in the filename.
    """
    match = re.search(r"(\d{8})", os.path.basename(input_path))
    date_part = match.group(1) if match else _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
    return f"auto_polar_{date_part}"


def _most_recent_measured_csv(output_dir: str) -> str | None:
    """Return the path of the most recently modified ``*.csv`` in output_dir, or None.

    Tie-breaker: highest mtime wins; names sorted ascending as a stable secondary
    key so the choice is deterministic when two files share an mtime.
    """
    try:
        entries = os.listdir(output_dir)
    except OSError:
        return None
    candidates = [f for f in entries if f.endswith(".csv")]
    if not candidates:
        return None
    best: tuple[float, str] | None = None
    for name in sorted(candidates):
        path = os.path.join(output_dir, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, name)
    return os.path.join(output_dir, best[1]) if best else None


def _resolve_target(args: argparse.Namespace, output_dir: str, input_path: str) -> str:
    """Resolve the target measured-polar CSV path (create-or-accumulate target).

    Priority:
      1. ``--measured-name`` (explicit — creates a new file if absent, else
         accumulates into the existing one).
      2. Most-recently-modified existing ``*.csv`` in output_dir (accumulate
         into it; lets you rename a file and keep building it).
      3. ``auto_polar_<YYYYMMDD>`` derived from the sailing log (fresh start).
    """
    if args.measured_name:
        return os.path.join(output_dir, f"{args.measured_name}.csv")
    existing = _most_recent_measured_csv(output_dir)
    if existing is not None:
        print(f"Accumulating into existing measured polar: {os.path.basename(existing)}")
        return existing
    return os.path.join(output_dir, f"{_default_measured_name(input_path)}.csv")


def _run_polar(args: argparse.Namespace, basedir: str) -> int:
    polars_dir = args.polars_dir or os.path.join(basedir, "polars")
    if args.output_dir is None and not args.no_measured_dir:
        output_dir = os.path.join(polars_dir, "measured")
    else:
        output_dir = args.output_dir or polars_dir
    os.makedirs(output_dir, exist_ok=True)

    # --- combine-best mode: envelope across existing measured polar CSVs -----
    if args.combine_best:
        return _run_combine_best(args, output_dir)

    # --- accumulate mode: merge a sailing log into the target measured polar --
    if args.input is None:
        sailing_logs_dir = os.path.join(basedir, "sailing_logs")
        try:
            files = sorted(f for f in os.listdir(sailing_logs_dir) if f.endswith(".jsonl"))
        except OSError:
            files = []
        if not files:
            print("No sailing log files found in sailing_logs/")
            return 0
        input_path = os.path.join(sailing_logs_dir, files[-1])
        print(f"Using most recent sailing log: {files[-1]}")
    else:
        input_path = args.input

    from boatpolars.coverage import build_coverage_from_session

    new_coverage = build_coverage_from_session(input_path)
    if not new_coverage:
        print("No measured data found. Check your sailing log.")
        return 0

    csv_path = _resolve_target(args, output_dir, input_path)
    accumulated = merge_coverage(load_coverage_sidecar(csv_path), new_coverage)
    measured = coverage_mean(accumulated)
    print(
        f"Built measured polar with {len(measured)} data points "
        f"({sum(len(v) for v in accumulated.values())} accumulated samples)"
    )

    write_polar_csv(measured, csv_path)
    save_coverage_sidecar(accumulated, csv_path)
    print(f"Wrote measured polar to {csv_path}")

    _maybe_render_comparison(args, polars_dir, output_dir, csv_path, measured)
    return 0


def _run_combine_best(args: argparse.Namespace, output_dir: str) -> int:
    """Combine multiple measured polar CSVs into an envelope (max STW per bin)."""
    inputs = args.combine_best or []
    measured_dicts = []
    for path in inputs:
        resolved = path if os.path.isabs(path) else os.path.join(output_dir, path)
        if not os.path.exists(resolved):
            print(f"combine-best: polar not found: {resolved}", file=sys.stderr)
            return 1
        measured_dicts.append(read_measured_polar_csv(resolved))
    if not measured_dicts:
        print("combine-best: no input polars given", file=sys.stderr)
        return 1

    combined = combine_best(*measured_dicts)
    if not combined:
        print("combine-best: no overlapping/non-empty bins found.")
        return 0

    name = args.measured_name or "combined_best"
    csv_path = os.path.join(output_dir, f"{name}.csv")
    write_polar_csv(combined, csv_path)
    print(f"Wrote combined-best polar ({len(combined)} bins) to {csv_path}")
    return 0


def _maybe_render_comparison(
    args: argparse.Namespace,
    polars_dir: str,
    output_dir: str,
    csv_path: str,
    measured: dict[tuple[int, int], float],
) -> None:
    comparison_polar, comparison_label = _resolve_comparison_polar(
        polars_dir, args.comparison_polar
    )
    if comparison_polar is None:
        print("No comparison polar available; skipping image.")
        return

    measured_name = os.path.splitext(os.path.basename(csv_path))[0]
    try:
        img_path = os.path.join(output_dir, f"{measured_name}_vs_{comparison_label}.png")
        generate_comparison_image(measured, comparison_polar, comparison_label, img_path)
    except ImportError:
        print("matplotlib not installed; skipping comparison image.")


def _add_polar_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "polar",
        help="Build a measured polar from a sailing log and compare to a theoretical polar",
        description=(
            "Build a measured polar from a sailing log JSONL and compare to a theoretical polar CSV.\n"
            "\n"
            "Accumulation: each run merges the sailing log into the target measured polar\n"
            "(existing CSV, selected by --measured-name or the most recently modified one in\n"
            "the output dir) and recomputes bin means across all accumulated sessions. Raw\n"
            "binned samples are kept in a sidecar <name>.cov.json next to the CSV so means\n"
            "stay correct as sessions accumulate.\n"
            "\n"
            "Combine-best: pass --combine-best a.csv b.csv [c.csv ...] to produce an envelope\n"
            "(max STW per bin) across the listed measured polars, e.g. to merge separate\n"
            "jib/code0/asym polars into one best-performance polar for a race."
        ),
    )
    p.add_argument("--input", default=None, help="Input sailing log JSONL file")
    p.add_argument("--output-dir", default=None, help="Output directory")
    p.add_argument(
        "--no-measured-dir",
        action="store_true",
        help="Write to polars_dir instead of polars/measured/",
    )
    p.add_argument(
        "--polars-dir", default=None, help="Directory to search for the comparison polar"
    )
    p.add_argument(
        "--comparison-polar",
        default=None,
        help="Comparison polar CSV filename or absolute path (default: first polar in --polars-dir)",
    )
    p.add_argument(
        "--measured-name",
        default=None,
        help=(
            "Base name for the measured polar CSV. When given, creates the file if absent or "
            "accumulates into it if it exists. When omitted, the most recently modified "
            "*.csv in the output dir is used; if none, an auto_polar_<YYYYMMDD> file is started."
        ),
    )
    p.add_argument(
        "--combine-best",
        nargs="+",
        default=None,
        metavar="POLAR.csv",
        help=(
            "Combine the listed measured polar CSVs into an envelope (max STW per bin). "
            "Paths may be relative to the output dir. Use --measured-name to name the result "
            "(default: combined_best)."
        ),
    )
    p.set_defaults(func=_run_polar)


# --- `segment` subcommand --------------------------------------------------
def _run_segment(args: argparse.Namespace, basedir: str) -> int:
    """Trim or split a sailing log JSONL file.

    Supports:
      --start/--end: time-bounded trim (local HH:MM within the log's date)
      --drop-state: filter out entries with a given sailing_state (e.g. motoring)
      --split-on idle: split into multiple files at idle gaps > --gap-minutes
    """
    input_path = args.input
    if not input_path or not os.path.exists(input_path):
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    output_dir = args.output_dir or os.path.dirname(input_path) or "."
    os.makedirs(output_dir, exist_ok=True)

    with open(input_path) as f:
        entries = [line for line in f if line.strip()]

    if not entries:
        print("Input file is empty.", file=sys.stderr)
        return 1

    # Parse all entries (skip event lines that don't have a "ts" + sample data)
    parsed: list[dict[str, Any]] = []
    for line in entries:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "ts" in obj:
            parsed.append(obj)

    if not parsed:
        print("No valid JSON entries found.", file=sys.stderr)
        return 1

    # Apply --drop-state filter
    if args.drop_state:
        before = len(parsed)
        parsed = [e for e in parsed if e.get("sailing_state") != args.drop_state]
        print(f"Dropped {before - len(parsed)} '{args.drop_state}' entries")

    # Apply --start/--end time trim (HH:MM within the log's first-entry date)
    if args.start or args.end:
        first_ts = parsed[0]["ts"][:10]  # YYYY-MM-DD
        if args.start:
            start_str = f"{first_ts}T{args.start}"
            parsed = [e for e in parsed if e["ts"] >= start_str]
        if args.end:
            end_str = f"{first_ts}T{args.end}"
            parsed = [e for e in parsed if e["ts"] <= end_str]

    if not parsed:
        print("No entries remain after filtering.", file=sys.stderr)
        return 0

    # Split on idle gaps
    if args.split_on == "idle":
        gap_seconds = (args.gap_minutes or 5) * 60
        segments = _split_on_idle(parsed, gap_seconds)
    else:
        segments = [parsed]

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    for i, seg in enumerate(segments):
        if len(segments) == 1:
            out_name = f"{base_name}_trim.jsonl"
        else:
            out_name = f"{base_name}_seg{i + 1}.jsonl"
        out_path = os.path.join(output_dir, out_name)
        with open(out_path, "w") as f:
            for entry in seg:
                f.write(json.dumps(entry) + "\n")
        print(f"Wrote {len(seg)} entries to {out_path}")

    return 0


def _split_on_idle(entries: list[dict[str, Any]], gap_seconds: int) -> list[list[dict[str, Any]]]:
    """Split entries into segments at idle-state gaps longer than gap_seconds."""
    from datetime import datetime

    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = [entries[0]]
    for prev, cur in itertools.pairwise(entries):
        try:
            t_prev = datetime.fromisoformat(prev["ts"].replace("Z", "+00:00"))
            t_cur = datetime.fromisoformat(cur["ts"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            current.append(cur)
            continue
        gap = (t_cur - t_prev).total_seconds()
        if prev.get("sailing_state") == "idle" and gap > gap_seconds:
            segments.append(current)
            current = [cur]
        else:
            current.append(cur)
    if current:
        segments.append(current)
    return segments


def _add_segment_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "segment",
        help="Trim or split a sailing log JSONL file",
        description="Trim a sailing log by time window, drop motoring/idle stretches, "
        "or split into multiple files at idle gaps.",
    )
    p.add_argument("--input", required=True, help="Input sailing log JSONL file")
    p.add_argument("--output-dir", default=None, help="Output directory (default: same as input)")
    p.add_argument("--start", default=None, help="Start time (HH:MM, within the log's date)")
    p.add_argument("--end", default=None, help="End time (HH:MM, within the log's date)")
    p.add_argument(
        "--drop-state",
        default=None,
        choices=["motoring", "idle", "sailing"],
        help="Filter out entries with the given sailing_state",
    )
    p.add_argument(
        "--split-on",
        default=None,
        choices=["idle"],
        help="Split into multiple files at idle gaps",
    )
    p.add_argument(
        "--gap-minutes",
        type=int,
        default=5,
        help="Minimum idle gap (minutes) to trigger a split (default: 5)",
    )
    p.set_defaults(func=_run_segment)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="log_analysis",
        description="PolarPrism sailing-log analysis CLI (raw log -> sailing log -> measured polar)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    _add_convert_parser(subparsers)
    _add_polar_parser(subparsers)
    _add_segment_parser(subparsers)

    args = parser.parse_args()
    basedir = os.path.dirname(os.path.abspath(__file__))
    rc = args.func(args, basedir)
    if rc:
        sys.exit(rc)


if __name__ == "__main__":
    main()
