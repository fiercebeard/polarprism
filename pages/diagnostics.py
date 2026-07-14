import math
import time
from datetime import datetime
from typing import Any

import pygame

from pages.ui import draw_heading, draw_row
from signalk.models import (
    CURRENT_LEEWAY_MIN_SOG_KTS,
    CURRENT_LEEWAY_MIN_STW_KTS,
    DRIFT_CALC_MIN_SOG_KTS,
    HDG_ERROR_WARN_DEG,
    HDG_ERROR_WARN_SPEED_KTS,
    HEADING_OFFSET_INCREMENT_DEG,
    MS_TO_KNOTS,
    STALE_VALUE_AGE_SEC,
    VARIATION_DELTA_WARN_DEG,
    State,
    angle_diff,
    calc_age,
    filtered_value,
    norm_angle,
    rad_to_deg,
    rad_to_deg_signed,
)
from theme import (
    BG,
    CALC,
    TEXT_DIM,
    TEXT_SRC,
    TEXT_VALUE,
    WARN,
    build_device_sections,
)

NMEA_LOG_MAX_LINES = 500
ROW_H = 17
VAL_H = 22

# Column anchors within the diagnostics Values panel (relative to panel x).
VALUE_X_OFFSET = 140
TIME_X_OFFSET = 220
DETAIL_X_OFFSET = 340


def _format_diag_value(fmt_type: str, val: float | None, state: State) -> str | None:
    if fmt_type == "deg6":
        return f"{rad_to_deg(val):06.1f}\u00b0" if val is not None else "---\u00b0"
    if fmt_type == "deg6_opt":
        if val is None:
            return None
        return f"{math.degrees(val):06.1f}\u00b0"
    if fmt_type == "deg_signed2":
        return f"{rad_to_deg_signed(val):+.2f}\u00b0" if val is not None else "---\u00b0"
    if fmt_type == "deg_signed2_opt":
        if val is None:
            return None
        return f"{math.degrees(val):+.2f}\u00b0"
    if fmt_type == "deg_signed1":
        return f"{math.degrees(val):+.1f}\u00b0" if val is not None else "---\u00b0"
    if fmt_type == "deg_signed1_opt":
        if val is None:
            return None
        return f"{math.degrees(val):+.1f}\u00b0"
    if fmt_type == "rot":
        return f"{math.degrees(val):+.2f}\u00b0/s" if val is not None else "---\u00b0/s"
    if fmt_type == "speed_kts":
        return f"{(val or 0) * MS_TO_KNOTS:.2f} kts" if val is not None else "--- kts"
    if fmt_type == "wind_combined":
        was = state.values.get("windSpeedApparent")
        if was is None:
            return None
        if val is None:
            return "--- kts"
        return f"{math.degrees(val):+.0f}\u00b0 at {was * MS_TO_KNOTS:.1f} kts"
    return "---"


def _format_last_update(ts: float | None) -> str:
    """Wall-clock HH:MM:SS for a last_update timestamp, or empty if never set."""
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _draw_signal_row(
    surface,
    font_sm,
    x: int,
    y: int,
    label: str,
    value_str: str,
    state: State,
    signal_key: str,
    src_color: tuple,
    show_detail: bool,
    stale_age: float = STALE_VALUE_AGE_SEC,
) -> bool:
    """Draw one sourced-signal row with last-updated time. False if hidden."""
    age = state.last_update.get(signal_key)
    if age is None or time.time() - age > stale_age:
        return False
    src = state.sources.get(signal_key, "")
    dev = state.device_names.get(src, src) if src else ""
    row_kwargs: dict[str, Any] = {
        "label_x": x + 4,
        "value_x": x + VALUE_X_OFFSET,
        "detail": _format_last_update(age),
        "detail_x": x + TIME_X_OFFSET,
        "detail_color": src_color,
    }
    draw_row(surface, font_sm, x, y, label, value_str, **row_kwargs)
    if show_detail and dev:
        ts = font_sm.render(dev, True, src_color)
        surface.blit(ts, (x + DETAIL_X_OFFSET, y))
    return True


