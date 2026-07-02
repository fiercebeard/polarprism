from __future__ import annotations

import glob as globmod
import logging
import math
import os

logger = logging.getLogger("polarprism")


class PolarData:
    __slots__ = ("measured", "name", "speed_grid", "twa_list", "tws_list")

    def __init__(
        self,
        name: str,
        twa_list: list[float],
        tws_list: list[float],
        speed_grid: dict[float, dict[float, float]],
        measured: bool = False,
    ) -> None:
        self.name = name
        self.twa_list = twa_list
        self.tws_list = tws_list
        self.speed_grid = speed_grid
        self.measured = measured


def load_polar(filepath: str) -> PolarData | None:
    name = os.path.splitext(os.path.basename(filepath))[0]
    try:
        with open(filepath) as f:
            lines = [line.strip() for line in f if line.strip()]
    except OSError:
        logger.warning("Cannot read polar file: %s", filepath)
        return None
    if not lines:
        logger.warning("Empty polar file: %s", filepath)
        return None

    header = lines[0]
    if ";" in header:
        sep = ";"
    elif "," in header:
        sep = ","
    else:
        return None

    header_parts = header.split(sep)
    tws_list = []
    for v in header_parts[1:]:
        try:
            tws_list.append(float(v))
        except ValueError:
            return None

    twa_list = []
    speed_grid = {}

    for line in lines[1:]:
        parts = line.split(sep)
        if len(parts) < 2:
            continue
        try:
            twa = float(parts[0])
        except ValueError:
            continue
        twa_list.append(twa)
        row = {}
        for i, v in enumerate(parts[1:]):
            if i >= len(tws_list):
                break
            try:
                row[tws_list[i]] = float(v)
            except ValueError:
                row[tws_list[i]] = 0.0
        speed_grid[twa] = row

    return PolarData(name=name, twa_list=twa_list, tws_list=tws_list, speed_grid=speed_grid)


def load_saildef(filepath: str) -> dict:
    saildef: dict[int, str] = {}
    if not os.path.exists(filepath):
        return saildef
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sep = ";" if ";" in line else ","
            parts = line.split(sep)
            if len(parts) >= 2:
                try:
                    num = int(float(parts[0]))
                    saildef[num] = parts[1]
                except ValueError:
                    pass
    return saildef


def load_sailselect(filepath: str) -> dict | None:
    if not os.path.exists(filepath):
        return None
    with open(filepath) as f:
        lines = [line.strip() for line in f if line.strip()]
    if not lines:
        return None

    sep = ";" if ";" in lines[0] else ","
    header = lines[0].split(sep)
    tws_list = []
    for v in header[1:]:
        try:
            tws_list.append(float(v))
        except ValueError:
            tws_list.append(0.0)

    rows = []
    for line in lines[1:]:
        parts = line.split(sep)
        if len(parts) < 2:
            continue
        try:
            twa = float(parts[0])
        except ValueError:
            continue
        sail_nums = []
        for v in parts[1:]:
            try:
                sail_nums.append(int(float(v)))
            except ValueError:
                sail_nums.append(0)
        rows.append((twa, sail_nums))

    return {"tws_list": tws_list, "rows": rows}


# Shipped sample polars are prefixed so they can be recognized (and hidden
# once the user adds their own data).
EXAMPLE_PREFIX = "example_"


def list_polar_csvs(directory: str) -> list[str]:
    """Return the polar CSV paths that should be loaded from ``directory``.

    The shipped ``example_*`` sample polars only load when they are the *only*
    polars present — they exist so the app demos out of the box. As soon as
    the user drops in a real polar CSV, the examples are ignored entirely (no
    need to delete them).
    """
    if not os.path.isdir(directory):
        return []
    paths = sorted(globmod.glob(os.path.join(directory, "*.csv")))
    real = [p for p in paths if not os.path.basename(p).startswith(EXAMPLE_PREFIX)]
    if real and len(real) < len(paths):
        logger.info(
            "Ignoring %d example polar(s) in %s (real polars present)",
            len(paths) - len(real),
            directory,
        )
    return real if real else paths


