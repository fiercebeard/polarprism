import math
import time

import pygame

from polars.parser import (
    calc_vmc,
    calc_vmg,
    compute_true_wind,
    lookup_recommended_sail,
    lookup_speed,
)
from signalk.models import MS_TO_KNOTS, derive_true_heading, rad_to_deg, toggle_sail
from theme import (
    BTN_ACTIVE_BG,
    BTN_ACTIVE_BORDER,
    BTN_BG,
    BTN_BORDER,
    CALC,
    OK,
    POLAR_BOAT_DOT,
    POLAR_FILL,
    POLAR_GRID,
    POLAR_RING,
    POLAR_TARGET_DOT,
    SAILING_ACTIVE,
    SAILING_INACTIVE,
    SECTION,
    TEXT_DIM,
    TEXT_LABEL,
    TEXT_MUTED,
    TEXT_VALUE,
    TEXT_WHITE,
    TWS_COLORS,
    WARN,
    WP_ACTION,
    WP_ADJUST,
    WP_HOLD,
    WP_LINE,
    WP_VMC_DOT,
    WP_VMG_DOT,
)

REC_REFRESH_SECONDS = 5.0
"""How long the polar-page recommendation box holds its text before being
recomputed. The numeric Performance/VMG/Waypoint rows still update every
frame; this throttle only applies to the TACK/HEAD UP/HOLD prose so it
stays readable instead of flipping while you read it."""

REC_OVERLAY_HEIGHT = 44
REC_OVERLAY_MAX_WIDTH = 280
REC_OVERLAY_BOTTOM_MARGIN = 6


def _current_wind_kts(state):
    """Current wind speed in knots, preferring TWS over AWS. Returns None if neither available."""
    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    _, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)
    if tws_ms is not None:
        return tws_ms * MS_TO_KNOTS
    if aws_ms is not None:
        return aws_ms * MS_TO_KNOTS
    return None


def _get_route_waypoint_bearing(state):
    if not state.route_active or not state.routes:
        return None
    return state.route_next_wp_bearing_rad


def _get_waypoint_bearing(state):
    rb = _get_route_waypoint_bearing(state)
    if rb is not None:
        return rb
    for key in (
        "calcBearingTrue",
        "nextPointBearingTrue",
        "gcNextPointBearingTrue",
        "courseBearingTrue",
        "courseRhumblineBearingTrue",
    ):
        v = state.values.get(key)
        if v is not None:
            return v
    return None


