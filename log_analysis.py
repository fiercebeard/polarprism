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
bin observed (TWA, TWS, STW) samples into a polar grid, write the resulting
measured polar as a CSV, and — if matplotlib is installed and a comparison
polar is available — render a side-by-side polar plot.

    python log_analysis.py polar [--input INPUT.jsonl] \\
        [--output-dir DIR] [--polars-dir DIR] [--comparison-polar NAME.csv]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from typing import Any

from polars.parser import discover_polars, load_polar, lookup_speed
from signalk.models import MS_TO_KNOTS
from signalk.rawlog import convert_raw_to_sailing_log

logger = logging.getLogger("polarprism")

# --- measured-polar binning constants --------------------------------------
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
def build_measured_polar(input_jsonl: str) -> dict[tuple[int, int], float]:
    """Build measured polar data from a sailing log JSONL file.

    Returns a dict keyed by ``(twa_bin, tws_bin)`` -> mean STW in knots, only
    for bins with at least ``MIN_SAMPLES_PER_BIN`` samples.
    """
    bins: dict[tuple[int, int], list[float]] = {}

    with open(input_jsonl) as f:
        for line in f:
            e = json.loads(line)
            awa = e.get("awa")
            aws = e.get("aws")
            stw = e.get("stw")

            if awa is None or aws is None or stw is None:
                continue
            if stw < MIN_STW_KTS or aws < MIN_AWS_KTS:
                continue

            awa_norm = awa if awa <= 180 else awa - 360
            awa_rad = math.radians(awa_norm)
            aws_ms = aws / MS_TO_KNOTS
            stw_ms = stw / MS_TO_KNOTS

            sin_twa = aws_ms * math.sin(awa_rad) / max(stw_ms, 0.1)
            cos_twa_num = aws_ms * math.cos(awa_rad) + stw_ms
            cos_twa_den = max(stw_ms, 0.1) if stw_ms > 0.1 else aws_ms
            cos_twa = (
                cos_twa_num / cos_twa_den
                if stw_ms > 0.1
                else aws_ms * math.cos(awa_rad) / max(aws_ms, 0.01)
            )

            sin_twa = max(-1.0, min(1.0, sin_twa))
            twa_rad = math.asin(sin_twa)
            if cos_twa < 0:
                twa_rad = math.copysign(math.pi - abs(twa_rad), twa_rad)

            twa_deg = abs(math.degrees(twa_rad))
            if twa_deg > 180:
                twa_deg = 360 - twa_deg

            tws_ms = math.sqrt(
                max(
                    0,
                    (aws_ms * math.sin(awa_rad)) ** 2 + (aws_ms * math.cos(awa_rad) + stw_ms) ** 2,
                )
            )
            tws_kts = tws_ms * MS_TO_KNOTS

            twa_bin = round(twa_deg / TWA_BIN_DEG) * TWA_BIN_DEG
            tws_bin = round(tws_kts / TWS_BIN_KTS) * TWS_BIN_KTS

            if twa_bin < TWA_MIN_DEG or twa_bin > TWA_MAX_DEG:
                continue
            if tws_bin < TWS_MIN_KTS or tws_bin > TWS_MAX_KTS:
                continue

            bins.setdefault((twa_bin, tws_bin), []).append(stw)

    return {
        key: sum(speeds) / len(speeds)
        for key, speeds in bins.items()
        if len(speeds) >= MIN_SAMPLES_PER_BIN
    }


def interpolate_measured(
    measured: dict[tuple[int, int], float], twa: float, tws: float
) -> float | None:
    """Bilinear (inverse-distance) interpolation of measured polar data."""
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


def _run_polar(args: argparse.Namespace, basedir: str) -> int:
    polars_dir = args.polars_dir or os.path.join(basedir, "polars")
    output_dir = args.output_dir or polars_dir

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

    os.makedirs(output_dir, exist_ok=True)

    measured = build_measured_polar(input_path)
    if not measured:
        print("No measured data found. Check your sailing log.")
        return 0

    print(f"Built measured polar with {len(measured)} data points")

    csv_path = os.path.join(output_dir, f"{args.measured_name}.csv")
    write_polar_csv(measured, csv_path)
    print(f"Wrote measured polar to {csv_path}")

    comparison_polar, comparison_label = _resolve_comparison_polar(
        polars_dir, args.comparison_polar
    )
    if comparison_polar is None:
        print("No comparison polar available; skipping image.")
        return 0

    try:
        img_path = os.path.join(output_dir, f"{args.measured_name}_vs_{comparison_label}.png")
        generate_comparison_image(measured, comparison_polar, comparison_label, img_path)
    except ImportError:
        print("matplotlib not installed; skipping comparison image.")
    return 0


def _add_polar_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "polar",
        help="Build a measured polar from a sailing log and compare to a theoretical polar",
        description="Build a measured polar from a sailing log JSONL and compare to a theoretical polar CSV.",
    )
    p.add_argument("--input", default=None, help="Input sailing log JSONL file")
    p.add_argument("--output-dir", default=None, help="Output directory")
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
        default="Measured",
        help="Base name for the measured polar CSV (default: Measured -> Measured.csv)",
    )
    p.set_defaults(func=_run_polar)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="log_analysis",
        description="PolarPrism sailing-log analysis CLI (raw log -> sailing log -> measured polar)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    _add_convert_parser(subparsers)
    _add_polar_parser(subparsers)

    args = parser.parse_args()
    basedir = os.path.dirname(os.path.abspath(__file__))
    rc = args.func(args, basedir)
    if rc:
        sys.exit(rc)


if __name__ == "__main__":
    main()
