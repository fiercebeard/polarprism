import math
import pygame
from polars.parser import lookup_speed, compute_true_wind, lookup_recommended_sail
from signalk.models import rad_to_deg, derive_true_heading
from theme import (
    BG, TEXT_WHITE, TEXT_MUTED, TEXT_LABEL, TEXT_VALUE, TEXT_DIM, SECTION,
    POLAR_RING, POLAR_GRID, POLAR_SPEED_LINE, POLAR_BOAT_DOT, POLAR_TARGET_DOT, POLAR_FILL,
    TWS_COLORS, WIND_TRUE, WIND_APPARENT, WIND_DIR_ARROW,
    SAILING_ACTIVE, SAILING_INACTIVE, MOTORING_COLOR, IDLE_COLOR,
    SAIL_COLORS, BTN_BG, BTN_BORDER, BTN_ACTIVE_BG, BTN_ACTIVE_BORDER,
    CALC, WARN, OK,
)


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
        lbl_map = {0: "B", 30: "30", 60: "60", 90: "90", 120: "120",
                   150: "150", 180: "180", 210: "150", 240: "120",
                   270: "90", 300: "60", 330: "30"}
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
        is_active = (ti == active_tws_idx)
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
        tws_kts_val = tws_ms * 1.94384
        target_spd = lookup_speed(polar, abs(twa_deg), tws_kts_val)
        stw_kts = (stw_ms or 0) * 1.94384

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

    pygame.draw.circle(surface, TEXT_WHITE, (cx, cy), 3)

    _draw_polar_panel(surface, font, font_sm, state, rect, chart_w, polar)


def _draw_polar_panel(surface, font, font_sm, state, rect, chart_w, polar):
    x, y, w, h = rect
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
        short = name.replace("US50_Rated_", "")
        tc = TEXT_WHITE if is_active else TEXT_MUTED
        tl = font_sm.render(f"{i+1}:{short}", True, tc)
        surface.blit(tl, (px + 6, py + 2))
        py += 24

    py += 4
    heading("--- Wind Speed (TWS) ---")
    key_hint = font_sm.render("W/S", True, TEXT_DIM)
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
    heading("--- Active Sails ---")
    for sail in state.available_sails:
        is_active = sail in state.active_sails
        bg = BTN_ACTIVE_BG if is_active else BTN_BG
        border_c = BTN_ACTIVE_BORDER if is_active else BTN_BORDER
        if is_active:
            border_c = SAIL_COLORS.get(sail, BTN_ACTIVE_BORDER)
        btn = pygame.Rect(px, py, pw, 20)
        pygame.draw.rect(surface, bg, btn, border_radius=4)
        pygame.draw.rect(surface, border_c, btn, 1, border_radius=4)
        sc = SAIL_COLORS.get(sail, TEXT_WHITE) if is_active else TEXT_MUTED
        tl = font_sm.render(sail, True, sc)
        surface.blit(tl, (px + 6, py + 2))
        py += 24

    py += 4
    heading("--- Recommended Sail ---")
    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)
    if twa_rad is not None and tws_ms is not None:
        twa_deg = math.degrees(twa_rad)
        tws_kts_v = tws_ms * 1.94384
        rec_sail = lookup_recommended_sail(state.sailselect, state.saildef, polar.twa_list, abs(twa_deg), tws_kts_v)
        if rec_sail:
            row("Sail:", rec_sail, SAIL_COLORS.get(rec_sail, TEXT_VALUE))
        else:
            row("Sail:", "---")
    else:
        row("Sail:", "(no wind)")

    py += 8
    heading("--- Performance ---")
    if twa_rad is not None and tws_ms is not None:
        twa_deg = math.degrees(twa_rad)
        tws_kts_v = tws_ms * 1.94384
        target = lookup_speed(polar, abs(twa_deg), tws_kts_v)
        stw_kts = (stw_ms or 0) * 1.94384
        row("TWA:", f"{abs(twa_deg):.1f}\u00b0")
        row("TWS:", f"{tws_kts_v:.1f} kts")
        row("Target:", f"{target:.2f} kts" if target else "--- kts", CALC)
        row("Actual:", f"{stw_kts:.2f} kts", POLAR_BOAT_DOT)
        if target and target > 0 and stw_ms is not None:
            pct = stw_kts / target * 100
            pc = OK if pct >= 95 else (WARN if pct < 80 else TEXT_VALUE)
            row("Perf:", f"{pct:.1f}%", pc)
        else:
            row("Perf:", "---")
    else:
        row("TWA:", "---")
        row("TWS:", "---")
        row("Target:", "---")
        row("Actual:", "---")
        row("Perf:", "---")