def _compute_polar_recommendation(state, polar):
    """Pure computation of the polar-page recommendation prose.

    Returns a dict ``{"line1": str, "line2": str, "color": tuple}`` or
    ``None`` if there is not enough data to produce any recommendation.
    Drawn separately (and throttled) by the caller so the text holds
    steady long enough to read instead of flipping every frame.
    """
    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)
    if twa_rad is None or tws_ms is None:
        return None

    twa_deg = math.degrees(twa_rad)
    tws_kts_v = tws_ms * MS_TO_KNOTS
    stw_kts = (stw_ms or 0) * MS_TO_KNOTS

    wp_brg_rad = _get_waypoint_bearing(state)
    ht_val = derive_true_heading(state)
    ht_deg = rad_to_deg(ht_val) if ht_val is not None else None
    twd_deg = (ht_deg + math.degrees(twa_rad)) % 360 if ht_deg is not None else None

    if wp_brg_rad is not None and ht_deg is not None and twd_deg is not None:
        wp_brg_deg = rad_to_deg(wp_brg_rad)
        course_twa_deg = (wp_brg_deg - twd_deg) % 360
        if course_twa_deg > 180:
            course_twa_deg -= 360
        vmc_data = calc_vmc(polar, tws_kts_v, course_twa_deg)
    else:
        course_twa_deg = None
        vmc_data = None

    if vmc_data is not None and ht_deg is not None and twd_deg is not None:
        current_tack = "starboard" if twa_deg >= 0 else "port"
        best_tack = vmc_data["best_tack"]
        hdg_to_sail = (twd_deg + vmc_data["best_twa"]) % 360
        if best_tack != current_tack:
            action = "TACK" if abs(vmc_data["best_twa"]) < 90 else "GYBE"
            line1 = f"{action} \u2192 sail {hdg_to_sail:.0f}\u00b0T"
            current_vmc = stw_kts * math.cos(math.radians(twa_deg - course_twa_deg))
            improvement = vmc_data["best_vmc"] - current_vmc
            line2 = f"VMC {vmc_data['best_vmc']:.1f} kts (+{improvement:.1f})"
            return {"line1": line1, "line2": line2, "color": WP_ACTION}
        heading_diff = (hdg_to_sail - ht_deg + 180) % 360 - 180
        if abs(heading_diff) < 5:
            return {
                "line1": f"HOLD {hdg_to_sail:.0f}\u00b0T \u2713",
                "line2": f"VMC {vmc_data['best_vmc']:.1f} kts",
                "color": WP_HOLD,
            }
        if heading_diff > 0:
            line1 = f"HEAD UP {abs(heading_diff):.0f}\u00b0 \u2192 {hdg_to_sail:.0f}\u00b0T"
        else:
            line1 = f"BEAR AWAY {abs(heading_diff):.0f}\u00b0 \u2192 {hdg_to_sail:.0f}\u00b0T"
        return {
            "line1": line1,
            "line2": f"VMC {vmc_data['best_vmc']:.1f} kts",
            "color": WP_ADJUST,
        }

    vmg_data = calc_vmg(polar, tws_kts_v)
    if vmg_data is not None and vmc_data is None:
        abs_twa = abs(twa_deg)
        if abs_twa < 90 and "upwind_twa" in vmg_data:
            diff = abs_twa - vmg_data["upwind_twa"]
            if diff > 10:
                return {
                    "line1": f"HEAD UP {diff:.0f}\u00b0 for VMG",
                    "line2": f"Best at {vmg_data['upwind_twa']:.0f}\u00b0 ({vmg_data['upwind_vmg']:.1f} kts)",
                    "color": WP_ADJUST,
                }
            return {
                "line1": "On good VMG angle",
                "line2": "",
                "color": WP_HOLD,
            }
        if abs_twa >= 90 and "downwind_twa" in vmg_data:
            diff = abs_twa - vmg_data["downwind_twa"]
            if abs(diff) > 10:
                if diff > 0:
                    line1 = f"BEAR AWAY {abs(diff):.0f}\u00b0 for VMG"
                else:
                    line1 = f"HEAD UP {abs(diff):.0f}\u00b0 for VMG"
                return {
                    "line1": line1,
                    "line2": f"Best at {vmg_data['downwind_twa']:.0f}\u00b0 ({vmg_data['downwind_vmg']:.1f} kts)",
                    "color": WP_ADJUST,
                }
            return {
                "line1": "On good VMG angle",
                "line2": "",
                "color": WP_HOLD,
            }
        return {"line1": "Sail on", "line2": "", "color": TEXT_MUTED}

    return None


def _cached_polar_recommendation(state, polar):
    """Return the (possibly cached) recommendation dict, recomputing at most
    every REC_REFRESH_SECONDS. The very first call after data becomes valid
    computes immediately so the box appears without delay.
    """
    now = time.monotonic()
    if not state._polar_rec_computed or now - state._polar_rec_ts >= REC_REFRESH_SECONDS:
        state._polar_rec_cache = _compute_polar_recommendation(state, polar) or {}
        state._polar_rec_ts = now
        state._polar_rec_computed = True
    return state._polar_rec_cache or None


def _draw_rec_box(surface, font_sm, x, y, w, line1, line2, color):
    """Draw the recommendation box at the given top-left. Returns box height."""
    try:
        box_surf = pygame.Surface((w, REC_OVERLAY_HEIGHT), pygame.SRCALPHA)
        pygame.draw.rect(box_surf, (*color, 30), (0, 0, w, REC_OVERLAY_HEIGHT), border_radius=4)
        surface.blit(box_surf, (x, y))
    except Exception:
        pass
    rec_box = pygame.Rect(x, y, w, REC_OVERLAY_HEIGHT)
    pygame.draw.rect(surface, color, rec_box, 1, border_radius=4)
    t1 = font_sm.render(line1, True, color)
    surface.blit(t1, (x + 6, y + 3))
    if line2:
        t2 = font_sm.render(line2, True, color)
        surface.blit(t2, (x + 6, y + 19))
    return REC_OVERLAY_HEIGHT


