import math
import pygame
from signalk.models import (
    State, rad_to_deg, rad_to_deg_signed, norm_angle, angle_diff,
    derive_true_heading, compute_fusion_heading,
)
from theme import (
    BG, SECTION, TEXT_LABEL, TEXT_VALUE, TEXT_SRC, TEXT_DIM, TEXT_WHITE, TEXT_MUTED,
    WARN, OK, CALC, CONNECTED, DISCONNECTED, FUSION_ON, FUSION_OFF,
    SIGNAL_COLORS, SIGNAL_LABELS,
    COMPASS_RING, COMPASS_RING_BORDER, COMPASS_FILL, COMPASS_TICK,
    COMPASS_CENTER_OUTER, COMPASS_CENTER_INNER,
)


def draw_compass(surface, font, font_sm, state, rect):
    x, y, w, h = rect
    cx = x + w // 2
    r = min(w, h) // 2 - 16
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
    if state.emulation_active and state.fusion_heading is not None:
        angle_keys.append("fusionTrue")

    for key in angle_keys:
        if key == "headingTrue":
            val = derive_true_heading(state)
        elif key == "fusionTrue":
            val = state.fusion_heading
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
        pygame.draw.circle(surface, color,
                           (int(cx + math.cos(a) * (r + 16)),
                            int(cy + math.sin(a) * (r + 16))), 4)

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

    legend_y = cy + r + 24
    legend_keys = ["headingMagnetic", "headingTrue", "cogTrue", "apTargetMagnetic",
                    "magneticVariation", "rateOfTurn"]
    if state.emulation_active:
        legend_keys.append("fusionTrue")

    row_h = 22
    for key in legend_keys:
        label = SIGNAL_LABELS[key]
        color = SIGNAL_COLORS[key]
        if key == "headingTrue":
            val = derive_true_heading(state)
        elif key == "fusionTrue":
            val = state.fusion_heading
        elif key == "magneticVariation":
            val = state.values.get(key)
            if val is not None:
                deg_str = f"{rad_to_deg_signed(val):+.1f}\u00b0"
            else:
                deg_str = "---\u00b0"
            ts_l = font_sm.render(f"  {label}", True, color)
            surface.blit(ts_l, (x + 8, legend_y))
            ts_v = font_sm.render(deg_str, True, TEXT_VALUE)
            surface.blit(ts_v, (x + 120, legend_y))
            pygame.draw.rect(surface, color, (x + 8 - 14, legend_y + 2, 10, 8))
            legend_y += row_h
            continue
        elif key == "rateOfTurn":
            val = state.values.get(key)
            if val is not None:
                deg_str = f"{math.degrees(val):+.2f}\u00b0/s"
            else:
                deg_str = "---\u00b0/s"
            ts_l = font_sm.render(f"  {label}", True, color)
            surface.blit(ts_l, (x + 8, legend_y))
            ts_v = font_sm.render(deg_str, True, TEXT_VALUE)
            surface.blit(ts_v, (x + 120, legend_y))
            pygame.draw.rect(surface, color, (x + 8 - 14, legend_y + 2, 10, 8))
            legend_y += row_h
            continue
        else:
            val = state.values.get(key)

        if val is not None:
            deg_str = f"{rad_to_deg(val):06.1f}\u00b0"
        else:
            deg_str = "---\u00b0"

        ts_l = font_sm.render(f"  {label}", True, color)
        surface.blit(ts_l, (x + 8, legend_y))
        ts_v = font_sm.render(deg_str, True, TEXT_VALUE)
        surface.blit(ts_v, (x + 120, legend_y))
        pygame.draw.rect(surface, color, (x + 8 - 14, legend_y + 2, 10, 8))
        legend_y += row_h