def _draw_calc_row(
    surface,
    font_sm,
    x: int,
    y: int,
    label: str,
    value_str: str,
    time_str: str,
    detail: str,
    detail_color: tuple,
    color: tuple = TEXT_VALUE,
) -> None:
    """Draw one CALC row with last-updated time and a detail note."""
    draw_row(
        surface,
        font_sm,
        x,
        y,
        label,
        value_str,
        label_x=x + 4,
        value_x=x + VALUE_X_OFFSET,
        color=color,
        detail=time_str,
        detail_x=x + TIME_X_OFFSET,
        detail_color=detail_color,
    )
    if detail:
        ts = font_sm.render(detail, True, detail_color)
        surface.blit(ts, (x + DETAIL_X_OFFSET, y))


def _calc_time_str(state: State, keys: list[str]) -> str:
    """Last-updated HH:MM:SS for the freshest input of a CALC row."""
    _, latest = calc_age(state, keys)
    return _format_last_update(latest)


def draw_values(surface, font, font_sm, state, rect, stale_age: float = STALE_VALUE_AGE_SEC):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))

    val_color = TEXT_VALUE
    src_color = TEXT_SRC
    warn_color = WARN
    dim_color = TEXT_DIM
    calc_color = CALC

    y = y0 + 4

    for section in build_device_sections(state):
        y += 4
        draw_heading(surface, font_sm, x + 4, y, f"--- {section['title']} ---")
        y += ROW_H - 2
        for label, signal_key, fmt_type in section["rows"]:
            val = state.values.get(signal_key)
            value_str = _format_diag_value(fmt_type, val, state)
            if value_str is None:
                continue
            show_src = fmt_type != "wind_combined" and not fmt_type.endswith("_opt")
            if _draw_signal_row(
                surface,
                font_sm,
                x,
                y,
                label,
                value_str,
                state,
                signal_key,
                src_color,
                show_src,
                stale_age,
            ):
                y += ROW_H

    y = _draw_heading_error_block(
        surface, font_sm, state, x, y, dim_color, val_color, warn_color, calc_color, stale_age
    )
    y = _draw_mag_cog_block(surface, font_sm, state, x, y, dim_color, calc_color, stale_age)
    y = _draw_ap_block(surface, font_sm, state, x, y, dim_color, stale_age)

    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- Variation Sources ---")
    y += ROW_H - 2

    mv_multi = state.multi_values.get("magneticVariation", {})
    if mv_multi and len(mv_multi) >= 2:
        vals = []
        for src, v in mv_multi.items():
            dev_name = state.device_names.get(src, src)
            vals.append((dev_name, math.degrees(v), src))
        vals.sort(key=lambda t: t[1])
        delta = vals[-1][1] - vals[0][1]
        for dev_name, v_deg, src in vals:
            draw_row(
                surface,
                font_sm,
                x,
                y,
                f"  {dev_name}:",
                f"{v_deg:+.4f}\u00b0",
                label_x=x + 4,
                value_x=x + VALUE_X_OFFSET,
                detail=f"({src})",
                detail_x=x + DETAIL_X_OFFSET,
                detail_color=dim_color,
            )
            y += ROW_H
        delta_warn = abs(delta) > VARIATION_DELTA_WARN_DEG
        row_color = warn_color if delta_warn else val_color
        draw_row(
            surface,
            font_sm,
            x,
            y,
            "CALC: Delta:",
            f"{delta:+.4f}\u00b0",
            label_x=x + 4,
            value_x=x + VALUE_X_OFFSET,
            color=row_color,
            detail="EXCESSIVE" if delta_warn else "OK",
            detail_x=x + DETAIL_X_OFFSET,
            detail_color=dim_color,
        )
        y += ROW_H

    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- Hdg Offset ---")
    y += ROW_H - 2

    draw_row(
        surface,
        font_sm,
        x,
        y,
        "Offset:",
        f"{state.heading_offset:+.1f}\u00b0",
        label_x=x + 4,
        value_x=x + VALUE_X_OFFSET,
        detail="[\u200b]/] to adjust",
        detail_x=x + DETAIL_X_OFFSET,
        detail_color=dim_color,
    )