def discover_polars(directory: str) -> list[PolarData]:
    polars: list[PolarData] = []
    for csv_path in list_polar_csvs(directory):
        p = load_polar(csv_path)
        if p is not None:
            polars.append(p)
    return polars


def discover_measured_polars(directory: str) -> list[PolarData]:
    """Load polar CSVs from the measured polar directory.

    Same as discover_polars but marks loaded polars with ``measured=True``
    and logs how many were loaded.
    """
    polars: list[PolarData] = []
    if not os.path.isdir(directory):
        logger.info("No measured polar directory: %s", directory)
        return polars
    for csv_path in sorted(globmod.glob(os.path.join(directory, "*.csv"))):
        p = load_polar(csv_path)
        if p is not None:
            p.measured = True
            polars.append(p)
            logger.info("Loaded measured polar: %s", p.name)
    logger.info("Loaded %d measured polar(s) from %s", len(polars), directory)
    return polars


def discover_saildef(directory: str, polar_names: list[str] | None = None) -> dict:
    saildef_files = sorted(globmod.glob(os.path.join(directory, "*.saildef")))
    if not saildef_files:
        return {}
    if len(saildef_files) == 1:
        return load_saildef(saildef_files[0])
    if polar_names:
        for pn in polar_names:
            candidate = os.path.join(directory, f"{pn}.saildef")
            if os.path.exists(candidate):
                return load_saildef(candidate)
    return load_saildef(saildef_files[0])


def discover_sailselect(directory: str, polar_names: list[str] | None = None) -> dict | None:
    sailselect_files = sorted(globmod.glob(os.path.join(directory, "*.sailselect")))
    if not sailselect_files:
        return None
    if len(sailselect_files) == 1:
        return load_sailselect(sailselect_files[0])
    if polar_names:
        for pn in polar_names:
            candidate = os.path.join(directory, f"{pn}.sailselect")
            if os.path.exists(candidate):
                return load_sailselect(candidate)
    return load_sailselect(sailselect_files[0])