def draw_wind(surface, font, font_sm, state, rect):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))

    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    hm_rad = state.values.get("headingMagnetic")
    mv_rad = state.values.get("magneticVariation")

    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)

    cx = x + w // 2
    cy = y0 + h // 2 - 40
    r = min(w, h) // 2 - 60

    pygame.draw.circle(surface, POLAR_FILL, (cx, cy), r)
    for ring_r in range(r // 4, r + 1, r // 4):
        pygame.draw.circle(surface, POLAR_RING, (cx, cy), ring_r, 1)

    for a_deg in range(0, 360, 30):
        a_rad = math.radians(a_deg) - math.pi / 2
        ex = cx + math.cos(a_rad) * r
        ey = cy + math.sin(a_rad) * r
        pygame.draw.line(surface, POLAR_GRID, (cx, cy), (int(ex), int(ey)), 1)

    lbl_map = {0: "B", 90: "S", 180: "B", 270: "S"}
    for a_deg in [0, 90, 180, 270]:
        a_rad = math.radians(a_deg) - math.pi / 2
        lx = cx + math.cos(a_rad) * (r + 16)
        ly = cy + math.sin(a_rad) * (r + 16)
        lbl = font_sm.render(lbl_map[a_deg], True, TEXT_DIM)
        surface.blit(lbl, (int(lx - lbl.get_width() // 2), int(ly - lbl.get_height() // 2)))

    heading_rad = None
    if hm_rad is not None:
        mv = mv_rad or 0
        heading_rad = hm_rad + mv
    elif state.values.get("cogTrue") is not None:
        heading_rad = state.values["cogTrue"]

    if heading_rad is not None and twa_rad is not None:
        twd_rad = heading_rad + twa_rad
        a = twd_rad - math.pi / 2
        ex = cx + math.cos(a) * (r - 4)
        ey = cy + math.sin(a) * (r - 4)
        pygame.draw.line(surface, WIND_DIR_ARROW, (cx, cy), (int(ex), int(ey)), 3)
        hx = ex + math.cos(a + 2.6) * 12
        hy = ey + math.sin(a + 2.6) * 12
        hx2 = ex + math.cos(a - 2.6) * 12
        hy2 = ey + math.sin(a - 2.6) * 12
        pygame.draw.polygon(surface, WIND_DIR_ARROW, [(int(ex), int(ey)), (int(hx), int(hy)), (int(hx2), int(hy2))])

    if awa_rad is not None:
        a = awa_rad - math.pi / 2
        a_len = r * 0.6
        ex = cx + math.cos(a) * a_len
        ey = cy + math.sin(a) * a_len
        pygame.draw.line(surface, WIND_APPARENT, (cx, cy), (int(ex), int(ey)), 2)

    if twa_rad is not None:
        a = twa_rad - math.pi / 2
        a_len = r * 0.8
        ex = cx + math.cos(a) * a_len
        ey = cy + math.sin(a) * a_len
        pygame.draw.line(surface, WIND_TRUE, (cx, cy), (int(ex), int(ey)), 2)

    pygame.draw.circle(surface, TEXT_WHITE, (cx, cy), 4)

    ny = cy + r + 30
    row_h = 20

    def row(label, val, color=TEXT_VALUE):
        nonlocal ny
        tl = font_sm.render(label, True, TEXT_LABEL)
        tv = font_sm.render(val, True, color)
        surface.blit(tl, (x + 20, ny))
        surface.blit(tv, (x + 140, ny))
        ny += row_h

    ht_val = derive_true_heading(state)
    ht_deg = rad_to_deg(ht_val) if ht_val is not None else None
    twd_deg = None
    if ht_deg is not None and twa_rad is not None:
        twd_deg = (ht_deg + math.degrees(twa_rad)) % 360

    awa_deg = math.degrees(awa_rad) if awa_rad is not None else None
    aws_kts = aws_ms * 1.94384 if aws_ms is not None else None
    twa_deg = math.degrees(twa_rad) if twa_rad is not None else None
    tws_kts = tws_ms * 1.94384 if tws_ms is not None else None

    row("TWD:", f"{twd_deg:.1f}\u00b0" if twd_deg is not None else "---\u00b0", WIND_DIR_ARROW)
    row("TWS:", f"{tws_kts:.1f} kts" if tws_kts is not None else "--- kts", WIND_TRUE)
    row("TWA:", f"{twa_deg:.1f}\u00b0" if twa_deg is not None else "---\u00b0", WIND_TRUE)
    row("AWA:", f"{awa_deg:.1f}\u00b0" if awa_deg is not None else "---\u00b0", WIND_APPARENT)
    row("AWS:", f"{aws_kts:.1f} kts" if aws_kts is not None else "--- kts", WIND_APPARENT)
    row("Heading:", f"{ht_deg:.1f}\u00b0" if ht_deg is not None else "---\u00b0")


def draw_log(surface, font, font_sm, state, rect):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))

    py = y0 + 20
    row_h = 28

    def heading(text):
        nonlocal py
        ts = font.render(text, True, SECTION)
        surface.blit(ts, (x + 20, py))
        py += row_h + 4

    def row(label, val, color=TEXT_VALUE):
        nonlocal py
        tl = font.render(label, True, TEXT_LABEL)
        tv = font.render(val, True, color)
        surface.blit(tl, (x + 20, py))
        surface.blit(tv, (x + 200, py))
        py += row_h

    if state.sailing_log_active:
        dot_color = SAILING_ACTIVE
        status_text = "RECORDING"
    else:
        dot_color = SAILING_INACTIVE
        status_text = "STOPPED"

    pygame.draw.circle(surface, dot_color, (x + 30, py + 10), 8)
    ts = font.render(status_text, True, dot_color)
    surface.blit(ts, (x + 50, py))
    py += row_h + 8

    btn_w = 180
    btn_h = 40
    btn = pygame.Rect(x + 20, py, btn_w, btn_h)
    btn_bg = (160, 40, 40) if state.sailing_log_active else (40, 120, 60)
    pygame.draw.rect(surface, btn_bg, btn, border_radius=6)
    pygame.draw.rect(surface, TEXT_WHITE, btn, 1, border_radius=6)
    btn_text = "STOP LOG [L]" if state.sailing_log_active else "START LOG [L]"
    bt = font.render(btn_text, True, TEXT_WHITE)
    surface.blit(bt, (btn.x + btn_w // 2 - bt.get_width() // 2, btn.y + btn_h // 2 - bt.get_height() // 2))
    py += btn_h + 16

    heading("--- Sailing State ---")
    state_colors = {"sailing": SAILING_ACTIVE, "motoring": MOTORING_COLOR, "idle": IDLE_COLOR}
    for i, (sname, scolor) in enumerate(state_colors.items()):
        is_active = state.sailing_state == sname
        bg = BTN_ACTIVE_BG if is_active else BTN_BG
        border_c = scolor if is_active else BTN_BORDER
        bw = 120
        brect = pygame.Rect(x + 20 + i * (bw + 8), py, bw, 24)
        pygame.draw.rect(surface, bg, brect, border_radius=4)
        pygame.draw.rect(surface, border_c, brect, 1, border_radius=4)
        tc = TEXT_WHITE if is_active else TEXT_MUTED
        tl = font_sm.render(f"{i+1}:{sname.capitalize()}", True, tc)
        surface.blit(tl, (brect.x + bw // 2 - tl.get_width() // 2, brect.y + 4))
    py += 34

    heading("--- Active Sails ---")
    for sail in state.available_sails:
        is_active = sail in state.active_sails
        bg = BTN_ACTIVE_BG if is_active else BTN_BG
        border_c = SAIL_COLORS.get(sail, BTN_BORDER) if is_active else BTN_BORDER
        brect = pygame.Rect(x + 20, py, 160, 24)
        pygame.draw.rect(surface, bg, brect, border_radius=4)
        pygame.draw.rect(surface, border_c, brect, 1, border_radius=4)
        sc = SAIL_COLORS.get(sail, TEXT_WHITE) if is_active else TEXT_MUTED
        tl = font_sm.render(sail, True, sc)
        surface.blit(tl, (x + 28, py + 4))
        py += 30
    py += 8

    heading("--- Polar Profile ---")
    short = state.polar_active.replace("US50_Rated_", "") if state.polar_active else "---"
    row("Polar:", short, CALC)
    py += 8

    heading("--- Log Info ---")
    if state.sailing_log_active:
        fname = state.performance_log_file or "---"
        if "/" in fname:
            fname = fname.rsplit("/", 1)[-1]
        row("File:", fname)
        row("Samples:", str(state.log_sample_count))
        if state.log_sample_count > 0:
            avg = state.log_perf_sum / state.log_sample_count
            pc = OK if avg >= 95 else (WARN if avg < 80 else TEXT_VALUE)
            row("Avg Perf:", f"{avg:.1f}%", pc)
        else:
            row("Avg Perf:", "---")
    else:
        row("File:", "(not recording)")
        row("Samples:", "0")
        row("Avg Perf:", "---")


def render(surface, font, font_sm, state, rect, sub_tab):
    if sub_tab == 0:
        draw_polar_rose(surface, font, font_sm, state, rect)
    elif sub_tab == 1:
        draw_wind(surface, font, font_sm, state, rect)
    elif sub_tab == 2:
        draw_log(surface, font, font_sm, state, rect)


def handle_click(state, mx, my, rect, sub_tab):
    x, y, w, h = rect
    if sub_tab == 0:
        return _handle_polar_click(state, mx, my, rect)
    elif sub_tab == 2:
        return _handle_log_click(state, mx, my, rect)
    return None


def _handle_polar_click(state, mx, my, rect):
    x, y, w, h = rect
    polar = state.polar_data.get(state.polar_active)
    if polar is None:
        return None

    chart_w = int(w * 0.60)
    px = x + chart_w + 10
    py = y + 8
    pw = w - chart_w - 20

    py += 22
    for i, name in enumerate(state.polar_names):
        btn = pygame.Rect(px, py, pw, 20)
        if btn.collidepoint(mx, my):
            state.polar_active = name
            state.polar_tws_index = min(state.polar_tws_index, len(state.polar_data[name].tws_list) - 1)
            return "polar_select"
        py += 24

    py += 22 + 4
    btn_w = min(40, (pw - 10) // max(len(polar.tws_list), 1))
    for i in range(len(polar.tws_list)):
        bx = px + i * (btn_w + 4)
        btn = pygame.Rect(bx, py, btn_w, 18)
        if btn.collidepoint(mx, my):
            state.polar_tws_index = i
            return "tws_select"
    py += 26

    py += 4 + 22
    for sail in state.available_sails:
        btn = pygame.Rect(px, py, pw, 20)
        if btn.collidepoint(mx, my):
            if sail in state.active_sails:
                state.active_sails.remove(sail)
            else:
                state.active_sails.append(sail)
            return "sail_toggle"
        py += 24

    return None


def _handle_log_click(state, mx, my, rect):
    x, y0, w, h = rect
    py = y0 + 20

    py += 28 + 8
    btn = pygame.Rect(x + 20, py, 180, 40)
    if btn.collidepoint(mx, my):
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
    py += 40 + 16

    py += 28 + 4 + 22
    state_names = ["sailing", "motoring", "idle"]
    for i in range(3):
        bw = 120
        brect = pygame.Rect(x + 20 + i * (bw + 8), py, bw, 24)
        if brect.collidepoint(mx, my):
            state.sailing_state = state_names[i]
            return "state_change"
    py += 34

    return None


def handle_key(state, key, sub_tab):
    if sub_tab == 0:
        return _handle_polar_key(state, key)
    elif sub_tab == 2:
        return _handle_log_key(state, key)
    return None


def _handle_polar_key(state, key):
    polar = state.polar_data.get(state.polar_active)
    if polar is None:
        return None

    if key == pygame.K_w:
        if state.polar_tws_index < len(polar.tws_list) - 1:
            state.polar_tws_index += 1
        return "tws_change"
    elif key == pygame.K_s:
        if state.polar_tws_index > 0:
            state.polar_tws_index -= 1
        return "tws_change"
    elif key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
        idx = key - pygame.K_1
        if idx < len(state.polar_names):
            state.polar_active = state.polar_names[idx]
            state.polar_tws_index = min(state.polar_tws_index, len(state.polar_data[state.polar_active].tws_list) - 1)
            return "polar_select"
    return None


def _handle_log_key(state, key):
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
    elif key == pygame.K_1:
        state.sailing_state = "sailing"
        return "state_change"
    elif key == pygame.K_2:
        state.sailing_state = "motoring"
        return "state_change"
    elif key == pygame.K_3:
        state.sailing_state = "idle"
        return "state_change"
    return None