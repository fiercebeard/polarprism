import math

import pygame

from polars.parser import calc_vmc, calc_vmg, compute_true_wind
from signalk.models import MS_TO_KNOTS, _refresh_route_cache, derive_true_heading, rad_to_deg
from theme import (
    BG,
    BTN_ACTIVE_BG,
    BTN_ACTIVE_BORDER,
    BTN_BG,
    BTN_BORDER,
    CALC,
    ROUTE_ACTIVE_LEG,
    ROUTE_DONE,
    ROUTE_LEG_DONE,
    ROUTE_NEXT_WAYPOINT,
    ROUTE_WAYPOINT,
    SECTION,
    TEXT_LABEL,
    TEXT_MUTED,
    TEXT_VALUE,
    TEXT_WHITE,
    WP_VMC_DOT,
    WP_VMG_DOT,
)


def _cycle_route(state, direction):
    if not state.route_names:
        return
    if state.route_active not in state.route_names:
        idx = 0
    else:
        idx = state.route_names.index(state.route_active)
    n = len(state.route_names)
    idx = (idx + direction) % n
    state.route_active = state.route_names[idx]
    state.route_leg_index = 0
    _refresh_route_cache(state)


def _format_eta(eta_s):
    if eta_s is None:
        return "---"
    if eta_s < 0:
        return "---"
    h = int(eta_s // 3600)
    m = int((eta_s % 3600) // 60)
    s = int(eta_s % 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def draw_route(surface, font, font_sm, state, rect):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))
    _refresh_route_cache(state)

    polar = state.polar_data.get(state.polar_active)
    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)

    vmc_kts = None
    vmc_data = None
    vmg_data = None
    if polar is not None and tws_ms is not None:
        vmg_data = calc_vmg(polar, tws_ms * MS_TO_KNOTS)
        if twa_rad is not None and state.route_next_wp_bearing_rad is not None:
            ht_val = derive_true_heading(state)
            ht_deg = rad_to_deg(ht_val) if ht_val is not None else None
            if ht_deg is not None:
                twd_deg = (ht_deg + math.degrees(twa_rad)) % 360
                wp_brg_deg = rad_to_deg(state.route_next_wp_bearing_rad)
                course_twa_deg = (wp_brg_deg - twd_deg) % 360
                if course_twa_deg > 180:
                    course_twa_deg -= 360
                vmc_data = calc_vmc(polar, tws_ms * MS_TO_KNOTS, course_twa_deg)
                if vmc_data is not None:
                    vmc_kts = vmc_data["best_vmc"]
    _refresh_route_cache(state, vmc_kts=vmc_kts)

    py = y0 + 20
    row_h = 26
    col_label_x = x + 20
    col_value_x = x + 200

    def heading(text):
        nonlocal py
        ts = font.render(text, True, SECTION)
        surface.blit(ts, (col_label_x, py))
        py += row_h + 4

    def row(label, val, color=TEXT_VALUE, val_x=col_value_x):
        nonlocal py
        tl = font.render(label, True, TEXT_LABEL)
        tv = font.render(val, True, color)
        surface.blit(tl, (col_label_x, py))
        surface.blit(tv, (val_x, py))
        py += row_h

    heading("--- Route ---")
    if not state.route_names:
        ts = font.render("No routes loaded (drop .gpx into routes/)", True, TEXT_MUTED)
        surface.blit(ts, (col_label_x, py))
        return
    btn_w = max(140, (w - 60) // max(len(state.route_names), 1))
    for i, name in enumerate(state.route_names):
        bx = col_label_x + i * (btn_w + 8)
        is_active = name == state.route_active
        bg = BTN_ACTIVE_BG if is_active else BTN_BG
        border = BTN_ACTIVE_BORDER if is_active else BTN_BORDER
        btn = pygame.Rect(bx, py, btn_w, 24)
        pygame.draw.rect(surface, bg, btn, border_radius=4)
        pygame.draw.rect(surface, border, btn, 1, border_radius=4)
        short = name
        if len(short) > 18:
            short = short[:17] + "\u2026"
        tc = TEXT_WHITE if is_active else TEXT_MUTED
        tl = font_sm.render(short, True, tc)
        surface.blit(tl, (bx + 6, py + 4))
    py += 30
    state._route_btn_rects = []
    for i in range(len(state.route_names)):
        bx = col_label_x + i * (btn_w + 8)
        state._route_btn_rects.append((py - 30, pygame.Rect(bx, py - 30, btn_w, 24)))

    route = state.routes.get(state.route_active)
    if route is None:
        row("Active:", "---", TEXT_MUTED)
        return

    py += 4
    heading("--- Active Route ---")
    row("Name:", route.name, CALC)
    row("Waypoints:", str(len(route.waypoints)))
    leg_idx = state.route_leg_index
    last_leg = route.leg_count() - 1
    if leg_idx > last_leg:
        leg_idx = last_leg
    state.route_leg_index = leg_idx
    row("Leg:", f"{leg_idx + 1} / {route.leg_count()}")
    from_wp = route.waypoints[leg_idx]
    to_wp = route.waypoints[leg_idx + 1] if leg_idx + 1 < len(route.waypoints) else None
    if to_wp is not None:
        row("From:", from_wp.name or f"WP{leg_idx}")
        row("To:", to_wp.name or f"WP{leg_idx + 1}", ROUTE_NEXT_WAYPOINT)
        leg_brg_deg = (
            rad_to_deg(route.leg_bearing_rad(leg_idx))
            if route.leg_bearing_rad(leg_idx) is not None
            else None
        )
        leg_dist_nm = route.leg_distance_m(leg_idx) / 1852.0
        row(
            "Leg brg:",
            f"{leg_brg_deg:.1f}\u00b0T" if leg_brg_deg is not None else "---",
            ROUTE_ACTIVE_LEG,
        )
        row("Leg dist:", f"{leg_dist_nm:.2f} nm", ROUTE_ACTIVE_LEG)
    row("Total:", f"{state.route_total_nm:.2f} nm", CALC)
    row("Remaining:", f"{state.route_remaining_nm:.2f} nm", CALC)
    row("ETA:", _format_eta(state.route_eta_s), ROUTE_NEXT_WAYPOINT)

    py += 4
    heading("--- Next Waypoint ---")
    if state.route_next_wp_bearing_rad is not None and state.route_next_wp_distance_m is not None:
        brg_deg = rad_to_deg(state.route_next_wp_bearing_rad)
        dist_nm = state.route_next_wp_distance_m / 1852.0
        row("Name:", state.route_next_wp_name or f"WP{leg_idx + 1}", ROUTE_NEXT_WAYPOINT)
        row("Bearing:", f"{brg_deg:.1f}\u00b0T", ROUTE_NEXT_WAYPOINT)
        if dist_nm < 1.0:
            row("Distance:", f"{state.route_next_wp_distance_m:.0f} m", ROUTE_NEXT_WAYPOINT)
        else:
            row("Distance:", f"{dist_nm:.2f} nm", ROUTE_NEXT_WAYPOINT)
        if vmc_data is not None:
            row("VMC TWA:", f"{vmc_data['best_twa']:.1f}\u00b0", WP_VMC_DOT)
            row("VMC Speed:", f"{vmc_data['best_speed']:.1f} kts", WP_VMC_DOT)
            row("VMC:", f"{vmc_data['best_vmc']:.1f} kts", WP_VMC_DOT)
            row("Tack:", vmc_data["best_tack"], WP_VMC_DOT)
        else:
            row("VMC:", "---")
        if vmg_data is not None:
            if "upwind_twa" in vmg_data:
                row("Up VMG:", f"{vmg_data['upwind_vmg']:.1f} kts", WP_VMG_DOT)
            else:
                row("Up VMG:", "---")
            if "downwind_twa" in vmg_data:
                row("Dn VMG:", f"{vmg_data['downwind_vmg']:.1f} kts", WP_VMG_DOT)
            else:
                row("Dn VMG:", "---")
        else:
            row("Up VMG:", "---")
            row("Dn VMG:", "---")
    else:
        row("(no position)", "", TEXT_MUTED)
        if vmg_data is not None:
            if "upwind_twa" in vmg_data:
                row("Up VMG:", f"{vmg_data['upwind_vmg']:.1f} kts", WP_VMG_DOT)
            else:
                row("Up VMG:", "---")
            if "downwind_twa" in vmg_data:
                row("Dn VMG:", f"{vmg_data['downwind_vmg']:.1f} kts", WP_VMG_DOT)
            else:
                row("Dn VMG:", "---")
        else:
            row("Up VMG:", "---")
            row("Dn VMG:", "---")

    py += 4
    advance_rect = pygame.Rect(col_label_x, py, 220, 32)
    is_last = state.route_leg_index >= route.leg_count() - 1
    btn_bg = ROUTE_DONE if is_last else BTN_ACTIVE_BG
    btn_border = ROUTE_DONE if is_last else BTN_ACTIVE_BORDER
    pygame.draw.rect(surface, btn_bg, advance_rect, border_radius=4)
    pygame.draw.rect(surface, btn_border, advance_rect, 1, border_radius=4)
    label = "FINISH" if is_last else "ADVANCE LEG [N]"
    bt = font.render(label, True, TEXT_WHITE)
    surface.blit(
        bt,
        (
            advance_rect.x + advance_rect.w // 2 - bt.get_width() // 2,
            advance_rect.y + advance_rect.h // 2 - bt.get_height() // 2,
        ),
    )
    state._route_advance_rect = advance_rect
    py += 40

    cycle_rect = pygame.Rect(col_label_x + 240, py - 40, 180, 32)
    pygame.draw.rect(surface, BTN_BG, cycle_rect, border_radius=4)
    pygame.draw.rect(surface, BTN_BORDER, cycle_rect, 1, border_radius=4)
    bt = font.render("CYCLE ROUTE [R]", True, TEXT_MUTED)
    surface.blit(
        bt,
        (
            cycle_rect.x + cycle_rect.w // 2 - bt.get_width() // 2,
            cycle_rect.y + cycle_rect.h // 2 - bt.get_height() // 2,
        ),
    )
    state._route_cycle_rect = cycle_rect

    py += 4
    heading("--- Legs ---")
    list_x = col_label_x
    list_y = py

    list_row_h = 22
    max_rows = max(1, (y0 + h - list_y - 20) // list_row_h)
    for i in range(route.leg_count()):
        if i >= max_rows:
            break
        a_wp = route.waypoints[i]
        b_wp = route.waypoints[i + 1]
        if i < state.route_leg_index:
            color = ROUTE_LEG_DONE
            prefix = "\u2713"
        elif i == state.route_leg_index:
            color = ROUTE_ACTIVE_LEG
            prefix = ">"
        else:
            color = ROUTE_WAYPOINT
            prefix = " "
        brg = route.leg_bearing_rad(i)
        dist_nm = route.leg_distance_m(i) / 1852.0
        brg_str = f"{rad_to_deg(brg):.0f}\u00b0" if brg is not None else "---"
        a_label = a_wp.name or f"WP{i}"
        b_label = b_wp.name or f"WP{i + 1}"
        line = f"{prefix} {i + 1}. {a_label}  \u2192  {b_label}   {brg_str:>5}  {dist_nm:5.2f}nm"
        ts = font_sm.render(line, True, color)
        surface.blit(ts, (list_x, list_y + i * list_row_h))


def _handle_route_click(state, mx, my, rect):
    rects = getattr(state, "_route_btn_rects", None)
    if rects:
        for i, (_orig_y, btn) in enumerate(rects):
            if btn.collidepoint(mx, my) and i < len(state.route_names):
                state.route_active = state.route_names[i]
                state.route_leg_index = 0
                _refresh_route_cache(state)
                return "route_select"
    adv = getattr(state, "_route_advance_rect", None)
    if adv is not None and adv.collidepoint(mx, my):
        route = state.routes.get(state.route_active)
        if route is not None and state.route_leg_index < route.leg_count() - 1:
            state.route_leg_index += 1
            _refresh_route_cache(state)
            return "route_advance"
    cyc = getattr(state, "_route_cycle_rect", None)
    if cyc is not None and cyc.collidepoint(mx, my):
        _cycle_route(state, +1)
        return "route_cycle"
    return None


def _handle_route_key(state, key):
    if key == pygame.K_n:
        route = state.routes.get(state.route_active)
        if route is not None and state.route_leg_index < route.leg_count() - 1:
            state.route_leg_index += 1
            _refresh_route_cache(state)
            return "route_advance"
    elif key == pygame.K_r:
        _cycle_route(state, +1)
        return "route_cycle"
    elif key == pygame.K_b:
        if state.route_leg_index > 0:
            state.route_leg_index -= 1
            _refresh_route_cache(state)
            return "route_back"
    return None