def build_sail_to_polar(
    saildef: dict,
    polar_names: list[str],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    polar_basenames = {pn.lower(): pn for pn in polar_names}
    for sail_name in saildef.values():
        sail_lower = sail_name.lower()
        candidates = [
            polar_basenames.get(sail_lower),
            polar_basenames.get(f"bestperf_{sail_lower}"),
        ]
        for pn in polar_names:
            pn_lower = pn.lower()
            if pn_lower.endswith(f"_{sail_lower}") or pn_lower == sail_lower:
                candidates.append(pn)
                break
        for c in candidates:
            if c is not None and c in polar_basenames.values():
                mapping[sail_name] = c
                break
        else:
            partial = [pn for pn in polar_names if sail_lower in pn.lower()]
            if len(partial) == 1:
                mapping[sail_name] = partial[0]
    return mapping


def compute_polar_display_names(
    polar_names: list[str],
    sail_to_polar: dict[str, str],
    saildef: dict,
) -> dict[str, str]:
    display: dict[str, str] = {}
    polar_to_sail: dict[str, str] = {v: k for k, v in sail_to_polar.items()}
    for pn in polar_names:
        if pn in polar_to_sail:
            display[pn] = polar_to_sail[pn]
            continue
        if polar_names:
            prefix = os.path.commonprefix(polar_names)
            candidate = pn
            if prefix and prefix != pn:
                candidate = pn[len(prefix) :]
                if candidate.startswith("_") or candidate.startswith("-"):
                    candidate = candidate[1:]
            if not candidate:
                candidate = pn
            display[pn] = candidate
        else:
            display[pn] = pn
    return display


def build_sail_groups(
    saildef: dict,
    config_groups: list[tuple[str, list[str]]] | None = None,
) -> list[tuple[str, list[str]]]:
    if config_groups:
        return [(name, list(sails)) for name, sails in config_groups]
    sail_names = sorted(saildef.values())
    if not sail_names:
        return []
    groups: list[tuple[str, list[str]]] = [("sails", sail_names)]
    return groups


def lookup_speed(polar: PolarData, twa_deg: float, tws_kts: float) -> float | None:
    if polar is None:
        return None
    twa = abs(twa_deg) % 360
    tws_list = polar.tws_list
    twa_list = polar.twa_list
    grid = polar.speed_grid

    if not tws_list or not twa_list:
        return None

    if tws_kts <= tws_list[0]:
        tws_lo, tws_hi = tws_list[0], tws_list[0]
        tws_frac = 0.0
    elif tws_kts >= tws_list[-1]:
        tws_lo, tws_hi = tws_list[-1], tws_list[-1]
        tws_frac = 0.0
    else:
        for i in range(len(tws_list) - 1):
            if tws_list[i] <= tws_kts <= tws_list[i + 1]:
                tws_lo = tws_list[i]
                tws_hi = tws_list[i + 1]
                tws_diff = tws_hi - tws_lo
                tws_frac = (tws_kts - tws_lo) / tws_diff if tws_diff > 0 else 0.0
                break
        else:
            tws_lo = tws_hi = tws_list[-1]
            tws_frac = 0.0

    if twa <= twa_list[0]:
        twa_lo, twa_hi = twa_list[0], twa_list[0]
        twa_frac = 0.0
    elif twa >= twa_list[-1]:
        twa_lo, twa_hi = twa_list[-1], twa_list[-1]
        twa_frac = 0.0
    else:
        twa_lo_idx = 0
        for i in range(len(twa_list) - 1):
            if twa_list[i] <= twa <= twa_list[i + 1]:
                twa_lo_idx = i
                break
        else:
            twa_lo_idx = len(twa_list) - 2
        twa_lo = twa_list[twa_lo_idx]
        twa_hi = twa_list[min(twa_lo_idx + 1, len(twa_list) - 1)]
        twa_diff = twa_hi - twa_lo
        twa_frac = (twa - twa_lo) / twa_diff if twa_diff > 0 else 0.0

    def get_speed(t: float, s: float) -> float:
        row = grid.get(t)
        if row is None:
            return 0.0
        return row.get(s, 0.0)

    s00 = get_speed(twa_lo, tws_lo)
    s01 = get_speed(twa_lo, tws_hi)
    s10 = get_speed(twa_hi, tws_lo)
    s11 = get_speed(twa_hi, tws_hi)

    s0 = s00 + (s01 - s00) * tws_frac
    s1 = s10 + (s11 - s10) * tws_frac
    return s0 + (s1 - s0) * twa_frac


def lookup_recommended_sail(
    sailselect_data: dict | None,
    saildef: dict[int, str],
    polar_twa_list: list[float],
    twa_deg: float,
    tws_kts: float,
) -> str | None:
    if sailselect_data is None or not polar_twa_list:
        return None
    rows = sailselect_data["rows"]
    n_select_rows = len(rows)
    n_polar_twas = len(polar_twa_list)
    twa = abs(twa_deg) % 360

    twa_polar_idx = 0
    for i, t in enumerate(polar_twa_list):
        if t <= twa:
            twa_polar_idx = i
        else:
            break

    twa_select_idx = int(twa_polar_idx * n_select_rows / max(n_polar_twas, 1))
    twa_select_idx = min(twa_select_idx, n_select_rows - 1)

    _, sail_nums = rows[twa_select_idx]
    if not sail_nums:
        return None

    n_select_cols = len(sail_nums)
    polar_tws_list = []
    if hasattr(lookup_recommended_sail, "_polar_tws"):
        polar_tws_list = lookup_recommended_sail._polar_tws

    tws_col_idx = 0
    if polar_tws_list:
        for i, t in enumerate(polar_tws_list):
            if t <= tws_kts:
                tws_col_idx = i
        tws_col_idx = int(tws_col_idx * n_select_cols / max(len(polar_tws_list), 1))
        tws_col_idx = min(tws_col_idx, n_select_cols - 1)

    sail_num = sail_nums[tws_col_idx]
    return saildef.get(sail_num, f"Sail {sail_num}")


def auto_select_tws_index(polar: PolarData, wind_kts: float | None) -> int | None:
    """Return the index of the polar TWS band closest to wind_kts, or None.

    Pure lookup; the caller is responsible for computing wind_kts and for
    writing the result onto state if desired. Kept here so both the polar
    page (initial selection) and the perf sampler (periodic refresh) share
    one implementation without signalk depending on pages.
    """
    if wind_kts is None or not polar.tws_list:
        return None
    best_i = 0
    best_diff = abs(polar.tws_list[0] - wind_kts)
    for i, tws in enumerate(polar.tws_list[1:], 1):
        diff = abs(tws - wind_kts)
        if diff < best_diff:
            best_diff = diff
            best_i = i
    return best_i


def compute_true_wind(
    awa_rad: float | None, aws_ms: float | None, stw_ms: float | None
) -> tuple[float | None, float | None]:
    if aws_ms is None or awa_rad is None:
        return None, None
    stw = stw_ms if stw_ms is not None else 0.0
    aws = aws_ms
    awa = awa_rad
    if stw > 0.1:
        x = aws * math.sin(awa)
        y = aws * math.cos(awa) - stw
        twa = math.atan2(x, y)
        tws = math.sqrt(max(0, x * x + y * y))
    else:
        twa = awa
        tws = aws
    return twa, tws


def calc_vmg(polar: PolarData, tws_kts: float) -> dict | None:
    if polar is None or tws_kts is None:
        return None
    best_upwind_vmg: float = -1e9
    best_upwind_twa: float | None = None
    best_upwind_speed: float | None = None
    best_downwind_vmg: float = -1e9
    best_downwind_twa: float | None = None
    best_downwind_speed: float | None = None
    for twa_deg in polar.twa_list:
        if twa_deg < 1:
            continue
        spd = lookup_speed(polar, twa_deg, tws_kts)
        if spd is None or spd <= 0:
            continue
        vmg = spd * math.cos(math.radians(twa_deg))
        if 0 < twa_deg <= 90 and vmg > best_upwind_vmg:
            best_upwind_vmg = vmg
            best_upwind_twa = twa_deg
            best_upwind_speed = spd
        if 90 < twa_deg <= 180 and -vmg > best_downwind_vmg:
            best_downwind_vmg = -vmg
            best_downwind_twa = twa_deg
            best_downwind_speed = spd
    result: dict[str, float | None] = {}
    if best_upwind_twa is not None:
        result["upwind_twa"] = best_upwind_twa
        result["upwind_vmg"] = best_upwind_vmg
        result["upwind_speed"] = best_upwind_speed
    if best_downwind_twa is not None:
        result["downwind_twa"] = best_downwind_twa
        result["downwind_vmg"] = best_downwind_vmg
        result["downwind_speed"] = best_downwind_speed
    return result if result else None


def calc_vmc(
    polar: PolarData | None, tws_kts: float | None, course_twa_deg: float | None
) -> dict | None:
    if polar is None or tws_kts is None or course_twa_deg is None:
        return None
    best_vmc = -1e9
    best_twa = None
    best_speed = None
    best_tack = None
    for twa_deg in polar.twa_list:
        if twa_deg < 1:
            continue
        spd = lookup_speed(polar, twa_deg, tws_kts)
        if spd is None or spd <= 0:
            continue
        for sign in (1, -1):
            twa_signed = sign * twa_deg
            vmc = spd * math.cos(math.radians(twa_signed - course_twa_deg))
            if vmc > best_vmc:
                best_vmc = vmc
                best_twa = twa_signed
                best_speed = spd
                best_tack = "starboard" if sign > 0 else "port"
    if best_twa is None:
        return None
    return {
        "course_twa": course_twa_deg,
        "best_twa": best_twa,
        "best_speed": best_speed,
        "best_vmc": best_vmc,
        "best_tack": best_tack,
    }
