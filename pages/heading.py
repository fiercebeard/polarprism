import math
from typing import Any

import pygame

from pages.diagnostics import _format_diag_value
from pages.ui import draw_heading, draw_row
from signalk.models import (
    CURRENT_LEEWAY_MIN_SOG_KTS,
    CURRENT_LEEWAY_MIN_STW_KTS,
    DRIFT_CALC_MIN_SOG_KTS,
    HDG_ERROR_WARN_DEG,
    HDG_ERROR_WARN_SPEED_KTS,
    HEADING_OFFSET_INCREMENT_DEG,
    MS_TO_KNOTS,
    angle_diff,
    derive_true_heading,
    filtered_value,
    norm_angle,
    rad_to_deg,
    rad_to_deg_signed,
)
from theme import (
    BG,
    CALC,
    COMPASS_CENTER_INNER,
    COMPASS_CENTER_OUTER,
    COMPASS_FILL,
    COMPASS_RING,
    COMPASS_RING_BORDER,
    COMPASS_TICK,
    SIGNAL_COLORS,
    TEXT_DIM,
    TEXT_SRC,
    TEXT_VALUE,
    TEXT_WHITE,
    WARN,
)


def draw_compass(surface, font, font_sm, state, rect):
    x, y, w, h = rect
    cx = x + w // 2
    r = min(w, h) // 2 - 60
    cy = y + r + 30

    pygame.draw.circle(surface, COMPASS_RING, (cx, cy), r + 6)
    pygame.draw.circle(surface, COMPASS_RING_BORDER, (cx, cy), r + 6, 2)
    pygame.draw.circle(surface, COMPASS_FILL, (cx, cy), r)

    for deg in range(0, 360, 1):
        a_rad = math.radians(deg) - math.pi / 2
        if deg % 30 == 0:
            inner = r - 22
            lw = 2
            lbl = f"{deg}"
            if deg == 0:
                lbl = "N"
            elif deg == 90:
                lbl = "E"
            elif deg == 180:
                lbl = "S"
            elif deg == 270:
                lbl = "W"
            lx = cx + math.cos(a_rad) * (r - 38)
            ly = cy + math.sin(a_rad) * (r - 38)
            ts = font.render(lbl, True, TEXT_WHITE)
            surface.blit(ts, (lx - ts.get_width() // 2, ly - ts.get_height() // 2))
        elif deg % 10 == 0:
            inner = r - 14
            lw = 1
        elif deg % 5 == 0:
            inner = r - 9
            lw = 1
        else:
            continue
        outer = r - 2
        x1 = cx + math.cos(a_rad) * inner
        y1 = cy + math.sin(a_rad) * inner
        x2 = cx + math.cos(a_rad) * outer
        y2 = cy + math.sin(a_rad) * outer
        pygame.draw.line(surface, COMPASS_TICK, (x1, y1), (x2, y2), lw)

    angle_keys = ["headingMagnetic", "headingTrue", "cogTrue", "apTargetMagnetic"]

    for key in angle_keys:
        if key == "headingTrue":
            val = derive_true_heading(state)
        elif key in ("cogTrue", "speedOverGround"):
            val = filtered_value(state, key)
        else:
            val = state.values.get(key)
        if val is None:
            continue
        color = SIGNAL_COLORS[key]
        a = val - math.pi / 2
        tip_x = cx + math.cos(a) * (r - 5)
        tip_y = cy + math.sin(a) * (r - 5)
        tail_len = r * 0.15
        tail_x = cx - math.cos(a) * tail_len
        tail_y = cy - math.sin(a) * tail_len
        mid_x = cx + math.cos(a) * (r * 0.7)
        mid_y = cy + math.sin(a) * (r * 0.7)
        perp_a = a + math.pi / 2
        hw = 10
        p1 = (mid_x + math.cos(perp_a) * hw, mid_y + math.sin(perp_a) * hw)
        p2 = (mid_x - math.cos(perp_a) * hw, mid_y - math.sin(perp_a) * hw)
        pygame.draw.polygon(surface, color, [(tip_x, tip_y), p1, p2])
        pygame.draw.line(surface, color, (tail_x, tail_y), (cx, cy), 2)
        pygame.draw.circle(
            surface, color, (int(cx + math.cos(a) * (r + 16)), int(cy + math.sin(a) * (r + 16))), 4
        )

    mv = state.values.get("magneticVariation")
    if mv is not None:
        color = SIGNAL_COLORS["magneticVariation"]
        start_a = -math.pi / 2
        end_a = mv - math.pi / 2
        if abs(mv) > 0.001:
            arc_r = r + 16
            n_pts = max(10, int(abs(math.degrees(mv)) * 2))
            pts = []
            for i in range(n_pts + 1):
                t = start_a + (end_a - start_a) * i / n_pts
                pts.append((cx + math.cos(t) * arc_r, cy + math.sin(t) * arc_r))
            if len(pts) >= 2:
                pygame.draw.lines(surface, color, False, pts, 2)
                label_a = (start_a + end_a) / 2
                lx2 = cx + math.cos(label_a) * (arc_r + 14)
                ly2 = cy + math.sin(label_a) * (arc_r + 14)
                deg_lbl = f"{rad_to_deg_signed(mv):.1f}\u00b0"
                ts2 = font_sm.render(deg_lbl, True, color)
                surface.blit(ts2, (lx2 - ts2.get_width() // 2, ly2 - ts2.get_height() // 2))

    pygame.draw.circle(surface, COMPASS_CENTER_OUTER, (cx, cy), 6)
    pygame.draw.circle(surface, COMPASS_CENTER_INNER, (cx, cy), 4)

    hm = state.values.get("headingMagnetic")
    ht = derive_true_heading(state)
    cog = filtered_value(state, "cogTrue")
    sog = filtered_value(state, "speedOverGround")
    stw = state.values.get("speedThroughWater")
    mv = state.values.get("magneticVariation")

    readout_y = cy + r + 20
    readout_h = 28

    primary = ht if ht is not None else hm
    primary_str = f"{rad_to_deg(primary):06.1f}\u00b0" if primary is not None else "---\u00b0"
    ts_primary = font.render(primary_str, True, TEXT_WHITE)
    surface.blit(ts_primary, (cx - ts_primary.get_width() // 2, readout_y))
    readout_y += readout_h

    hm_str = f"MAG {rad_to_deg(hm):06.1f}\u00b0" if hm is not None else "MAG ---\u00b0"
    ts = font_sm.render(hm_str, True, SIGNAL_COLORS["headingMagnetic"])
    surface.blit(ts, (x + 8, readout_y))
    cog_str = f"COG {rad_to_deg(cog):06.1f}\u00b0" if cog is not None else "COG ---\u00b0"
    ts = font_sm.render(cog_str, True, SIGNAL_COLORS["cogTrue"])
    surface.blit(ts, (cx + 10, readout_y))
    readout_y += readout_h

    sog_str = f"SOG {(sog or 0) * MS_TO_KNOTS:.1f} kts" if sog is not None else "SOG --- kts"
    ts = font_sm.render(sog_str, True, TEXT_VALUE)
    surface.blit(ts, (x + 8, readout_y))
    stw_str = f"STW {(stw or 0) * MS_TO_KNOTS:.1f} kts" if stw is not None else "STW --- kts"
    ts = font_sm.render(stw_str, True, TEXT_VALUE)
    surface.blit(ts, (cx + 10, readout_y))
    readout_y += readout_h

    var_str = f"VAR {rad_to_deg_signed(mv):+.1f}\u00b0" if mv is not None else "VAR ---\u00b0"
    ts = font_sm.render(var_str, True, SIGNAL_COLORS["magneticVariation"])
    surface.blit(ts, (x + 8, readout_y))


def draw_headings(surface, font, font_sm, state, rect):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))

    row_h = 22
    y = y0 + 8

    hm = state.values.get("headingMagnetic")
    ht = derive_true_heading(state)
    cog = filtered_value(state, "cogTrue")
    sog = filtered_value(state, "speedOverGround")
    stw = state.values.get("speedThroughWater")
    mv = state.values.get("magneticVariation")
    rot = state.values.get("rateOfTurn")
    ap_target = state.values.get("apTargetMagnetic")

    draw_heading(surface, font_sm, x + 4, y, "--- Headings ---")
    y += row_h

    heading_items = [
        ("headingMagnetic", "MAG HDG", hm, "deg6"),
        ("headingTrue", "TRUE HDG", ht, "deg6"),
        ("cogTrue", "COG TRUE", cog, "deg6"),
    ]

    for key, label, val, fmt_type in heading_items:
        color = SIGNAL_COLORS.get(key, TEXT_WHITE)
        src = state.sources.get(key, "") if key != "headingTrue" else ""
        dev = state.device_names.get(src, src) if src else ""
        value_str = _format_diag_value(fmt_type, val, state)
        row_kwargs: dict[str, Any] = {
            "label_x": x + 4,
            "value_x": x + 140,
            "color": color,
        }
        if dev:
            row_kwargs["detail"] = dev
            row_kwargs["detail_x"] = x + 260
            row_kwargs["detail_color"] = TEXT_SRC
        draw_row(surface, font_sm, x, y, f"{label}:", value_str, **row_kwargs)
        y += row_h

    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- Derived ---")
    y += row_h

    derived_ht = None
    if hm is not None and mv is not None:
        derived_ht = norm_angle(hm + mv + math.radians(state.heading_offset))
        draw_row(
            surface,
            font_sm,
            x,
            y,
            "Mag+Var:",
            f"{rad_to_deg(derived_ht):06.1f}\u00b0",
            label_x=x + 4,
            value_x=x + 140,
            color=CALC,
            detail=f"offset {state.heading_offset:+.1f}\u00b0",
            detail_x=x + 260,
            detail_color=TEXT_DIM,
        )
        y += row_h

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
            "HDG ERROR:",
            f"{hdg_err_deg:+.1f}\u00b0",
            label_x=x + 4,
            value_x=x + 140,
            color=WARN
            if abs(hdg_err_deg) > HDG_ERROR_WARN_DEG and sog_kts > HDG_ERROR_WARN_SPEED_KTS
            else TEXT_VALUE,
            detail="COG-Heading",
            detail_x=x + 260,
            detail_color=TEXT_DIM,
        )
        y += row_h

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
                "Drift:",
                f"{current_drift:.1f} kts",
                label_x=x + 4,
                value_x=x + 140,
                color=CALC,
                detail=f"{math.degrees(hdg_err):+.0f}\u00b0 set",
                detail_x=x + 260,
                detail_color=TEXT_DIM,
            )
            y += row_h
            draw_row(
                surface,
                font_sm,
                x,
                y,
                "Leeway:",
                f"{leeway_est:+.1f}\u00b0",
                label_x=x + 4,
                value_x=x + 140,
                color=CALC,
                detail="(est from hdg-COG)",
                detail_x=x + 260,
                detail_color=TEXT_DIM,
            )
            y += row_h

    if hm is not None and cog is not None:
        mag_cog = math.degrees(angle_diff(hm, cog))
        draw_row(
            surface,
            font_sm,
            x,
            y,
            "Mag-COG:",
            f"{mag_cog:+.1f}\u00b0",
            label_x=x + 4,
            value_x=x + 140,
            color=CALC,
        )
        y += row_h

    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- Navigation ---")
    y += row_h

    nav_items = [
        ("magneticVariation", "MAG VAR", mv, "deg_signed2"),
        ("rateOfTurn", "ROT", rot, "rot"),
        ("speedOverGround", "SOG", sog, "speed_kts"),
        ("speedThroughWater", "STW", stw, "speed_kts"),
    ]

    for key, label, val, fmt_type in nav_items:
        color = SIGNAL_COLORS.get(key, TEXT_VALUE)
        src = state.sources.get(key, "")
        dev = state.device_names.get(src, src) if src else ""
        value_str = _format_diag_value(fmt_type, val, state)
        row_kwargs: dict[str, Any] = {
            "label_x": x + 4,
            "value_x": x + 140,
            "color": color,
        }
        if dev:
            row_kwargs["detail"] = dev
            row_kwargs["detail_x"] = x + 260
            row_kwargs["detail_color"] = TEXT_SRC
        draw_row(surface, font_sm, x, y, f"{label}:", value_str, **row_kwargs)
        y += row_h

    if hm is not None and mv is not None and ap_target is not None:
        ap_true = norm_angle(ap_target + mv)
        if derived_ht is not None:
            ap_off = math.degrees(angle_diff(ap_true, derived_ht))
            draw_row(
                surface,
                font_sm,
                x,
                y,
                "AP off hdg:",
                f"{ap_off:+.1f}\u00b0",
                label_x=x + 4,
                value_x=x + 140,
                color=SIGNAL_COLORS.get("apTargetMagnetic", TEXT_VALUE),
                detail="to port" if ap_off > 0 else "to stbd",
                detail_x=x + 260,
                detail_color=TEXT_DIM,
            )
            y += row_h

    y += 4
    draw_heading(surface, font_sm, x + 4, y, "--- Hdg Offset ---")
    y += row_h
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
        detail_x=x + 260,
        detail_color=TEXT_DIM,
    )


def render(surface, font, font_sm, state, rect, sub_tab):
    if sub_tab == 0:
        draw_compass(surface, font, font_sm, state, rect)
    elif sub_tab == 1:
        draw_headings(surface, font, font_sm, state, rect)


def handle_click(state, mx, my, rect, sub_tab):
    pass


def handle_key(state, key, sub_tab):
    if key == pygame.K_RIGHTBRACKET:
        state.heading_offset += HEADING_OFFSET_INCREMENT_DEG
    elif key == pygame.K_LEFTBRACKET:
        state.heading_offset -= HEADING_OFFSET_INCREMENT_DEG