def draw_diagnostics(surface, font, font_sm, state, rect):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))

    row_h = 17
    label_color = TEXT_LABEL
    val_color = TEXT_VALUE
    src_color = TEXT_SRC
    warn_color = WARN
    dim_color = TEXT_DIM
    section_color = SECTION

    hm = state.values.get("headingMagnetic")
    mv = state.values.get("magneticVariation")
    cog = state.values.get("cogTrue")
    sog = state.values.get("speedOverGround")
    stw = state.values.get("speedThroughWater")
    rot = state.values.get("rateOfTurn")
    rudder = state.values.get("rudderAngle")
    roll = state.values.get("roll")
    pitch = state.values.get("pitch")
    yaw = state.values.get("yaw")
    sk_ht = state.values.get("headingTrue")
    waa = state.values.get("windAngleApparent")
    was = state.values.get("windSpeedApparent")
    ap_target = state.values.get("apTargetMagnetic")

    derived_ht = None
    if hm is not None and mv is not None:
        derived_ht = norm_angle(hm + mv + math.radians(state.heading_offset))

    y = y0 + 4

    def section(title):
        nonlocal y
        y += 4
        ts = font_sm.render(title, True, section_color)
        surface.blit(ts, (x + 4, y))
        y += row_h - 2

    def row(label, value_str, detail="", color=val_color, warn=False):
        nonlocal y
        ts_l = font_sm.render(label, True, label_color)
        surface.blit(ts_l, (x + 4, y))
        ts_v = font_sm.render(value_str, True, warn_color if warn else color)
        surface.blit(ts_v, (x + 140, y))
        if detail:
            ts_d = font_sm.render(detail, True, dim_color)
            surface.blit(ts_d, (x + 260, y))
        y += row_h

    def dev_row(label, value_str, src_key, color=val_color, warn=False):
        nonlocal y
        ts_l = font_sm.render(label, True, label_color)
        surface.blit(ts_l, (x + 4, y))
        ts_v = font_sm.render(value_str, True, warn_color if warn else color)
        surface.blit(ts_v, (x + 140, y))
        src = state.sources.get(src_key, "")
        dev = state.device_names.get(src, src) if src else ""
        if dev:
            ts_d = font_sm.render(dev, True, src_color)
            surface.blit(ts_d, (x + 260, y))
        y += row_h

    section("--- EV-1 Course Computer [204] ---")
    dev_row("Mag Heading:", f"{rad_to_deg(hm):06.1f}\u00b0" if hm is not None else "---\u00b0", "headingMagnetic")
    dev_row("Rate of Turn:", f"{math.degrees(rot):+.2f}\u00b0/s" if rot is not None else "---\u00b0/s", "rateOfTurn")
    if yaw is not None:
        row("  Yaw:", f"{math.degrees(yaw):06.1f}\u00b0")
    if roll is not None:
        row("  Roll:", f"{math.degrees(roll):+.1f}\u00b0")
    if pitch is not None:
        row("  Pitch:", f"{math.degrees(pitch):+.2f}\u00b0")
    dev_row("AP Target:", f"{rad_to_deg(ap_target):06.1f}\u00b0" if ap_target is not None else "---\u00b0", "apTargetMagnetic")

    section("--- AXIOM 9 [11] ---")
    dev_row("Mag Variation:", f"{rad_to_deg_signed(mv):+.2f}\u00b0" if mv is not None else "---\u00b0", "magneticVariation")

    section("--- Vesper CORTEX [22] ---")
    dev_row("COG True:", f"{rad_to_deg(cog):06.1f}\u00b0" if cog is not None else "---\u00b0", "cogTrue")
    dev_row("SOG:", f"{(sog or 0)*1.94384:.2f} kts" if sog is not None else "--- kts", "speedOverGround")

    section("--- DST810 [35] ---")
    dev_row("STW:", f"{(stw or 0)*1.94384:.2f} kts" if stw is not None else "--- kts", "speedThroughWater")

    section("--- ACU400 Rudder [172] ---")
    dev_row("Rudder:", f"{math.degrees(rudder):+.1f}\u00b0" if rudder is not None else "---\u00b0", "rudderAngle")

    section("--- iTC5 Wind [105] ---")
    if was is not None:
        row("App Wind:", f"{math.degrees(waa):+.0f}\u00b0 at {was*1.94384:.1f} kts" if waa is not None else "--- kts")

    section("--- CALC: Heading Error ---")
    calc_color = CALC
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
        sog_kts = (sog or 0) * 1.94384
        stw_kts = (stw or 0) * 1.94384
        row(f"{calc_label}:", f"{rad_to_deg(derived_ht):06.1f}\u00b0", calc_src, color=calc_color)
        row("COG TRUE:", f"{rad_to_deg(cog):06.1f}\u00b0", "(measured)")
        row("HDG ERROR:", f"{hdg_err_deg:+.1f}\u00b0",
            "COG-Heading" if abs(hdg_err_deg) < 180 else "wrap?",
            warn=abs(hdg_err_deg) > 15 and sog_kts > 1.0)

        if sog_kts > 1.5 and stw_kts > 0.5:
            current_drift = stw_kts * abs(math.sin(hdg_err)) / max(sog_kts, 0.1)
            leeway_est = math.degrees(math.asin(min(1, max(-1, math.sin(hdg_err) * sog_kts / max(stw_kts, 0.1)))))
            row("CALC: Current:", f"{abs(sog_kts - stw_kts):.1f} kts",
                "set" if abs(sog_kts - stw_kts) > 1 else "light")
            row("CALC: Drift:", f"{current_drift:.1f} kts",
                f"{math.degrees(hdg_err):+.0f}\u00b0 set")
            row("CALC: Leeway:", f"{leeway_est:+.1f}\u00b0", "(est from hdg-COG)")
        elif sog_kts > 1.5:
            row("CALC: Leeway:", f"{hdg_err_deg:+.1f}\u00b0 (incl. current)", "(no STW)")
        else:
            row("SOG:", f"{sog_kts:.1f} kts", "too slow for calc")

    if hm is not None and cog is not None:
        mag_cog = math.degrees(angle_diff(hm, cog))
        row("CALC: Mag-COG:", f"{mag_cog:+.1f}\u00b0",
            "(includes variation+leeway+current)")

    if hm is not None and mv is not None and ap_target is not None:
        ap_true = norm_angle(ap_target + mv)
        if derived_ht is not None:
            ap_off = math.degrees(angle_diff(ap_true, derived_ht))
            row("CALC: AP off hdg:", f"{ap_off:+.1f}\u00b0",
                "to port" if ap_off > 0 else "to stbd")

    section("--- Variation Sources ---")
    mv_multi = state.multi_values.get("magneticVariation", {})
    if mv_multi and len(mv_multi) >= 2:
        vals = []
        for src, v in mv_multi.items():
            dev_name = state.device_names.get(src, src)
            vals.append((dev_name, math.degrees(v), src))
        vals.sort(key=lambda x: x[1])
        delta = vals[-1][1] - vals[0][1]
        for dev_name, v_deg, src in vals:
            row(f"  {dev_name}:", f"{v_deg:+.4f}\u00b0", f"({src})")
        row("CALC: Delta:", f"{delta:+.4f}\u00b0", "EXCESSIVE" if abs(delta) > 0.5 else "OK",
            warn=abs(delta) > 0.5)

    section("--- Hdg Offset ---")
    row("Offset:", f"{state.heading_offset:+.1f}\u00b0", "[\u200b]/] to adjust")