def _draw_heading_error_block(
    surface, font_sm, state, x, y, dim_color, val_color, warn_color, calc_color, stale_age
):
    """Draw the CALC: Heading Error section. Returns updated y."""
    hm = state.values.get("headingMagnetic")
    mv = state.values.get("magneticVariation")
    cog = filtered_value(state, "cogTrue")
    sog = filtered_value(state, "speedOverGround")
    stw = state.values.get("speedThroughWater")

    hdg_inputs = ["headingMagnetic", "magneticVariation", "cogTrue"]
    hdg_age, _ = calc_age(state, hdg_inputs)
    if hdg_age is None or hdg_age > stale_age:
        return y

    derived_ht = None
    if hm is not None and mv is not None:
        derived_ht = norm_angle(hm + mv + math.radians(state.heading_offset))
    elif hm is not None:
        derived_ht = hm

    if derived_ht is None or cog is None:
        return y

    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- CALC: Heading Error ---")
    y += ROW_H - 2

    if hm is not None and mv is not None:
        calc_label = "TRUE HDG"
        calc_src = "(CALC: Mag+Var)"
    else:
        calc_label = "MAG HDG"
        calc_src = "(no variation)"

    hdg_time = _calc_time_str(state, hdg_inputs)
    hdg_err = angle_diff(cog, derived_ht)
    hdg_err_deg = math.degrees(hdg_err)
    sog_kts = (sog or 0) * MS_TO_KNOTS
    stw_kts = (stw or 0) * MS_TO_KNOTS

    _draw_calc_row(
        surface,
        font_sm,
        x,
        y,
        f"{calc_label}:",
        f"{rad_to_deg(derived_ht):06.1f}\u00b0",
        hdg_time,
        calc_src,
        dim_color,
        calc_color,
    )
    y += ROW_H
    _draw_calc_row(
        surface,
        font_sm,
        x,
        y,
        "COG TRUE:",
        f"{rad_to_deg(cog):06.1f}\u00b0",
        hdg_time,
        "(measured)",
        dim_color,
    )
    y += ROW_H
    hdg_warn = abs(hdg_err_deg) > HDG_ERROR_WARN_DEG and sog_kts > HDG_ERROR_WARN_SPEED_KTS
    row_color = warn_color if hdg_warn else val_color
    _draw_calc_row(
        surface,
        font_sm,
        x,
        y,
        "HDG ERROR:",
        f"{hdg_err_deg:+.1f}\u00b0",
        hdg_time,
        "COG-Heading" if abs(hdg_err_deg) < 180 else "wrap?",
        dim_color,
        row_color,
    )
    y += ROW_H

    current_inputs = ["headingMagnetic", "cogTrue", "speedOverGround", "speedThroughWater"]
    cur_age, _ = calc_age(state, current_inputs)
    if cur_age is not None and cur_age <= stale_age:
        if sog_kts > CURRENT_LEEWAY_MIN_SOG_KTS and stw_kts > CURRENT_LEEWAY_MIN_STW_KTS:
            y = _draw_current_drift_leeway(
                surface, font_sm, x, y, hdg_err, sog_kts, stw_kts, current_inputs, dim_color, state
            )
        elif sog_kts > CURRENT_LEEWAY_MIN_SOG_KTS:
            cur_time = _calc_time_str(state, ["headingMagnetic", "cogTrue", "speedOverGround"])
            _draw_calc_row(
                surface,
                font_sm,
                x,
                y,
                "CALC: Leeway:",
                f"{hdg_err_deg:+.1f}\u00b0 (incl. current)",
                cur_time,
                "(no STW)",
                dim_color,
            )
            y += ROW_H
        else:
            cur_time = _calc_time_str(state, ["speedOverGround"])
            _draw_calc_row(
                surface,
                font_sm,
                x,
                y,
                "SOG:",
                f"{sog_kts:.1f} kts",
                cur_time,
                "too slow for calc",
                dim_color,
            )
            y += ROW_H
    return y


def _draw_current_drift_leeway(
    surface, font_sm, x, y, hdg_err, sog_kts, stw_kts, inputs, dim_color, state
):
    """Draw Current / Drift / Leeway rows. Returns updated y."""
    cur_time = _calc_time_str(state, inputs)
    current_drift = stw_kts * abs(math.sin(hdg_err)) / max(sog_kts, DRIFT_CALC_MIN_SOG_KTS)
    leeway_est = math.degrees(
        math.asin(
            min(
                1,
                max(-1, math.sin(hdg_err) * sog_kts / max(stw_kts, DRIFT_CALC_MIN_SOG_KTS)),
            )
        )
    )
    _draw_calc_row(
        surface,
        font_sm,
        x,
        y,
        "CALC: Current:",
        f"{abs(sog_kts - stw_kts):.1f} kts",
        cur_time,
        "set" if abs(sog_kts - stw_kts) > 1 else "light",
        dim_color,
    )
    y += ROW_H
    _draw_calc_row(
        surface,
        font_sm,
        x,
        y,
        "CALC: Drift:",
        f"{current_drift:.1f} kts",
        cur_time,
        f"{math.degrees(hdg_err):+.0f}\u00b0 set",
        dim_color,
    )
    y += ROW_H
    _draw_calc_row(
        surface,
        font_sm,
        x,
        y,
        "CALC: Leeway:",
        f"{leeway_est:+.1f}\u00b0",
        cur_time,
        "(est from hdg-COG)",
        dim_color,
    )
    y += ROW_H
    return y


