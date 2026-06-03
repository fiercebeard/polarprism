import math
import os
import glob as globmod


class PolarData:
    __slots__ = ("name", "twa_list", "tws_list", "speed_grid")

    def __init__(self, name, twa_list, tws_list, speed_grid):
        self.name = name
        self.twa_list = twa_list
        self.tws_list = tws_list
        self.speed_grid = speed_grid


def load_polar(filepath):
    name = os.path.splitext(os.path.basename(filepath))[0]
    with open(filepath, "r") as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines:
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


def load_saildef(filepath):
    saildef = {}
    if not os.path.exists(filepath):
        return saildef
    with open(filepath, "r") as f:
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


def load_sailselect(filepath):
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r") as f:
        lines = [l.strip() for l in f if l.strip()]
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


def discover_polars(directory):
    polars = []
    if not os.path.isdir(directory):
        return polars
    for csv_path in sorted(globmod.glob(os.path.join(directory, "*.csv"))):
        p = load_polar(csv_path)
        if p is not None:
            polars.append(p)
    return polars


def lookup_speed(polar, twa_deg, tws_kts):
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

    def get_speed(t, s):
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


def lookup_recommended_sail(sailselect_data, saildef, polar_twa_list, twa_deg, tws_kts):
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
    tws_list = polar_twa_list  # dummy, we use proportional mapping
    polar_tws_list = []
    if hasattr(lookup_recommended_sail, '_polar_tws'):
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


def compute_true_wind(awa_rad, aws_ms, stw_ms):
    if aws_ms is None or awa_rad is None:
        return None, None
    stw = stw_ms if stw_ms is not None else 0.0
    aws = aws_ms
    awa = awa_rad
    sin_twa = aws * math.sin(awa) / max(stw, 0.01)
    cos_twa = (aws * math.cos(awa) + stw) / max(stw, 0.01) if stw > 0.1 else aws * math.cos(awa) / max(aws, 0.01)
    sin_twa = max(-1.0, min(1.0, sin_twa))
    twa = math.asin(sin_twa)
    if cos_twa < 0:
        twa = math.copysign(math.pi - abs(twa), twa)
    tws = math.sqrt(max(0, (aws * math.sin(awa)) ** 2 + (aws * math.cos(awa) + stw) ** 2))
    return twa, tws