def draw_fusion(surface, font, font_sm, state, rect):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))

    row_h = 24
    y = y0 + 20

    def row(label, value_str, color=TEXT_WHITE):
        nonlocal y
        ts_l = font.render(label, True, TEXT_LABEL)
        surface.blit(ts_l, (x + 20, y))
        ts_v = font.render(value_str, True, color)
        surface.blit(ts_v, (x + 220, y))
        y += row_h

    emu_color = FUSION_ON if state.emulation_active else FUSION_OFF
    emu_text = "ACTIVE" if state.emulation_active else "OFF"
    row("Fusion Engine:", emu_text, emu_color)
    row("Toggle:", "[F] key")

    if state.fusion_heading is not None:
        row("Fusion Heading:", f"{rad_to_deg(state.fusion_heading):06.1f}\u00b0", CALC)
    else:
        row("Fusion Heading:", "---\u00b0")

    hm = state.values.get("headingMagnetic")
    mv = state.values.get("magneticVariation")
    cog = state.values.get("cogTrue")
    sog = state.values.get("speedOverGround")
    rot = state.values.get("rateOfTurn")

    y += 16
    ts = font_sm.render("--- Algorithm ---", True, SECTION)
    surface.blit(ts, (x + 20, y))
    y += row_h

    if hm is not None and mv is not None:
        base = norm_angle(hm + mv)
        row("Base (Mag+Var):", f"{rad_to_deg(base):06.1f}\u00b0")

    if cog is not None and hm is not None:
        diff = math.degrees(angle_diff(cog, norm_angle(hm + (mv or 0))))
        sog_kts = (sog or 0) * 1.94384
        if abs(diff) > 15 and sog_kts < 1.0:
            cog_w = 0.0
            row("COG Weight:", "0.00 (drift threshold)", WARN)
        elif abs(diff) > 15:
            cog_w = 0.15
            row("COG Weight:", "0.15 (high drift)", CALC)
        else:
            cog_w = 0.3
            row("COG Weight:", "0.30 (normal)", OK)

        if rot is not None and abs(rot) > math.radians(10):
            row("ROT Dampen:", "0.5x", CALC)
        else:
            row("ROT Dampen:", "1.0x (none)")

    y += 16
    ts = font_sm.render("--- Sources ---", True, SECTION)
    surface.blit(ts, (x + 20, y))
    y += row_h

    for key in ["headingMagnetic", "magneticVariation", "cogTrue", "speedOverGround", "rateOfTurn"]:
        val = state.values.get(key)
        src = state.sources.get(key, "")
        dev = state.device_names.get(src, src) if src else ""
        if key == "magneticVariation":
            deg_str = f"{rad_to_deg_signed(val):+.2f}\u00b0" if val is not None else "---\u00b0"
        elif key == "rateOfTurn":
            deg_str = f"{math.degrees(val):+.2f}\u00b0/s" if val is not None else "---\u00b0/s"
        elif key == "speedOverGround":
            deg_str = f"{(val or 0)*1.94384:.1f} kts" if val is not None else "--- kts"
        else:
            deg_str = f"{rad_to_deg(val):06.1f}\u00b0" if val is not None else "---\u00b0"
        row(f"{SIGNAL_LABELS.get(key, key)}:", f"{deg_str}  [{dev}]", SIGNAL_COLORS.get(key, TEXT_WHITE))


def render(surface, font, font_sm, state, rect, sub_tab):
    if sub_tab == 0:
        draw_compass(surface, font, font_sm, state, rect)
    elif sub_tab == 1:
        draw_diagnostics(surface, font, font_sm, state, rect)
    elif sub_tab == 2:
        draw_fusion(surface, font, font_sm, state, rect)


def handle_click(state, mx, my, rect, sub_tab):
    pass


def handle_key(state, key, sub_tab):
    if key == pygame.K_f:
        state.emulation_active = not state.emulation_active
        if not state.emulation_active:
            state.fusion_heading = None
    elif key == pygame.K_RIGHTBRACKET:
        state.heading_offset += 0.5
    elif key == pygame.K_LEFTBRACKET:
        state.heading_offset -= 0.5