def _draw_mag_cog_block(surface, font_sm, state, x, y, dim_color, calc_color, stale_age):
    """Draw the CALC: Mag-COG row. Returns updated y."""
    hm = state.values.get("headingMagnetic")
    cog = filtered_value(state, "cogTrue")
    if hm is None or cog is None:
        return y
    inputs = ["headingMagnetic", "cogTrue"]
    age, _ = calc_age(state, inputs)
    if age is None or age > stale_age:
        return y
    mag_cog = math.degrees(angle_diff(hm, cog))
    mag_time = _calc_time_str(state, inputs)
    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- CALC: Mag-COG ---")
    y += ROW_H - 2
    _draw_calc_row(
        surface,
        font_sm,
        x,
        y,
        "CALC: Mag-COG:",
        f"{mag_cog:+.1f}\u00b0",
        mag_time,
        "(includes variation+leeway+current)",
        dim_color,
        calc_color,
    )
    y += ROW_H
    return y


def _draw_ap_block(surface, font_sm, state, x, y, dim_color, stale_age):
    """Draw the CALC: AP off-hdg row. Returns updated y."""
    hm = state.values.get("headingMagnetic")
    mv = state.values.get("magneticVariation")
    ap_target = state.values.get("apTargetMagnetic")
    if hm is None or mv is None or ap_target is None:
        return y
    inputs = ["headingMagnetic", "magneticVariation", "apTargetMagnetic"]
    age, _ = calc_age(state, inputs)
    if age is None or age > stale_age:
        return y
    derived_ht = norm_angle(hm + mv + math.radians(state.heading_offset))
    ap_true = norm_angle(ap_target + mv)
    ap_off = math.degrees(angle_diff(ap_true, derived_ht))
    ap_time = _calc_time_str(state, inputs)
    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- CALC: AP off hdg ---")
    y += ROW_H - 2
    _draw_calc_row(
        surface,
        font_sm,
        x,
        y,
        "CALC: AP off hdg:",
        f"{ap_off:+.1f}\u00b0",
        ap_time,
        "to port" if ap_off > 0 else "to stbd",
        dim_color,
    )
    y += ROW_H
    return y


def draw_nmea_log(surface, font, font_sm, state, rect):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))

    pad = 8
    log_x = x + pad
    log_y = y0 + pad
    log_h = h - pad * 2

    draw_heading(
        surface, font_sm, log_x, log_y, f"--- NMEA Data Log ({len(state.nmea_log)} messages) ---"
    )
    log_y += VAL_H

    line_h = font_sm.get_height() + 2
    max_lines = max(1, (log_y + log_h - log_y) // line_h)

    entries = list(state.nmea_log)
    visible = entries[-max_lines:]

    for line in visible:
        ts = font_sm.render(line, True, TEXT_VALUE)
        surface.blit(ts, (log_x, log_y))
        log_y += line_h
        if log_y > y0 + h - pad:
            break


def render(surface, font, font_sm, state, rect, sub_tab, config=None):
    if sub_tab == 0:
        stale_age = config.stale_value_age_sec if config else STALE_VALUE_AGE_SEC
        draw_values(surface, font, font_sm, state, rect, stale_age)
    elif sub_tab == 1:
        draw_nmea_log(surface, font, font_sm, state, rect)


def handle_click(state, mx, my, rect, sub_tab):
    pass


def handle_key(state, key, sub_tab):
    if key == pygame.K_RIGHTBRACKET:
        state.heading_offset += HEADING_OFFSET_INCREMENT_DEG
    elif key == pygame.K_LEFTBRACKET:
        state.heading_offset -= HEADING_OFFSET_INCREMENT_DEG
