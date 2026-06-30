"""Polar Builder page: a real-time coverage heatmap showing which
(TWA, TWS) bins have been sailed, built from named session groups.

The left side is a read-only rose with three layers:
  1. Theoretical active-polar outline (faint).
  2. Coverage heatmap (annular sectors colored by sample count).
  3. Measured mean-speed curves per TWS band.

The right side is an interactive group-management panel: pick a group,
rename it, choose its target polar, add/remove sailing-log sessions. The
group whose polar matches ``state.polar_active`` auto-receives the live
session's samples so coverage grows in real time.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os

import pygame

from pages.rose import (
    angle_to_screen,
    compute_max_speed,
    draw_center_dot,
    draw_radials,
    draw_rose_fill,
    draw_speed_rings,
)
from pages.ui import TextInput
from polars.coverage import (
    TWA_BIN_DEG,
    TWA_MAX_DEG,
    TWA_MIN_DEG,
    build_coverage_from_sessions,
    coverage_counts,
    coverage_mean,
)
from polars.parser import PolarData, compute_true_wind
from signalk.models import MS_TO_KNOTS
from theme import (
    BG,
    BTN_ACTIVE_BG,
    BTN_ACTIVE_BORDER,
    BTN_BG,
    BTN_BORDER,
    CALC,
    COVERAGE_GAP,
    COVERAGE_GRADIENT,
    OK,
    POLAR_BOAT_DOT,
    POLAR_GRID,
    SECTION,
    TEXT_DIM,
    TEXT_LABEL,
    TEXT_MUTED,
    TEXT_VALUE,
    TEXT_WHITE,
    TWS_COLORS,
    WARN,
)

PAD = 12
ROW_H = 22
BTN_H = 24
SECTION_GAP = 10
NAME_FIELD_H = 28

_logger = logging.getLogger("polarprism")

# Max sample count that maps to the brightest gradient stop. Above this,
# intensity is clamped to full bright.
COVERAGE_MAX_COUNT = 30


def _clock_dt_ms(state) -> int:
    """Approximate frame delta for cursor blink. Falls back to 16ms."""
    return getattr(state, "_frame_dt_ms", 16)


def _get_name_input(state, rect, font, group) -> TextInput:
    """Return the cached group-name TextInput for this frame, creating if needed.

    The rect is updated each frame. The text is reset from the group name only
    when the field is inactive (not being edited), so an in-progress edit is
    never clobbered.
    """
    inp = getattr(state, "_pb_name_input", None)
    if inp is None:
        inp = TextInput(rect, font, group.get("name", ""))
        state._pb_name_input = inp
    inp.rect = rect
    inp.font = font
    if not inp.active:
        inp.text = group.get("name", "")
    return inp


def _commit_group_name(state, group) -> None:
    """Commit the edited name from the TextInput onto the group dict."""
    inp = getattr(state, "_pb_name_input", None)
    if inp is None:
        return
    new_name = inp.text.strip()
    if not new_name:
        inp.deactivate()
        return
    if new_name == group.get("name"):
        inp.deactivate()
        return
    # Update the coverage cache key to match the new name, so existing coverage
    # data isn't lost when the group is renamed.
    old_name = group.get("name", "")
    cov = state.polar_builder_coverage.pop(old_name, None)
    ver = state.polar_builder_coverage_version.pop(old_name, None)
    group["name"] = new_name
    if cov is not None:
        state.polar_builder_coverage[new_name] = cov
    if ver is not None:
        state.polar_builder_coverage_version[new_name] = ver
    inp.deactivate()


def render(surface, font, font_sm, state, rect, sub_tab, config=None):
    """Top-level builder section renderer (mirrors other sections)."""
    x, y, w, h = rect
    surface.fill(BG, pygame.Rect(x, y, w, h))
    if not state.polar_builder_groups:
        _draw_empty(surface, font, font_sm, state, rect)
        return
    groups = state.polar_builder_groups
    idx = max(0, min(state.polar_builder_active_group, len(groups) - 1))
    group = groups[idx]
    coverage = _coverage_for_group(state, group)
    polar = state.polar_data.get(group["polar"])
    chart_w = int(w * 0.60)
    cx = x + chart_w // 2
    cy = y + h // 2
    r = min(chart_w, h) // 2 - 20
    base_max = _polar_max_speed(polar) if polar is not None else 10.0
    max_speed = compute_max_speed(base_max)
    draw_rose_fill(surface, cx, cy, r)
    draw_speed_rings(surface, font_sm, cx, cy, r, max_speed)
    draw_radials(surface, font_sm, cx, cy, r)
    if polar is not None:
        _draw_theoretical_outline(surface, polar, cx, cy, r, max_speed)
    _draw_coverage_heatmap(surface, coverage, cx, cy, r, max_speed)
    if polar is not None:
        _draw_measured_curves(surface, coverage, polar, cx, cy, r, max_speed)
    _draw_live_boat_dot(surface, state, group, cx, cy, r, max_speed)
    draw_center_dot(surface, cx, cy, 3)
    _draw_panel(surface, font, font_sm, state, rect, chart_w, group, coverage, config)


def handle_click(state, mx, my, rect, sub_tab, config=None):
    """Click handler for the builder section. Returns a result string or None."""
    if not state.polar_builder_groups:
        _logger.debug("polar_builder click ignored: no groups")
        return None
    x, y, w, _h = rect
    chart_w = int(w * 0.60)
    panel_x = x + chart_w + 20
    if mx < panel_x:
        return None
    return _handle_panel_click(state, mx, my, panel_x, y)


def handle_key(state, event, sub_tab):
    """Key handler for the builder section. Returns a result string or None.

    When the group-name text input is active, it consumes all keys (so an
    in-progress rename isn't hijacked by the group/letter shortcuts); Enter
    commits the new name, Esc cancels.
    """
    import pygame as pg

    name_input = getattr(state, "_pb_name_input", None)
    if name_input is not None and name_input.active:
        result = name_input.handle_key(event)
        if result == "commit":
            groups = state.polar_builder_groups
            idx = max(0, min(state.polar_builder_active_group, len(groups) - 1))
            _commit_group_name(state, groups[idx])
        elif result == "cancel":
            name_input.deactivate()
        return None

    key = event.key
    if key == pg.K_n:
        _new_group(state)
    elif key == pg.K_DELETE or key == pg.K_BACKSPACE:
        _delete_active_group(state)
    elif pg.K_1 <= key <= pg.K_9:
        idx = key - pg.K_1
        if idx < len(state.polar_builder_groups):
            state.polar_builder_active_group = idx
    elif key == pg.K_b:
        return "build_polar"
    elif key == pg.K_c:
        return "combine_best"
    return None


# --- coverage helpers ------------------------------------------------------


def _coverage_for_group(state, group) -> dict[tuple[int, int], list[float]]:
    """Return cached coverage for a group, rebuilding if its session list changed."""
    sessions = list(group.get("sessions", []))
    version = hash(tuple(sessions))
    name = group.get("name", "")
    if state.polar_builder_coverage_version.get(name) != version:
        cov = build_coverage_from_sessions(sessions)
        # Fold in live buffer if this group's polar matches the active polar.
        if group.get("polar") == state.polar_active and state.polar_builder_live_buffer:
            for twa_bin, tws_bin, stw_kts in state.polar_builder_live_buffer:
                cov.setdefault((twa_bin, tws_bin), []).append(stw_kts)
        state.polar_builder_coverage[name] = cov
        state.polar_builder_coverage_version[name] = version
    return state.polar_builder_coverage.get(name) or {}


def _polar_max_speed(polar: PolarData) -> float:
    best = 0.0
    for twa in polar.twa_list:
        row = polar.speed_grid.get(twa, {})
        for tws in polar.tws_list:
            spd = row.get(tws, 0.0)
            if spd > best:
                best = spd
    return best


def _count_color(count: int) -> tuple[int, int, int]:
    """Map a sample count to a gradient color (faint -> bright)."""
    if count <= 0:
        return COVERAGE_GAP
    steps = len(COVERAGE_GRADIENT)
    idx = min(int(count * steps / COVERAGE_MAX_COUNT), steps - 1)
    return COVERAGE_GRADIENT[idx]


# --- rose drawing -----------------------------------------------------------


def _draw_theoretical_outline(surface, polar, cx, cy, r, max_speed):
    """Draw the active polar's speed curves as a faint reference outline."""
    for tws in polar.tws_list:
        for sign in (1, -1):
            pts: list[tuple[int, int]] = []
            for twa_deg in polar.twa_list:
                spd = polar.speed_grid.get(twa_deg, {}).get(tws, 0.0)
                if spd <= 0:
                    continue
                pr = r * spd / max_speed
                px, py = angle_to_screen(cx, cy, pr, sign * twa_deg)
                pts.append((int(px), int(py)))
            if len(pts) > 1:
                pygame.draw.lines(surface, POLAR_GRID, False, pts, 1)


def _draw_coverage_heatmap(surface, coverage, cx, cy, r, max_speed):
    """Draw one annular-sector polygon per coverage bin, colored by count."""
    counts = coverage_counts(coverage)
    if not counts:
        return
    overlay = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
    half = r + 2
    for (twa_bin, tws_bin), count in counts.items():
        samples = coverage[(twa_bin, tws_bin)]
        mean_stw = sum(samples) / len(samples)
        pr = r * mean_stw / max_speed if max_speed > 0 else 0.0
        if pr <= 0:
            continue
        alpha = 120 if count >= 3 else 50
        color = (*_count_color(count), alpha)
        _draw_sector(overlay, half, twa_bin, tws_bin, pr, color)
    surface.blit(overlay, (cx - r - 2, cy - r - 2))


def _draw_sector(overlay, half, twa_bin, tws_bin, pr, color):
    """Draw an annular sector for one coverage bin on the overlay surface."""
    a0 = math.radians(twa_bin - TWA_BIN_DEG / 2) - math.pi / 2
    a1 = math.radians(twa_bin + TWA_BIN_DEG / 2) - math.pi / 2
    inner_r = max(pr - 4, 0)
    steps = 4
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        pts.append((half + math.cos(a) * pr, half + math.sin(a) * pr))
    for i in range(steps + 1):
        a = a1 + (a0 - a1) * i / steps
        pts.append((half + math.cos(a) * inner_r, half + math.sin(a) * inner_r))
    if len(pts) >= 3:
        with contextlib.suppress(TypeError, ValueError):
            pygame.draw.polygon(overlay, color, pts)


def _draw_measured_curves(surface, coverage, polar, cx, cy, r, max_speed):
    """Draw measured mean-speed curves per TWS band of the theoretical polar."""
    means = coverage_mean(coverage)
    if not means:
        return
    for ti, tws in enumerate(polar.tws_list):
        color = TWS_COLORS[ti % len(TWS_COLORS)]
        for sign in (1, -1):
            pts: list[tuple[int, int]] = []
            for twa_bin in range(TWA_MIN_DEG, TWA_MAX_DEG + 1, TWA_BIN_DEG):
                key = (twa_bin, int(tws))
                mean_stw = means.get(key)
                if mean_stw is None:
                    continue
                pr = r * mean_stw / max_speed if max_speed > 0 else 0.0
                if pr <= 0:
                    continue
                px, py = angle_to_screen(cx, cy, pr, sign * twa_bin)
                pts.append((int(px), int(py)))
            if len(pts) > 1:
                pygame.draw.lines(surface, color, False, pts, 2)


def _draw_live_boat_dot(surface, state, group, cx, cy, r, max_speed):
    """Draw the current boat dot if this group is receiving the live feed."""
    if group.get("polar") != state.polar_active:
        return
    if not state.polar_builder_live_buffer:
        return
    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    twa_rad, _ = compute_true_wind(awa_rad, aws_ms, stw_ms)
    if twa_rad is None or stw_ms is None:
        return
    twa_deg = abs(math.degrees(twa_rad))
    stw_kts = stw_ms * MS_TO_KNOTS
    ar = r * stw_kts / max_speed if max_speed > 0 else 0.0
    for sign in (1, -1):
        ax, ay = angle_to_screen(cx, cy, ar, sign * twa_deg)
        pygame.draw.circle(surface, POLAR_BOAT_DOT, (int(ax), int(ay)), 5)


# --- panel -----------------------------------------------------------------


def _draw_empty(surface, font, font_sm, state, rect):
    """Draw the empty-state placeholder."""
    x, y, w, h = rect
    # Clear stale hit-rects so a click on the empty panel can't match the
    # last-rendered Delete/Session-X buttons from the previously active group.
    state._pb_group_rects = []
    state._pb_session_rects = []
    state._pb_polar_rects = []
    state._pb_new_rect = None
    state._pb_del_rect = None
    state._pb_name_rect = None
    state._pb_build_rect = None
    state._pb_combine_rect = None
    msg = font.render("No builder groups yet", True, TEXT_MUTED)
    surface.blit(msg, (x + w // 2 - msg.get_width() // 2, y + h // 2 - 20))
    hint = font_sm.render("Press N to create a group, or sail to auto-seed one", True, TEXT_DIM)
    surface.blit(hint, (x + w // 2 - hint.get_width() // 2, y + h // 2 + 6))


def _draw_panel(surface, font, font_sm, state, rect, chart_w, group, coverage, config):
    """Draw the right-hand group-management panel."""
    x, y, w, _h = rect
    px = x + chart_w + 20
    pw = w - chart_w - 20
    py = y + PAD
    state._pb_group_rects = []
    state._pb_session_rects = []
    state._pb_polar_rects = []
    state._pb_new_rect = None
    state._pb_del_rect = None
    state._pb_name_rect = None
    state._pb_build_rect = None
    state._pb_combine_rect = None

    py = _draw_groups_list(surface, font, font_sm, state, px, py, pw)
    py += SECTION_GAP
    py = _draw_active_group_details(surface, font, font_sm, state, group, px, py, pw)
    py += SECTION_GAP
    py = _draw_sessions(surface, font_sm, state, group, px, py, pw, config)
    py += SECTION_GAP
    py = _draw_available_sessions(surface, font_sm, state, group, px, py, pw, config)
    py += SECTION_GAP
    py = _draw_coverage_stats(surface, font_sm, state, group, coverage, px, py, pw)
    py += SECTION_GAP
    py = _draw_build_button(surface, font_sm, state, group, coverage, px, py, pw)
    py += SECTION_GAP
    _draw_combine_button(surface, font_sm, state, px, py, pw)


def _heading(surface, font, px, py, text):
    ts = font.render(text, True, SECTION)
    surface.blit(ts, (px, py))
    return py + ROW_H + 2


def _row(surface, font_sm, px, py, label, value, color=TEXT_VALUE):
    tl = font_sm.render(label, True, TEXT_LABEL)
    surface.blit(tl, (px, py))
    tv = font_sm.render(value, True, color)
    surface.blit(tv, (px + 110, py))
    return py + ROW_H


def _btn(surface, font_sm, rect, label, active, color=TEXT_WHITE):
    bg = BTN_ACTIVE_BG if active else BTN_BG
    border = BTN_ACTIVE_BORDER if active else BTN_BORDER
    pygame.draw.rect(surface, bg, rect, border_radius=4)
    pygame.draw.rect(surface, border, rect, 1, border_radius=4)
    tc = TEXT_WHITE if active else TEXT_MUTED
    tl = font_sm.render(label, True, tc)
    surface.blit(tl, (rect.x + 6, rect.y + (rect.h - tl.get_height()) // 2))


def _draw_groups_list(surface, font, font_sm, state, px, py, pw):
    py = _heading(surface, font, px, py, "--- Groups ---")
    for i, g in enumerate(state.polar_builder_groups):
        is_active = i == state.polar_builder_active_group
        rect = pygame.Rect(px, py, pw, BTN_H)
        live = g.get("polar") == state.polar_active and state.polar_builder_live_buffer
        label = g.get("name", "?")
        if live:
            label = "\u25cf " + label
        _btn(surface, font_sm, rect, label, is_active)
        state._pb_group_rects.append((i, rect.x, rect.y, rect.w, rect.h))
        py += BTN_H + 4
    new_rect = pygame.Rect(px, py, pw, BTN_H)
    _btn(surface, font_sm, new_rect, "+ New Group", False, color=OK)
    state._pb_new_rect = (new_rect.x, new_rect.y, new_rect.w, new_rect.h)
    return py + BTN_H + 4


def _draw_active_group_details(surface, font, font_sm, state, group, px, py, pw):
    py = _heading(surface, font, px, py, "--- Active Group ---")
    # Editable group-name field (determines the measured polar output name).
    name_rect = pygame.Rect(px, py, pw, NAME_FIELD_H)
    name_input = _get_name_input(state, name_rect, font_sm, group)
    name_input.tick(_clock_dt_ms(state))
    name_input.draw(surface, BTN_BG, BTN_BORDER, TEXT_WHITE)
    state._pb_name_rect = (name_rect.x, name_rect.y, name_rect.w, name_rect.h)
    py += NAME_FIELD_H + 4
    # Polar selector
    pol_lbl = font_sm.render("Polar:", True, TEXT_LABEL)
    surface.blit(pol_lbl, (px, py + 4))
    polar_x = px + 60
    for i, pname in enumerate(state.polar_names):
        rect = pygame.Rect(polar_x + i * 70, py, 64, BTN_H)
        is_active = pname == group.get("polar")
        _btn(surface, font_sm, rect, pname[:8], is_active)
        state._pb_polar_rects.append((i, rect.x, rect.y, rect.w, rect.h))
    py += BTN_H + 4
    # Delete button
    del_rect = pygame.Rect(px, py, pw, BTN_H)
    _btn(surface, font_sm, del_rect, "Delete Group", False, color=WARN)
    state._pb_del_rect = (del_rect.x, del_rect.y, del_rect.w, del_rect.h)
    return py + BTN_H + 4


def _draw_sessions(surface, font_sm, state, group, px, py, pw, config):
    py = _heading_simple(surface, font_sm, px, py, "--- Sessions in Group ---")
    sessions = list(group.get("sessions", []))
    if not sessions:
        ts = font_sm.render("(none yet)", True, TEXT_DIM)
        surface.blit(ts, (px, py))
        return py + ROW_H
    for s in sessions:
        fname = os.path.basename(s)
        rect = pygame.Rect(px, py, pw - 24, BTN_H)
        _btn(surface, font_sm, rect, fname[:24], False)
        x_rect = pygame.Rect(px + pw - 22, py, 22, BTN_H)
        _btn(surface, font_sm, x_rect, "\u2715", False, color=WARN)
        state._pb_session_rects.append((rect.x, rect.y, rect.w, rect.h, False))
        state._pb_session_rects.append((x_rect.x, x_rect.y, x_rect.w, x_rect.h, True))
        py += BTN_H + 2
    return py


def _draw_available_sessions(surface, font_sm, state, group, px, py, pw, config):
    py = _heading_simple(surface, font_sm, px, py, "--- Available Sessions ---")
    in_group = set(group.get("sessions", []))
    log_dir = config.log_dir if config else "sailing_logs"
    try:
        files = sorted(
            f for f in os.listdir(log_dir) if f.startswith("sailing_") and f.endswith(".jsonl")
        )
    except OSError:
        files = []
    avail = [os.path.join(log_dir, f) for f in files if os.path.join(log_dir, f) not in in_group]
    if not avail:
        ts = font_sm.render("(no more sessions)", True, TEXT_DIM)
        surface.blit(ts, (px, py))
        return py + ROW_H
    for s in avail[:20]:
        fname = os.path.basename(s)
        rect = pygame.Rect(px, py, pw - 24, BTN_H)
        _btn(surface, font_sm, rect, fname[:24], False)
        add_rect = pygame.Rect(px + pw - 22, py, 22, BTN_H)
        _btn(surface, font_sm, add_rect, "+", False, color=OK)
        state._pb_session_rects.append((rect.x, rect.y, rect.w, rect.h, False))
        state._pb_session_rects.append((add_rect.x, add_rect.y, add_rect.w, add_rect.h, True))
        py += BTN_H + 2
    return py


def _draw_coverage_stats(surface, font_sm, state, group, coverage, px, py, pw):
    py = _heading_simple(surface, font_sm, px, py, "--- Coverage ---")
    counts = coverage_counts(coverage)
    total = sum(counts.values())
    filled = sum(1 for c in counts.values() if c >= 3)
    # Coverage % vs theoretical grid bins in range.
    polar = state.polar_data.get(group.get("polar"))
    grid_bins = len(polar.twa_list) * len(polar.tws_list) if polar is not None else max(1, filled)
    pct = (filled / grid_bins * 100.0) if grid_bins > 0 else 0.0
    live = group.get("polar") == state.polar_active and bool(state.polar_builder_live_buffer)
    live_color = OK if live else TEXT_DIM
    live_text = "LIVE" if live else "idle"
    py = _row(surface, font_sm, px, py, "Samples:", str(total))
    py = _row(surface, font_sm, px, py, "Bins filled:", f"{filled}")
    py = _row(surface, font_sm, px, py, "Coverage:", f"{pct:.0f}%", color=CALC)
    py = _row(surface, font_sm, px, py, "Live feed:", live_text, color=live_color)
    return py


def _draw_build_button(surface, font_sm, state, group, coverage, px, py, pw):
    """Draw the 'Build measured polar' button and any build-status message."""
    has_data = bool(coverage) or bool(state.polar_builder_live_buffer)
    build_rect = pygame.Rect(px, py, pw, BTN_H + 4)
    label = "BUILD MEASURED POLAR [B]"
    color = OK if has_data else TEXT_DIM
    bg = BTN_ACTIVE_BG if has_data else BTN_BG
    border = BTN_ACTIVE_BORDER if has_data else BTN_BORDER
    pygame.draw.rect(surface, bg, build_rect, border_radius=4)
    pygame.draw.rect(surface, border, build_rect, 1, border_radius=4)
    tl = font_sm.render(label, True, color)
    surface.blit(tl, (build_rect.x + 6, build_rect.y + (build_rect.h - tl.get_height()) // 2))
    state._pb_build_rect = (
        (build_rect.x, build_rect.y, build_rect.w, build_rect.h) if has_data else None
    )
    py += BTN_H + 8
    # Transient build-status message (set by _handle_build_polar in main.py)
    status = getattr(state, "_pb_build_status", None)
    if status:
        ts = font_sm.render(status, True, OK)
        surface.blit(ts, (px, py))
        py += ROW_H
    return py


def _draw_combine_button(surface, font_sm, state, px, py, pw):
    """Draw the 'Combine Best' button.

    Envelope (max STW per bin) across every measured polar currently loaded
    into ``state.polar_data`` (those flagged ``measured=True``). Disabled when
    fewer than two measured polars are available.
    """
    measured_count = sum(1 for p in state.polar_data.values() if getattr(p, "measured", False))
    can_combine = measured_count >= 2
    rect = pygame.Rect(px, py, pw, BTN_H + 4)
    label = f"COMBINE BEST ({measured_count}) [C]"
    color = OK if can_combine else TEXT_DIM
    bg = BTN_ACTIVE_BG if can_combine else BTN_BG
    border = BTN_ACTIVE_BORDER if can_combine else BTN_BORDER
    pygame.draw.rect(surface, bg, rect, border_radius=4)
    pygame.draw.rect(surface, border, rect, 1, border_radius=4)
    tl = font_sm.render(label, True, color)
    surface.blit(tl, (rect.x + 6, rect.y + (rect.h - tl.get_height()) // 2))
    state._pb_combine_rect = (rect.x, rect.y, rect.w, rect.h) if can_combine else None
    return py + BTN_H + 8


def _heading_simple(surface, font_sm, px, py, text):
    ts = font_sm.render(text, True, SECTION)
    surface.blit(ts, (px, py))
    return py + ROW_H


# --- click handling --------------------------------------------------------


def _handle_panel_click(state, mx, my, panel_x, panel_y):
    if not state.polar_builder_groups:
        return None
    # Group selection
    for i, rx, ry, rw, rh in state._pb_group_rects:
        if rx <= mx <= rx + rw and ry <= my <= ry + rh:
            state.polar_builder_active_group = i
            return None
    # New group
    if state._pb_new_rect and _hit(mx, my, state._pb_new_rect):
        _new_group(state)
        return None
    # Delete group
    if state._pb_del_rect and _hit(mx, my, state._pb_del_rect):
        _delete_active_group(state)
        return None
    # Group-name text input: click to activate, click-away to commit.
    groups = state.polar_builder_groups
    idx = max(0, min(state.polar_builder_active_group, len(groups) - 1))
    group = groups[idx]
    name_input = getattr(state, "_pb_name_input", None)
    if state._pb_name_rect and _hit(mx, my, state._pb_name_rect):
        if name_input is not None:
            name_input.activate(group.get("name", ""))
        return None
    if name_input is not None and name_input.active:
        _commit_group_name(state, group)
    # Build measured polar
    if state._pb_build_rect and _hit(mx, my, state._pb_build_rect):
        return "build_polar"
    # Combine best
    if state._pb_combine_rect and _hit(mx, my, state._pb_combine_rect):
        return "combine_best"
    # Polar selector
    for i, rx, ry, rw, rh in state._pb_polar_rects:
        if rx <= mx <= rx + rw and ry <= my <= ry + rh:
            if i < len(state.polar_names):
                group["polar"] = state.polar_names[i]
                _invalidate_coverage(state, group)
            return None
    # Session add/remove
    _handle_session_click(state, mx, my, group, panel_x)
    return None


def _handle_session_click(state, mx, my, group, panel_x):
    sessions = list(group.get("sessions", []))
    for i in range(0, len(state._pb_session_rects), 2):
        if i + 1 >= len(state._pb_session_rects):
            break
        action_rect = state._pb_session_rects[i + 1]
        row_idx = i // 2
        # Determine if this row is a "remove from group" (action is True)
        # vs "add to group" (action is False). We stored action flag in [5].
        # Rows are paired: even = left button, odd = right action button.
        if _hit(mx, my, action_rect[:4]):
            is_remove = action_rect[4]
            if is_remove and row_idx < len(sessions):
                sessions.pop(row_idx)
                group["sessions"] = sessions
                _invalidate_coverage(state, group)
            elif not is_remove:
                # Add: find the corresponding available file.
                _add_available_session(state, group, row_idx)
            return


def _add_available_session(state, group, row_idx):
    """Add the row_idx-th available session to the group."""
    in_group = set(group.get("sessions", []))
    # The active group's sessions hold absolute paths; use their dir as a hint.
    if group.get("sessions"):
        log_dir = os.path.dirname(group["sessions"][0])
    else:
        # Fallback: try any other group's session dir, else default.
        for g in state.polar_builder_groups:
            if g.get("sessions"):
                log_dir = os.path.dirname(g["sessions"][0])
                break
        else:
            log_dir = "sailing_logs"
    try:
        files = sorted(
            f for f in os.listdir(log_dir) if f.startswith("sailing_") and f.endswith(".jsonl")
        )
    except OSError:
        return
    avail = [os.path.join(log_dir, f) for f in files if os.path.join(log_dir, f) not in in_group]
    if row_idx < len(avail):
        group.setdefault("sessions", []).append(avail[row_idx])
        _invalidate_coverage(state, group)


def _hit(mx, my, rect):
    rx, ry, rw, rh = rect
    return rx <= mx <= rx + rw and ry <= my <= ry + rh


def _invalidate_coverage(state, group):
    name = group.get("name", "")
    state.polar_builder_coverage_version.pop(name, None)


def _new_group(state):
    name = f"Group {len(state.polar_builder_groups) + 1}"
    polar = (
        state.polar_active
        if state.polar_active
        else (state.polar_names[0] if state.polar_names else "")
    )
    state.polar_builder_groups.append({"name": name, "polar": polar, "sessions": []})
    state.polar_builder_active_group = len(state.polar_builder_groups) - 1


def _delete_active_group(state):
    if not state.polar_builder_groups:
        return
    idx = state.polar_builder_active_group
    name = state.polar_builder_groups[idx].get("name", "")
    state.polar_builder_coverage.pop(name, None)
    state.polar_builder_coverage_version.pop(name, None)
    name_input = getattr(state, "_pb_name_input", None)
    if name_input is not None:
        name_input.deactivate()
    state.polar_builder_groups.pop(idx)
    if state.polar_builder_active_group >= len(state.polar_builder_groups):
        state.polar_builder_active_group = max(0, len(state.polar_builder_groups) - 1)