def draw_polar_rose(surface, font, font_sm, state, rect):
    x, y, w, h = rect
    polar = state.polar_data.get(state.polar_active)
    if polar is None:
        ts = font.render("No polar loaded", True, TEXT_MUTED)
        surface.blit(ts, (x + w // 2 - ts.get_width() // 2, y + h // 2 - 10))
        return

    chart_w = int(w * 0.60)
    chart_h = h
    cx = x + chart_w // 2
    cy = y + chart_h // 2
    r = min(chart_w, chart_h) // 2 - 20

    max_speed = 0.0
    for twa in polar.twa_list:
        for tws in polar.tws_list:
            spd = polar.speed_grid.get(twa, {}).get(tws, 0.0)
            if spd > max_speed:
                max_speed = spd
    max_speed = math.ceil(max_speed / 2) * 2
    if max_speed < 2:
        max_speed = 10
    speed_step = 2

    pygame.draw.circle(surface, POLAR_FILL, (cx, cy), r)

    for s in range(speed_step, int(max_speed) + 1, speed_step):
        ring_r = int(r * s / max_speed)
        if ring_r > 0:
            pygame.draw.circle(surface, POLAR_RING, (cx, cy), ring_r, 1)
            lbl = font_sm.render(f"{s}", True, TEXT_DIM)
            surface.blit(lbl, (cx + 2, cy - ring_r - lbl.get_height()))

    for a_deg in range(0, 360, 30):
        a_rad = math.radians(a_deg) - math.pi / 2
        ex = cx + math.cos(a_rad) * r
        ey = cy + math.sin(a_rad) * r
        pygame.draw.line(surface, POLAR_GRID, (cx, cy), (int(ex), int(ey)), 1)
        lbl_map = {
            0: "B",
            30: "30",
            60: "60",
            90: "90",
            120: "120",
            150: "150",
            180: "180",
            210: "150",
            240: "120",
            270: "90",
            300: "60",
            330: "30",
        }
        lbl_text = lbl_map.get(a_deg, "")
        if lbl_text:
            lx = cx + math.cos(a_rad) * (r + 14)
            ly = cy + math.sin(a_rad) * (r + 14)
            lbl = font_sm.render(lbl_text, True, TEXT_DIM)
            surface.blit(lbl, (int(lx - lbl.get_width() // 2), int(ly - lbl.get_height() // 2)))

    active_tws_idx = state.polar_tws_index
    if active_tws_idx >= len(polar.tws_list):
        active_tws_idx = len(polar.tws_list) - 1

    for ti, tws in enumerate(polar.tws_list):
        color = TWS_COLORS[ti % len(TWS_COLORS)]
        is_active = ti == active_tws_idx
        lw = 3 if is_active else 1
        pts_port = []
        pts_stbd = []
        for twa_deg in polar.twa_list:
            spd = polar.speed_grid.get(twa_deg, {}).get(tws, 0.0)
            if spd <= 0:
                continue
            pr = r * spd / max_speed
            a_rad = math.radians(twa_deg) - math.pi / 2
            px = cx + math.cos(a_rad) * pr
            py = cy + math.sin(a_rad) * pr
            pts_port.append((px, py))
            a_rad_s = math.radians(-twa_deg) - math.pi / 2
            sx = cx + math.cos(a_rad_s) * pr
            sy = cy + math.sin(a_rad_s) * pr
            pts_stbd.append((sx, sy))

        if is_active and len(pts_port) > 2:
            fill_pts = pts_port + list(reversed(pts_stbd))
            fill_surf = pygame.Surface((w, h), pygame.SRCALPHA)
            shifted = [(p[0] - x, p[1] - y) for p in fill_pts]
            try:
                pygame.draw.polygon(fill_surf, (*color, 30), shifted)
                surface.blit(fill_surf, (x, y))
            except Exception:
                pass

        if len(pts_port) > 1:
            pygame.draw.lines(surface, color, False, [(int(p[0]), int(p[1])) for p in pts_port], lw)
        if len(pts_stbd) > 1:
            pygame.draw.lines(surface, color, False, [(int(p[0]), int(p[1])) for p in pts_stbd], lw)

    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)

    if twa_rad is not None and tws_ms is not None:
        twa_deg = math.degrees(twa_rad)
        tws_kts_val = tws_ms * MS_TO_KNOTS
        target_spd = lookup_speed(polar, abs(twa_deg), tws_kts_val)
        stw_kts = (stw_ms or 0) * MS_TO_KNOTS

        if target_spd is not None and target_spd > 0:
            tr = r * target_spd / max_speed
            ta_rad = math.radians(abs(twa_deg)) - math.pi / 2
            tx = cx + math.cos(ta_rad) * tr
            ty = cy + math.sin(ta_rad) * tr
            pygame.draw.circle(surface, POLAR_TARGET_DOT, (int(tx), int(ty)), 5)

            if stw_ms is not None:
                ar = r * stw_kts / max_speed
                ax = cx + math.cos(ta_rad) * ar
                ay = cy + math.sin(ta_rad) * ar
                pygame.draw.circle(surface, POLAR_BOAT_DOT, (int(ax), int(ay)), 5)
                pygame.draw.line(surface, POLAR_BOAT_DOT, (int(tx), int(ty)), (int(ax), int(ay)), 1)

            ta_rad_s = math.radians(-abs(twa_deg)) - math.pi / 2
            tx_s = cx + math.cos(ta_rad_s) * tr
            ty_s = cy + math.sin(ta_rad_s) * tr
            pygame.draw.circle(surface, POLAR_TARGET_DOT, (int(tx_s), int(ty_s)), 5)
            if stw_ms is not None:
                ax_s = cx + math.cos(ta_rad_s) * ar
                ay_s = cy + math.sin(ta_rad_s) * ar
                pygame.draw.circle(surface, POLAR_BOAT_DOT, (int(ax_s), int(ay_s)), 5)

    wp_brg_rad = _get_waypoint_bearing(state)
    ht_val = derive_true_heading(state)
    ht_deg = rad_to_deg(ht_val) if ht_val is not None else None
    if twa_rad is not None and tws_ms is not None and ht_deg is not None and wp_brg_rad is not None:
        wp_brg_deg = rad_to_deg(wp_brg_rad)
        twd_deg = (ht_deg + math.degrees(twa_rad)) % 360
        course_twa_deg = (wp_brg_deg - twd_deg) % 360
        if course_twa_deg > 180:
            course_twa_deg -= 360
        tws_kts_wp = tws_ms * MS_TO_KNOTS
        vmc_data = calc_vmc(polar, tws_kts_wp, course_twa_deg)
        vmg_data = calc_vmg(polar, tws_kts_wp)

        wp_a_rad_port = math.radians(abs(course_twa_deg)) - math.pi / 2
        wp_a_rad_stbd = math.radians(-abs(course_twa_deg)) - math.pi / 2
        pygame.draw.line(
            surface,
            WP_LINE,
            (cx, cy),
            (int(cx + math.cos(wp_a_rad_port) * r), int(cy + math.sin(wp_a_rad_port) * r)),
            2,
        )
        pygame.draw.line(
            surface,
            WP_LINE,
            (cx, cy),
            (int(cx + math.cos(wp_a_rad_stbd) * r), int(cy + math.sin(wp_a_rad_stbd) * r)),
            2,
        )

        if vmc_data is not None:
            best_twa_abs = abs(vmc_data["best_twa"])
            best_spd = vmc_data["best_speed"]
            vr = r * best_spd / max_speed
            for sign in (1, -1):
                va_rad = math.radians(sign * best_twa_abs) - math.pi / 2
                vx = cx + math.cos(va_rad) * vr
                vy = cy + math.sin(va_rad) * vr
                sz = 6
                pts = [
                    (int(vx), int(vy - sz)),
                    (int(vx + sz), int(vy)),
                    (int(vx), int(vy + sz)),
                    (int(vx - sz), int(vy)),
                ]
                pygame.draw.polygon(surface, WP_VMC_DOT, pts)

        if vmg_data is not None:
            for key in ("upwind", "downwind"):
                twa_k = f"{key}_twa"
                spd_k = f"{key}_speed"
                if twa_k in vmg_data and spd_k in vmg_data:
                    vmg_twa = vmg_data[twa_k]
                    vmg_spd = vmg_data[spd_k]
                    vmg_r = r * vmg_spd / max_speed
                    for sign in (1, -1):
                        va_rad = math.radians(sign * vmg_twa) - math.pi / 2
                        vx = cx + math.cos(va_rad) * vmg_r
                        vy = cy + math.sin(va_rad) * vmg_r
                        pygame.draw.circle(surface, WP_VMG_DOT, (int(vx), int(vy)), 3)

    pygame.draw.circle(surface, TEXT_WHITE, (cx, cy), 3)

    _draw_rec_overlay(surface, font_sm, state, polar, x, y, chart_w, h)

    _draw_polar_panel(surface, font, font_sm, state, rect, chart_w, polar)


def _draw_rec_overlay(surface, font_sm, state, polar, x, y, chart_w, chart_h):
    """Draw the recommendation box as an overlay at the bottom-center of the
    polar rose chart area, so it is always visible regardless of how tall
    the right-hand data panel grows. The text is throttled via
    ``_cached_polar_recommendation`` so it holds steady long enough to read.
    """
    rec = _cached_polar_recommendation(state, polar)
    if not rec:
        return
    box_w = min(chart_w - 20, REC_OVERLAY_MAX_WIDTH)
    if box_w < 80:
        return
    box_x = x + chart_w // 2 - box_w // 2
    box_y = y + chart_h - REC_OVERLAY_HEIGHT - REC_OVERLAY_BOTTOM_MARGIN
    _draw_rec_box(surface, font_sm, box_x, box_y, box_w, rec["line1"], rec["line2"], rec["color"])


def _draw_polar_panel(surface, font, font_sm, state, rect, chart_w, polar):
    x, y, w, _h = rect
    px = x + chart_w + 10
    py = y + 8
    pw = w - chart_w - 20
    row_h = 22

    def heading(text):
        nonlocal py
        ts = font_sm.render(text, True, SECTION)
        surface.blit(ts, (px, py))
        py += row_h

    def row(label, val_str, color=TEXT_VALUE):
        nonlocal py
        tl = font_sm.render(label, True, TEXT_LABEL)
        tv = font_sm.render(val_str, True, color)
        surface.blit(tl, (px, py))
        surface.blit(tv, (px + 100, py))
        py += row_h

    heading("--- Polar Profile ---")
    for i, name in enumerate(state.polar_names):
        is_active = name == state.polar_active
        bg = BTN_ACTIVE_BG if is_active else BTN_BG
        border = BTN_ACTIVE_BORDER if is_active else BTN_BORDER
        btn = pygame.Rect(px, py, pw, 20)
        pygame.draw.rect(surface, bg, btn, border_radius=4)
        pygame.draw.rect(surface, border, btn, 1, border_radius=4)
        short = state.polar_display_names.get(name, name)
        tc = TEXT_WHITE if is_active else TEXT_MUTED
        tl = font_sm.render(f"{i + 1}:{short}", True, tc)
        surface.blit(tl, (px + 6, py + 2))
        py += 24

    py += 4
    heading("--- Wind Speed (TWS) ---")
    wind_kts = _current_wind_kts(state)
    wind_label = f"now: {wind_kts:.1f} kts" if wind_kts is not None else "now: ---"
    key_hint = font_sm.render(wind_label, True, TEXT_DIM)
    surface.blit(key_hint, (px + pw - key_hint.get_width() - 2, py - row_h + 4))
    btn_w = min(40, (pw - 10) // max(len(polar.tws_list), 1))
    for i, tws in enumerate(polar.tws_list):
        bx = px + i * (btn_w + 4)
        is_active = i == state.polar_tws_index
        bg = BTN_ACTIVE_BG if is_active else BTN_BG
        border = BTN_ACTIVE_BORDER if is_active else BTN_BORDER
        btn = pygame.Rect(bx, py, btn_w, 18)
        pygame.draw.rect(surface, bg, btn, border_radius=3)
        pygame.draw.rect(surface, border, btn, 1, border_radius=3)
        tc = TEXT_WHITE if is_active else TWS_COLORS[i % len(TWS_COLORS)]
        tl = font_sm.render(f"{tws:.0f}", True, tc)
        surface.blit(tl, (bx + btn_w // 2 - tl.get_width() // 2, py + 1))
    py += 26

    py += 4
    heading("--- Sails ---")
    for group_name, group_sails in state.sail_groups:
        group_label = font_sm.render(group_name.capitalize(), True, TEXT_DIM)
        surface.blit(group_label, (px + 2, py))
        py += 16
        for sail in group_sails:
            is_active = sail in state.active_sails
            bg = BTN_ACTIVE_BG if is_active else BTN_BG
            border_c = BTN_ACTIVE_BORDER if is_active else BTN_BORDER
            if is_active:
                border_c = state.sail_colors.get(sail, BTN_ACTIVE_BORDER)
            btn = pygame.Rect(px, py, pw, 20)
            pygame.draw.rect(surface, bg, btn, border_radius=4)
            pygame.draw.rect(surface, border_c, btn, 1, border_radius=4)
            sc = state.sail_colors.get(sail, TEXT_WHITE) if is_active else TEXT_MUTED
            tl = font_sm.render(sail, True, sc)
            surface.blit(tl, (px + 6, py + 2))
            py += 24

    py += 4
    heading("--- Logging ---")
    if state.sailing_log_active:
        dot_color = SAILING_ACTIVE
        status_text = "RECORDING"
    else:
        dot_color = SAILING_INACTIVE
        status_text = "STOPPED"
    pygame.draw.circle(surface, dot_color, (px + 8, py + 8), 6)
    ts = font_sm.render(status_text, True, dot_color)
    surface.blit(ts, (px + 20, py))
    py += 22

    btn_h = 26
    btn = pygame.Rect(px, py, pw, btn_h)
    btn_bg = (160, 40, 40) if state.sailing_log_active else (40, 120, 60)
    pygame.draw.rect(surface, btn_bg, btn, border_radius=4)
    pygame.draw.rect(surface, TEXT_WHITE, btn, 1, border_radius=4)
    btn_label = "STOP LOG [L]" if state.sailing_log_active else "START LOG [L]"
    bt = font_sm.render(btn_label, True, TEXT_WHITE)
    surface.blit(
        bt, (btn.x + btn.w // 2 - bt.get_width() // 2, btn.y + btn_h // 2 - bt.get_height() // 2)
    )
    py += btn_h + 6

    if state.sailing_log_active:
        row("Samples:", str(state.log_sample_count))
        if state.log_sample_count > 0:
            avg = state.log_perf_sum / state.log_sample_count
            pc = OK if avg >= 95 else (WARN if avg < 80 else TEXT_VALUE)
            row("Avg Perf:", f"{avg:.1f}%", pc)
        else:
            row("Avg Perf:", "---")
    else:
        row("Samples:", "0")

    py += 4
    heading("--- Recommended Sail ---")
    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)
    if twa_rad is not None and tws_ms is not None:
        twa_deg = math.degrees(twa_rad)
        tws_kts_v = tws_ms * MS_TO_KNOTS
        rec_sail = lookup_recommended_sail(
            state.sailselect, state.saildef, polar.twa_list, abs(twa_deg), tws_kts_v
        )
        if rec_sail:
            row("Sail:", rec_sail, state.sail_colors.get(rec_sail, TEXT_VALUE))
        else:
            row("Sail:", "---")
    else:
        row("Sail:", "(no wind)")

    py += 8
    heading("--- Performance ---")
    wp_brg_rad = _get_waypoint_bearing(state)
    ht_val = derive_true_heading(state)
    ht_deg = rad_to_deg(ht_val) if ht_val is not None else None
    course_twa_deg = None
    vmc_data = None
    vmg_data = None
    if twa_rad is not None and tws_ms is not None:
        twa_deg = math.degrees(twa_rad)
        tws_kts_v = tws_ms * MS_TO_KNOTS
        aws_kts_v = (aws_ms or 0) * MS_TO_KNOTS
        target = lookup_speed(polar, abs(twa_deg), tws_kts_v)
        stw_kts = (stw_ms or 0) * MS_TO_KNOTS
        row("TWA:", f"{abs(twa_deg):.1f}\u00b0")
        row("TWS:", f"{tws_kts_v:.1f} kts")
        row("AWS:", f"{aws_kts_v:.1f} kts")
        row("Target:", f"{target:.2f} kts" if target else "--- kts", CALC)
        row("Actual:", f"{stw_kts:.2f} kts", POLAR_BOAT_DOT)
        if target and target > 0 and stw_ms is not None:
            pct = stw_kts / target * 100
            pc = OK if pct >= 95 else (WARN if pct < 80 else TEXT_VALUE)
            row("Perf:", f"{pct:.1f}%", pc)
        else:
            row("Perf:", "---")
        for window in state.PERF_WINDOWS:
            avg = state.perf_averages.get(window)
            if avg is not None:
                label = f"{window}s avg:" if window < 60 else f"{window // 60}m avg:"
                n_samples = sum(1 for t, _ in state.perf_samples if t > time.time() - window)
                pc = OK if avg >= 95 else (WARN if avg < 80 else TEXT_VALUE)
                row(label, f"{avg:.1f}% ({n_samples})", pc)
            else:
                label = f"{window}s avg:" if window < 60 else f"{window // 60}m avg:"
                row(label, "---")
        twd_deg = (ht_deg + math.degrees(twa_rad)) % 360 if ht_deg is not None else None
        vmg_data = calc_vmg(polar, tws_kts_v)
        if wp_brg_rad is not None and ht_deg is not None and twd_deg is not None:
            wp_brg_deg = rad_to_deg(wp_brg_rad)
            course_twa_deg = (wp_brg_deg - twd_deg) % 360
            if course_twa_deg > 180:
                course_twa_deg -= 360
            vmc_data = calc_vmc(polar, tws_kts_v, course_twa_deg)
    else:
        row("TWA:", "---")
        row("TWS:", "---")
        row("AWS:", f"{(aws_ms or 0) * MS_TO_KNOTS:.1f} kts" if aws_ms is not None else "---")
        row("Target:", "---")
        row("Actual:", "---")
        row("Perf:", "---")
        twa_deg = None
        tws_kts_v = None
        stw_kts = None

    py += 8
    heading("--- VMG ---")
    if vmg_data is not None:
        if "upwind_twa" in vmg_data:
            row("Up TWA:", f"{vmg_data['upwind_twa']:.0f}\u00b0", CALC)
            row("Up VMG:", f"{vmg_data['upwind_vmg']:.1f} kts", CALC)
        else:
            row("Up TWA:", "---")
            row("Up VMG:", "---")
        if "downwind_twa" in vmg_data:
            row("Dn TWA:", f"{vmg_data['downwind_twa']:.0f}\u00b0", CALC)
            row("Dn VMG:", f"{vmg_data['downwind_vmg']:.1f} kts", CALC)
        else:
            row("Dn TWA:", "---")
            row("Dn VMG:", "---")
    else:
        row("Up TWA:", "---")
        row("Up VMG:", "---")
        row("Dn TWA:", "---")
        row("Dn VMG:", "---")

    py += 8
    heading("--- Waypoint ---")
    wp_dist = None
    for dk in ("calcDistance", "nextPointDistance", "gcNextPointDistance"):
        wp_dist = state.values.get(dk)
        if wp_dist is not None:
            break
    wp_xte = state.values.get("calcXTE") or state.values.get("gcXTE")
    sk_vmc = state.values.get("calcVMG") or state.values.get("gcNextPointVMG")
    if wp_brg_rad is not None:
        wp_brg_deg = rad_to_deg(wp_brg_rad)
        row("WP Brng:", f"{wp_brg_deg:.1f}\u00b0T", WP_LINE)
        if wp_dist is not None:
            if wp_dist > 1852:
                row("Distance:", f"{wp_dist / 1852:.2f} nm", WP_LINE)
            else:
                row("Distance:", f"{wp_dist:.0f} m", WP_LINE)
        else:
            row("Distance:", "---")
        if wp_xte is not None:
            row("XTE:", f"{wp_xte:.1f} m", WP_LINE)
        else:
            row("XTE:", "---")
        if course_twa_deg is not None:
            row("Course TWA:", f"{course_twa_deg:.1f}\u00b0", WP_LINE)
        else:
            row("Course TWA:", "---")
        if vmc_data is not None:
            row("VMC TWA:", f"{vmc_data['best_twa']:.1f}\u00b0", WP_VMC_DOT)
            row("VMC Speed:", f"{vmc_data['best_speed']:.1f} kts", WP_VMC_DOT)
            row("VMC:", f"{vmc_data['best_vmc']:.1f} kts", WP_VMC_DOT)
            if ht_deg is not None and twd_deg is not None:
                hdg_to_sail = (twd_deg + vmc_data["best_twa"]) % 360
                row("HDG to sail:", f"{hdg_to_sail:.1f}\u00b0T", WP_VMC_DOT)
            else:
                row("HDG to sail:", "---")
        else:
            row("VMC TWA:", "---")
            row("VMC Speed:", "---")
            row("VMC:", "---")
            row("HDG to sail:", "---")
        if sk_vmc is not None:
            row("SK VMG:", f"{abs(sk_vmc) * MS_TO_KNOTS:.1f} kts", WP_VMC_DOT)
        else:
            row("SK VMG:", "---")
    else:
        row("WP Brng:", "(no WP)")
        row("Distance:", "---")
        row("XTE:", "---")
        row("Course TWA:", "---")
        row("VMC TWA:", "---")
        row("VMC Speed:", "---")
        row("VMC:", "---")
        row("SK VMG:", "---")
        row("HDG to sail:", "---")


def _handle_polar_click(state, mx, my, rect):
    x, y, w, _h = rect
    polar = state.polar_data.get(state.polar_active)
    if polar is None:
        return None

    chart_w = int(w * 0.60)
    px = x + chart_w + 10
    py = y + 8
    pw = w - chart_w - 20

    py += 22
    for _i, name in enumerate(state.polar_names):
        btn = pygame.Rect(px, py, pw, 20)
        if btn.collidepoint(mx, my):
            state.polar_active = name
            state.polar_tws_index = min(
                state.polar_tws_index, len(state.polar_data[name].tws_list) - 1
            )
            return "polar_select"
        py += 24

    py += 22 + 4
    py += 26

    py += 4 + 22
    for _group_name, group_sails in state.sail_groups:
        py += 16
        for sail in group_sails:
            btn = pygame.Rect(px, py, pw, 20)
            if btn.collidepoint(mx, my):
                toggle_sail(state, sail)
                return "sail_toggle"
            py += 24

    py += 4 + 22
    py += 22
    log_btn = pygame.Rect(px, py, pw, 26)
    if log_btn.collidepoint(mx, my):
        if state.sailing_log_active:
            state.sailing_log_active = False
            state.performance_log_file = None
            return "log_stop"
        else:
            state.sailing_log_active = True
            state.log_sample_count = 0
            state.log_perf_sum = 0.0
            state.performance_log_file = None
            return "log_start"
    py += 26 + 6
    if state.sailing_log_active:
        py += 22
        if state.log_sample_count > 0:
            py += 22
    else:
        py += 22

    return None


def _handle_polar_key(state, key):
    polar = state.polar_data.get(state.polar_active)
    if polar is None:
        return None

    if key == pygame.K_l:
        if state.sailing_log_active:
            state.sailing_log_active = False
            state.performance_log_file = None
            return "log_stop"
        else:
            state.sailing_log_active = True
            state.log_sample_count = 0
            state.log_perf_sum = 0.0
            state.performance_log_file = None
            return "log_start"
    elif key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
        idx = key - pygame.K_1
        if idx < len(state.polar_names):
            state.polar_active = state.polar_names[idx]
            state.polar_tws_index = min(
                state.polar_tws_index, len(state.polar_data[state.polar_active].tws_list) - 1
            )
            return "polar_select"
    return None
