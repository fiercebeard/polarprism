import math
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
    VARIATION_DELTA_WARN_DEG,
    State,
    angle_diff,
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


def draw_values(surface, font, font_sm, state, rect):
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
            src = state.sources.get(signal_key, "")
            dev = state.device_names.get(src, src) if src else ""
            row_kwargs: dict[str, Any] = {
                "label_x": x + 4,
                "value_x": x + 140,
            }
            if fmt_type != "wind_combined" and not fmt_type.endswith("_opt"):
                row_kwargs["detail"] = dev
                row_kwargs["detail_x"] = x + 260
                row_kwargs["detail_color"] = src_color
            draw_row(surface, font_sm, x, y, label, value_str, **row_kwargs)
            y += ROW_H

    hm = state.values.get("headingMagnetic")
    mv = state.values.get("magneticVariation")
    cog = filtered_value(state, "cogTrue")
    sog = filtered_value(state, "speedOverGround")
    stw = state.values.get("speedThroughWater")
    ap_target = state.values.get("apTargetMagnetic")

    derived_ht = None
    if hm is not None and mv is not None:
        derived_ht = norm_angle(hm + mv + math.radians(state.heading_offset))

    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- CALC: Heading Error ---")
    y += ROW_H - 2

    if derived_ht is not None:
        calc_label = "TRUE HDG"
        calc_src = "(CALC: Mag+Var)"
    elif hm is not None:
        calc_label = "MAG HDG"
        calc_src = "(no variation)"
        derived_ht = hm
    else:
        calc_label = None

    if derived_ht is not None and cog is not None:
        hdg_err = angle_diff(cog, derived_ht)
        hdg_err_deg = math.degrees(hdg_err)
        sog_kts = (sog or 0) * MS_TO_KNOTS
        stw_kts = (stw or 0) * MS_TO_KNOTS
        draw_row(
            surface,
            font_sm,
            x,
            y,
            f"{calc_label}:",
            f"{rad_to_deg(derived_ht):06.1f}\u00b0",
            label_x=x + 4,
            value_x=x + 140,
            color=calc_color,
            detail=calc_src,
            detail_color=dim_color,
        )
        y += ROW_H
        draw_row(
            surface,
            font_sm,
            x,
            y,
            "COG TRUE:",
            f"{rad_to_deg(cog):06.1f}\u00b0",
            label_x=x + 4,
            value_x=x + 140,
            detail="(measured)",
            detail_color=dim_color,
        )
        y += ROW_H
        hdg_warn = abs(hdg_err_deg) > HDG_ERROR_WARN_DEG and sog_kts > HDG_ERROR_WARN_SPEED_KTS
        row_color = warn_color if hdg_warn else val_color
        draw_row(
            surface,
            font_sm,
            x,
            y,
            "HDG ERROR:",
            f"{hdg_err_deg:+.1f}\u00b0",
            label_x=x + 4,
            value_x=x + 140,
            color=row_color,
            detail="COG-Heading" if abs(hdg_err_deg) < 180 else "wrap?",
            detail_color=dim_color,
        )
        y += ROW_H

        if sog_kts > CURRENT_LEEWAY_MIN_SOG_KTS and stw_kts > CURRENT_LEEWAY_MIN_STW_KTS:
            current_drift = stw_kts * abs(math.sin(hdg_err)) / max(sog_kts, DRIFT_CALC_MIN_SOG_KTS)
            leeway_est = math.degrees(
                math.asin(
                    min(
                        1,
                        max(-1, math.sin(hdg_err) * sog_kts / max(stw_kts, DRIFT_CALC_MIN_SOG_KTS)),
                    )
                )
            )
            draw_row(
                surface,
                font_sm,
                x,
                y,
                "CALC: Current:",
                f"{abs(sog_kts - stw_kts):.1f} kts",
                label_x=x + 4,
                value_x=x + 140,
                detail="set" if abs(sog_kts - stw_kts) > 1 else "light",
                detail_color=dim_color,
            )
            y += ROW_H
            draw_row(
                surface,
                font_sm,
                x,
                y,
                "CALC: Drift:",
                f"{current_drift:.1f} kts",
                label_x=x + 4,
                value_x=x + 140,
                detail=f"{math.degrees(hdg_err):+.0f}\u00b0 set",
                detail_color=dim_color,
            )
            y += ROW_H
            draw_row(
                surface,
                font_sm,
                x,
                y,
                "CALC: Leeway:",
                f"{leeway_est:+.1f}\u00b0",
                label_x=x + 4,
                value_x=x + 140,
                detail="(est from hdg-COG)",
                detail_color=dim_color,
            )
            y += ROW_H
        elif sog_kts > CURRENT_LEEWAY_MIN_SOG_KTS:
            draw_row(
                surface,
                font_sm,
                x,
                y,
                "CALC: Leeway:",
                f"{hdg_err_deg:+.1f}\u00b0 (incl. current)",
                label_x=x + 4,
                value_x=x + 140,
                detail="(no STW)",
                detail_color=dim_color,
            )
            y += ROW_H
        else:
            draw_row(
                surface,
                font_sm,
                x,
                y,
                "SOG:",
                f"{sog_kts:.1f} kts",
                label_x=x + 4,
                value_x=x + 140,
                detail="too slow for calc",
                detail_color=dim_color,
            )
            y += ROW_H

    if hm is not None and cog is not None:
        mag_cog = math.degrees(angle_diff(hm, cog))
        draw_row(
            surface,
            font_sm,
            x,
            y,
            "CALC: Mag-COG:",
            f"{mag_cog:+.1f}\u00b0",
            label_x=x + 4,
            value_x=x + 140,
            detail="(includes variation+leeway+current)",
            detail_color=dim_color,
        )
        y += ROW_H

    if hm is not None and mv is not None and ap_target is not None:
        ap_true = norm_angle(ap_target + mv)
        if derived_ht is not None:
            ap_off = math.degrees(angle_diff(ap_true, derived_ht))
            draw_row(
                surface,
                font_sm,
                x,
                y,
                "CALC: AP off hdg:",
                f"{ap_off:+.1f}\u00b0",
                label_x=x + 4,
                value_x=x + 140,
                detail="to port" if ap_off > 0 else "to stbd",
                detail_color=dim_color,
            )
            y += ROW_H

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
                value_x=x + 140,
                detail=f"({src})",
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
            value_x=x + 140,
            color=row_color,
            detail="EXCESSIVE" if delta_warn else "OK",
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
        value_x=x + 140,
        detail="[\u200b]/] to adjust",
        detail_color=dim_color,
    )


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


def render(surface, font, font_sm, state, rect, sub_tab):
    if sub_tab == 0:
        draw_values(surface, font, font_sm, state, rect)
    elif sub_tab == 1:
        draw_nmea_log(surface, font, font_sm, state, rect)


def handle_click(state, mx, my, rect, sub_tab):
    pass


def handle_key(state, key, sub_tab):
    if key == pygame.K_RIGHTBRACKET:
        state.heading_offset += HEADING_OFFSET_INCREMENT_DEG
    elif key == pygame.K_LEFTBRACKET:
        state.heading_offset -= HEADING_OFFSET_INCREMENT_DEG
