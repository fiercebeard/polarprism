import logging
import os

import pygame

from config import SETUP_CHECKLIST, save_config
from pages.ui import TextInput, draw_heading, draw_row
from signalk.filters import DEFAULT_CUTOFF_HZ, FILTERABLE_SIGNALS, analyze_log
from theme import (
    BG,
    BTN_ACTIVE_BG,
    BTN_ACTIVE_BORDER,
    BTN_BG,
    BTN_BORDER,
    CALC,
    CONNECTED,
    DISCONNECTED,
    IDLE_COLOR,
    OK,
    SAILING_ACTIVE,
    SAILING_INACTIVE,
    SETUP_EXPAND_CHEVRON,
    SETUP_ROW_H,
    TEXT_DIM,
    TEXT_MUTED,
    TEXT_VALUE,
    TEXT_WHITE,
    WARN,
)

_logger = logging.getLogger("polarprism")

ROW_H = 24
BTN_W = 36
BTN_H = 24
INDENT = 20
STEP_ROW_H = 20
URL_FIELD_H = 28
URL_FIELD_W = 360


def _get_url_input(state, rect, font, config) -> TextInput:
    """Return the cached URL TextInput for this frame, creating if needed.

    The TextInput's rect is updated each frame so layout changes (window
    resize) are reflected. The text is only reset from config when the field
    is inactive and not being edited.
    """
    inp = getattr(state, "_sk_url_input", None)
    if inp is None:
        url = config.signalk_url if config else "ws://localhost:3000"
        inp = TextInput(rect, font, url)
        state._sk_url_input = inp
    inp.rect = rect
    inp.font = font
    if not inp.active:
        inp.text = config.signalk_url if config else "ws://localhost:3000"
    return inp


def _commit_sail_config(state, config) -> None:
    """Persist the current sail groups/colors/polar_map to polarprism.toml."""
    if config is None:
        return
    config.sail_groups = list(state.sail_groups)
    config.sail_to_polar = dict(state.sail_to_polar)
    config.sail_colors = dict(state.sail_colors)
    try:
        save_config(config)
        state._sail_save_status = "Saved to " + (config._source_path or "polarprism.toml")
    except Exception as exc:
        _logger.warning("could not write sail config: %s", exc, exc_info=True)
        state._sail_save_status = f"Save failed: {exc}"


def _commit_url(state, config) -> str:
    """Persist the edited URL to polarprism.toml and signal a reconnect."""
    inp = getattr(state, "_sk_url_input", None)
    if inp is None:
        return ""
    new_url = inp.text.strip()
    if not new_url:
        inp.deactivate()
        return ""
    if new_url == config.signalk_url:
        inp.deactivate()
        return ""
    config.signalk_url = new_url
    from config import ws_url_to_rest_url

    config.signalk_rest_url = ws_url_to_rest_url(new_url)
    try:
        save_config(config)
    except Exception:
        _logger.warning(
            "could not write polarprism.toml; URL change is session-only", exc_info=True
        )
    inp.deactivate()
    return "sk_reconnect"


def _last_frame_ms(state) -> int:
    """Approximate frame delta for cursor blink. Falls back to 16ms."""
    return getattr(state, "_frame_dt_ms", 16)


# Alias kept for readability at call site.
def clock_dt_ms(state) -> int:
    return _last_frame_ms(state)


def _draw_setup_tab(surface, font, font_sm, state, rect, config):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))
    ry = y0 + 16

    draw_heading(surface, font_sm, x + 20, ry, "--- Setup Checklist ---")
    ry += ROW_H + 4

    expanded = getattr(state, "_setup_expanded", set())

    section_rects = []
    for item in SETUP_CHECKLIST:
        status_fn = item["status_fn"]
        status = status_fn(state, config)
        is_ok = status == "ok"
        is_warn = status == "warn"

        dot_color = OK if is_ok else (WARN if is_warn else DISCONNECTED)

        if is_ok:
            status_label = item.get("ok_text", "OK")
        elif is_warn:
            status_label = item.get("warn_text", "Warning")
        else:
            status_label = item.get("missing_text", "Not set up")

        row_rect = pygame.Rect(x + 10, ry, w - 20, SETUP_ROW_H)
        section_rects.append((item["key"], pygame.Rect(x, ry, w, SETUP_ROW_H)))

        if is_ok:
            bg_fill = (20, 35, 20)
        elif is_warn:
            bg_fill = (35, 30, 15)
        else:
            bg_fill = (35, 20, 20)
        pygame.draw.rect(surface, bg_fill, row_rect, border_radius=6)

        dot_cy = ry + SETUP_ROW_H // 2
        pygame.draw.circle(surface, dot_color, (x + 30, dot_cy), 6)

        title_surf = font.render(item["title"], True, TEXT_WHITE)
        surface.blit(title_surf, (x + 46, ry + (SETUP_ROW_H - title_surf.get_height()) // 2))

        status_surf = font_sm.render(status_label, True, dot_color)
        surface.blit(
            status_surf,
            (
                x + w - 30 - status_surf.get_width(),
                ry + (SETUP_ROW_H - status_surf.get_height()) // 2,
            ),
        )

        key = item["key"]
        chevron = "\u25bc" if key in expanded else "\u25b6"
        chev_surf = font_sm.render(chevron, True, SETUP_EXPAND_CHEVRON)
        surface.blit(
            chev_surf,
            (x + w - 26, ry + (SETUP_ROW_H - chev_surf.get_height()) // 2),
        )

        ry += SETUP_ROW_H + 2

        if key in expanded:
            for i, step in enumerate(item["steps"]):
                step_num = font_sm.render(f"{i + 1}.", True, TEXT_DIM)
                step_text = font_sm.render(step, True, TEXT_MUTED)
                surface.blit(step_num, (x + 46, ry + 2))
                surface.blit(step_text, (x + 66, ry + 2))
                ry += STEP_ROW_H
            ry += 6

    state._setup_section_rects = section_rects


def render(surface, font, font_sm, state, rect, sub_tab, config=None):
    x, y, w, h = rect
    surface.fill(BG, (x, y, w, h))

    ry = y + 20

    if sub_tab == 0:
        ry += 4
        draw_heading(surface, font_sm, x + 20, ry, "--- SignalK Connection ---")
        ry += ROW_H

        conn_color = CONNECTED if state.connected else DISCONNECTED
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            "WebSocket:",
            "CONNECTED" if state.connected else "DISCONNECTED",
            label_x=x + 20,
            value_x=x + 200,
            color=conn_color,
        )
        ry += ROW_H

        url_label = font_sm.render("URL:", True, TEXT_WHITE)
        surface.blit(url_label, (x + 20, ry + (URL_FIELD_H - url_label.get_height()) // 2))
        url_rect = pygame.Rect(x + 80, ry, URL_FIELD_W, URL_FIELD_H)
        url_input = _get_url_input(state, url_rect, font_sm, config)
        url_input.tick(clock_dt_ms(state))
        url_input.draw(surface, BTN_BG, BTN_BORDER, TEXT_WHITE)
        state._sk_url_rect = url_rect
        if url_input.active:
            hint = font_sm.render("Enter=saved+reconnect  Esc=cancel", True, TEXT_DIM)
            surface.blit(hint, (url_rect.right + 12, ry + (URL_FIELD_H - hint.get_height()) // 2))
        else:
            hint = font_sm.render("click to edit", True, TEXT_DIM)
            surface.blit(hint, (url_rect.right + 12, ry + (URL_FIELD_H - hint.get_height()) // 2))
        ry += URL_FIELD_H + 4

        reconnect_rect = pygame.Rect(x + 20, ry, 180, 28)
        pygame.draw.rect(surface, BTN_ACTIVE_BG, reconnect_rect, border_radius=4)
        pygame.draw.rect(surface, BTN_ACTIVE_BORDER, reconnect_rect, 1, border_radius=4)
        rt = font_sm.render("Reconnect", True, TEXT_WHITE)
        surface.blit(
            rt,
            (
                reconnect_rect.x + reconnect_rect.w // 2 - rt.get_width() // 2,
                reconnect_rect.y + reconnect_rect.h // 2 - rt.get_height() // 2,
            ),
        )
        state._sk_reconnect_rect = reconnect_rect
        ry += ROW_H + 16

        draw_heading(surface, font_sm, x + 20, ry, "--- Vessel ---")
        ry += ROW_H
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            "Vessel:",
            state.vessel_name or "---",
            label_x=x + 20,
            value_x=x + 200,
        )
        ry += ROW_H

        ry += 12
        draw_heading(surface, font_sm, x + 20, ry, "--- N2K Devices ---")
        ry += ROW_H

        for src, name in sorted(state.device_names.items()):
            draw_row(
                surface,
                font_sm,
                x,
                ry,
                f"{src}:",
                name,
                label_x=x + 20,
                value_x=x + 200,
                color=TEXT_MUTED,
            )
            ry += ROW_H

    elif sub_tab == 1:
        _draw_sails_tab(surface, font, font_sm, state, rect, config)

    elif sub_tab == 2:
        ry += 4
        draw_heading(surface, font_sm, x + 20, ry, "--- Display ---")
        ry += ROW_H

        draw_row(
            surface,
            font_sm,
            x,
            ry,
            "Heading Offset:",
            f"{state.heading_offset:+.1f}\u00b0",
            label_x=x + 20,
            value_x=x + 200,
        )
        ry += ROW_H

        minus_rect = pygame.Rect(x + 200, ry, BTN_W, BTN_H)
        pygame.draw.rect(surface, BTN_BG, minus_rect, border_radius=3)
        pygame.draw.rect(surface, BTN_BORDER, minus_rect, 1, border_radius=3)
        mt = font_sm.render("-", True, TEXT_WHITE)
        surface.blit(
            mt,
            (
                minus_rect.x + BTN_W // 2 - mt.get_width() // 2,
                minus_rect.y + BTN_H // 2 - mt.get_height() // 2,
            ),
        )
        state._offset_minus_rect = minus_rect

        plus_rect = pygame.Rect(x + 240, ry, BTN_W, BTN_H)
        pygame.draw.rect(surface, BTN_BG, plus_rect, border_radius=3)
        pygame.draw.rect(surface, BTN_BORDER, plus_rect, 1, border_radius=3)
        pt = font_sm.render("+", True, TEXT_WHITE)
        surface.blit(
            pt,
            (
                plus_rect.x + BTN_W // 2 - pt.get_width() // 2,
                plus_rect.y + BTN_H // 2 - pt.get_height() // 2,
            ),
        )
        state._offset_plus_rect = plus_rect

        key_hint = font_sm.render("or [\u200b / ] keys", True, TEXT_DIM)
        surface.blit(key_hint, (x + 284, ry + 4))
        ry += ROW_H

        ry += 12
        draw_heading(surface, font_sm, x + 20, ry, "--- Status ---")
        ry += ROW_H
        has_polars = bool(state.polar_data)
        has_routes = bool(state.routes)
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            "Polars:",
            f"{len(state.polar_data)} loaded" if has_polars else "None (add CSVs to polars/)",
            label_x=x + 20,
            value_x=x + 200,
            color=TEXT_WHITE if has_polars else DISCONNECTED,
        )
        ry += ROW_H
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            "Routes:",
            f"{len(state.routes)} loaded" if has_routes else "None (add GPX to routes/)",
            label_x=x + 20,
            value_x=x + 200,
            color=TEXT_WHITE if has_routes else DISCONNECTED,
        )
        ry += ROW_H

        ry += 12
        draw_heading(surface, font_sm, x + 20, ry, "--- Logging ---")
        ry += ROW_H

        log_status = "RECORDING" if state.sailing_log_active else "STOPPED"
        log_color = SAILING_ACTIVE if state.sailing_log_active else SAILING_INACTIVE
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            "Status:",
            log_status,
            label_x=x + 20,
            value_x=x + 200,
            color=log_color,
        )
        ry += ROW_H

        if state.sailing_log_active:
            fname = state.performance_log_file or "---"
            if "/" in fname:
                fname = fname.rsplit("/", 1)[-1]
            draw_row(surface, font_sm, x, ry, "File:", fname, label_x=x + 20, value_x=x + 200)
            ry += ROW_H
            draw_row(
                surface,
                font_sm,
                x,
                ry,
                "Samples:",
                str(state.log_sample_count),
                label_x=x + 20,
                value_x=x + 200,
            )
            ry += ROW_H
            if state.log_sample_count > 0:
                avg = state.log_perf_sum / state.log_sample_count
                pc = OK if avg >= 95 else (WARN if avg < 80 else IDLE_COLOR)
                draw_row(
                    surface,
                    font_sm,
                    x,
                    ry,
                    "Avg Perf:",
                    f"{avg:.1f}%",
                    label_x=x + 20,
                    value_x=x + 200,
                    color=pc,
                )
                ry += ROW_H
        else:
            draw_row(
                surface,
                font_sm,
                x,
                ry,
                "File:",
                "(not recording)",
                label_x=x + 20,
                value_x=x + 200,
                color=TEXT_DIM,
            )
            ry += ROW_H

    elif sub_tab == 3:
        _draw_filters_tab(surface, font, font_sm, state, rect, config)
    else:
        _draw_setup_tab(surface, font, font_sm, state, rect, config)


def _draw_sails_tab(surface, font, font_sm, state, rect, config):
    """Render the Sails tab: show groups, colors, polar_map, and a Save button."""
    x, y, _w, _h = rect
    ry = y + 20
    ry += 4
    draw_heading(surface, font_sm, x + 20, ry, "--- Sail Groups ---")
    ry += ROW_H
    if not state.sail_groups:
        ts = font_sm.render("(no sail groups — add a .saildef to polars/)", True, TEXT_DIM)
        surface.blit(ts, (x + 20, ry))
        ry += ROW_H
    for group_name, group_sails in state.sail_groups:
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            group_name.capitalize() + ":",
            ", ".join(group_sails),
            label_x=x + 20,
            value_x=x + 120,
        )
        ry += ROW_H

    ry += 12
    draw_heading(surface, font_sm, x + 20, ry, "--- Sail Colors ---")
    ry += ROW_H
    for sail_name in sorted(state.sail_colors.keys()):
        color = state.sail_colors[sail_name]
        color_str = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
        # Draw a color swatch
        swatch = pygame.Rect(x + 20, ry + 2, 16, 16)
        pygame.draw.rect(surface, color, swatch, border_radius=2)
        pygame.draw.rect(surface, BTN_BORDER, swatch, 1, border_radius=2)
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            sail_name + ":",
            color_str,
            label_x=x + 44,
            value_x=x + 120,
        )
        ry += ROW_H

    ry += 12
    draw_heading(surface, font_sm, x + 20, ry, "--- Polar Map ---")
    ry += ROW_H
    if not state.sail_to_polar:
        ts = font_sm.render("(auto-derived from .saildef and polar filenames)", True, TEXT_DIM)
        surface.blit(ts, (x + 20, ry))
        ry += ROW_H
    for sail_name, polar_name in sorted(state.sail_to_polar.items()):
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            sail_name + ":",
            polar_name,
            label_x=x + 20,
            value_x=x + 120,
        )
        ry += ROW_H

    if state.sail_to_polar:
        ts = font_sm.render(
            "Note: polar_map drives display names only; selecting a sail never changes the active polar.",
            True,
            TEXT_DIM,
        )
        surface.blit(ts, (x + 20, ry))
        ry += ROW_H

    ry += 16
    # Save button — persists current sail config to polarprism.toml
    save_rect = pygame.Rect(x + 20, ry, 240, 28)
    pygame.draw.rect(surface, BTN_ACTIVE_BG, save_rect, border_radius=4)
    pygame.draw.rect(surface, BTN_ACTIVE_BORDER, save_rect, 1, border_radius=4)
    st = font_sm.render("Save Sail Config to TOML", True, TEXT_WHITE)
    surface.blit(st, (save_rect.x + 12, save_rect.y + (save_rect.h - st.get_height()) // 2))
    state._sail_save_rect = save_rect
    ry += ROW_H + 8

    status = getattr(state, "_sail_save_status", "")
    if status:
        ts = font_sm.render(status, True, OK)
        surface.blit(ts, (x + 20, ry))
        ry += ROW_H


# --- Filters tab -----------------------------------------------------------

FILTER_FILE_ROW_H = 20
FILTER_SUGGEST_ROW_H = 22
FILTER_BTN_H = 28


def _list_sailing_logs(log_dir: str) -> list[str]:
    """Return sorted list of sailing-log JSONL basenames in log_dir."""
    try:
        names = sorted(f for f in os.listdir(log_dir) if f.endswith(".jsonl"))
    except OSError:
        return []
    return names


def _draw_filters_tab(surface, font, font_sm, state, rect, config):
    """GPS motion-artifact filter settings: analyze, suggest, enable."""
    x, y, _w, _h = rect
    ry = y + 20
    ry += 4
    draw_heading(surface, font_sm, x + 20, ry, "--- GPS Signal Filters ---")
    ry += ROW_H

    enabled = bool(config.filter_enabled)
    draw_row(
        surface,
        font_sm,
        x,
        ry,
        "Filtering:",
        "ENABLED" if enabled else "DISABLED",
        label_x=x + 20,
        value_x=x + 200,
        color=OK if enabled else IDLE_COLOR,
    )
    ry += ROW_H

    toggle_rect = pygame.Rect(x + 200, ry, 120, BTN_H)
    bg = BTN_ACTIVE_BG if enabled else BTN_BG
    border = BTN_ACTIVE_BORDER if enabled else BTN_BORDER
    pygame.draw.rect(surface, bg, toggle_rect, border_radius=4)
    pygame.draw.rect(surface, border, toggle_rect, 1, border_radius=4)
    tt = font_sm.render("ON" if enabled else "OFF", True, TEXT_WHITE)
    surface.blit(
        tt,
        (
            toggle_rect.x + toggle_rect.w // 2 - tt.get_width() // 2,
            toggle_rect.y + toggle_rect.h // 2 - tt.get_height() // 2,
        ),
    )
    state._filter_toggle_rect = toggle_rect
    ry += BTN_H + 4

    hint = font_sm.render(
        "Low-pass filters COG/SOG to suppress mast-sway motion artifacts.",
        True,
        TEXT_DIM,
    )
    surface.blit(hint, (x + 20, ry))
    ry += ROW_H

    # --- Sailing log file picker ---
    ry += 4
    draw_heading(surface, font_sm, x + 20, ry, "--- Sailing Log ---")
    ry += ROW_H

    log_dir = config.log_dir if config else ""
    files = _list_sailing_logs(log_dir)
    selected_idx = getattr(state, "_filter_log_idx", 0)
    if not files:
        ts = font_sm.render("(no sailing logs found — record one first)", True, TEXT_DIM)
        surface.blit(ts, (x + 20, ry))
        ry += FILTER_FILE_ROW_H
    else:
        if selected_idx >= len(files):
            selected_idx = 0
        show_count = min(len(files), 6)
        start = max(0, selected_idx - show_count // 2)
        end = min(len(files), start + show_count)
        start = max(0, end - show_count)
        file_rects = []
        for i in range(start, end):
            fname = files[i]
            is_sel = i == selected_idx
            row_rect = pygame.Rect(x + 20, ry, 380, FILTER_FILE_ROW_H)
            color = BTN_ACTIVE_BG if is_sel else BG
            pygame.draw.rect(surface, color, row_rect, border_radius=3)
            pygame.draw.rect(surface, BTN_BORDER, row_rect, 1, border_radius=3)
            fname_color = TEXT_WHITE if is_sel else TEXT_MUTED
            ts = font_sm.render(fname, True, fname_color)
            surface.blit(ts, (row_rect.x + 8, ry + 2))
            file_rects.append((i, row_rect))
            ry += FILTER_FILE_ROW_H
        state._filter_file_rects = file_rects
        state._filter_files = files

        nav_hint = font_sm.render("click to select; Analyze runs the spectral scan", True, TEXT_DIM)
        surface.blit(nav_hint, (x + 20, ry))
        ry += FILTER_FILE_ROW_H

    # Analyze button
    analyze_rect = pygame.Rect(x + 20, ry, 140, FILTER_BTN_H)
    pygame.draw.rect(surface, BTN_ACTIVE_BG, analyze_rect, border_radius=4)
    pygame.draw.rect(surface, BTN_ACTIVE_BORDER, analyze_rect, 1, border_radius=4)
    at = font_sm.render("Analyze", True, TEXT_WHITE)
    surface.blit(
        at,
        (
            analyze_rect.x + analyze_rect.w // 2 - at.get_width() // 2,
            analyze_rect.y + analyze_rect.h // 2 - at.get_height() // 2,
        ),
    )
    state._filter_analyze_rect = analyze_rect
    ry += FILTER_BTN_H + 4

    # Analyze status / error
    status = getattr(state, "_filter_analyze_status", "")
    if status:
        color = WARN if status.startswith("Error") else CALC
        ts = font_sm.render(status, True, color)
        surface.blit(ts, (x + 20, ry))
        ry += ROW_H

    # --- Suggestions ---
    suggestions = getattr(state, "_filter_suggestions", [])
    if suggestions:
        ry += 4
        draw_heading(surface, font_sm, x + 20, ry, "--- Suggested Filters ---")
        ry += ROW_H

        accept_rects = []
        for i, s in enumerate(suggestions):
            signal = s.get("signal", "")
            cutoff = s.get("cutoff_hz", DEFAULT_CUTOFF_HZ)
            artifact = s.get("artifact_hz")
            power_db = s.get("artifact_power_db")
            baseline_db = s.get("baseline_power_db")

            sig_label = "COG" if signal == "cogTrue" else "SOG"
            line = f"{sig_label}: cutoff {cutoff:.3f} Hz"
            if artifact and power_db is not None and baseline_db is not None:
                line += f"  | artifact {artifact:.3f} Hz ({power_db - baseline_db:+.1f} dB)"
            ts = font_sm.render(line, True, TEXT_VALUE)
            surface.blit(ts, (x + 20, ry))
            ry += FILTER_SUGGEST_ROW_H - 2

            reason = s.get("reason", "")
            ts = font_sm.render(reason, True, TEXT_DIM)
            surface.blit(ts, (x + 40, ry))
            ry += FILTER_SUGGEST_ROW_H - 2

            accept_rect = pygame.Rect(x + 460, ry - FILTER_SUGGEST_ROW_H + 2, 90, BTN_H)
            pygame.draw.rect(surface, BTN_BG, accept_rect, border_radius=3)
            pygame.draw.rect(surface, BTN_BORDER, accept_rect, 1, border_radius=3)
            act = font_sm.render("Accept", True, TEXT_WHITE)
            surface.blit(
                act,
                (
                    accept_rect.x + accept_rect.w // 2 - act.get_width() // 2,
                    accept_rect.y + accept_rect.h // 2 - act.get_height() // 2,
                ),
            )
            accept_rects.append((i, accept_rect))
            ry += 4

        state._filter_accept_rects = accept_rects

        # Save button
        save_rect = pygame.Rect(x + 20, ry, 240, FILTER_BTN_H)
        pygame.draw.rect(surface, BTN_ACTIVE_BG, save_rect, border_radius=4)
        pygame.draw.rect(surface, BTN_ACTIVE_BORDER, save_rect, 1, border_radius=4)
        st = font_sm.render("Save Filters to TOML", True, TEXT_WHITE)
        surface.blit(
            st,
            (
                save_rect.x + 12,
                save_rect.y + (save_rect.h - st.get_height()) // 2,
            ),
        )
        state._filter_save_rect = save_rect
        ry += FILTER_BTN_H + 4
    else:
        state._filter_accept_rects = []

    save_status = getattr(state, "_filter_save_status", "")
    if save_status:
        color = OK if save_status.startswith("Saved") else WARN
        ts = font_sm.render(save_status, True, color)
        surface.blit(ts, (x + 20, ry))
        ry += ROW_H

    # Show current active cutoffs
    ry += 4
    draw_heading(surface, font_sm, x + 20, ry, "--- Active Cutoffs ---")
    ry += ROW_H
    for sig in FILTERABLE_SIGNALS:
        sig_label = "COG" if sig == "cogTrue" else "SOG"
        cutoff = config.filter_cutoffs.get(sig, DEFAULT_CUTOFF_HZ)
        draw_row(
            surface,
            font_sm,
            x,
            ry,
            f"{sig_label}:",
            f"{cutoff:.3f} Hz ({1.0 / cutoff:.0f}s period)" if cutoff > 0 else "off",
            label_x=x + 20,
            value_x=x + 200,
        )
        ry += ROW_H


def _handle_filters_click(state, mx, my, config):
    """Handle clicks on the Filters tab."""
    # Toggle enable/disable
    toggle_rect = getattr(state, "_filter_toggle_rect", None)
    if toggle_rect and toggle_rect.collidepoint(mx, my):
        config.filter_enabled = not config.filter_enabled
        fm = getattr(state, "filter_manager", None)
        if fm is not None:
            fm.config.enabled = config.filter_enabled
            if not config.filter_enabled:
                fm.reset()
        _save_filters(state, config)
        return

    # File picker
    file_rects = getattr(state, "_filter_file_rects", [])
    for idx, rect in file_rects:
        if rect.collidepoint(mx, my):
            state._filter_log_idx = idx
            return

    # Analyze button
    analyze_rect = getattr(state, "_filter_analyze_rect", None)
    if analyze_rect and analyze_rect.collidepoint(mx, my):
        _run_filter_analysis(state, config)
        return

    # Accept suggestion buttons
    accept_rects = getattr(state, "_filter_accept_rects", [])
    for i, rect in accept_rects:
        if rect.collidepoint(mx, my):
            suggestions = getattr(state, "_filter_suggestions", [])
            if i < len(suggestions):
                s = suggestions[i]
                signal = s.get("signal", "")
                cutoff = s.get("cutoff_hz", DEFAULT_CUTOFF_HZ)
                if signal:
                    config.filter_cutoffs[signal] = cutoff
                    fm = getattr(state, "filter_manager", None)
                    if fm is not None:
                        fm.config.cutoffs[signal] = cutoff
                        f = fm._filters.get(signal)
                        if f is not None:
                            f.set_cutoff(cutoff)
                            f.reset()
            return

    # Save button
    save_rect = getattr(state, "_filter_save_rect", None)
    if save_rect and save_rect.collidepoint(mx, my):
        _save_filters(state, config)
        return


def _run_filter_analysis(state, config):
    """Run spectral analysis on the selected sailing log."""
    files = getattr(state, "_filter_files", [])
    idx = getattr(state, "_filter_log_idx", 0)
    if not files or idx >= len(files):
        state._filter_analyze_status = "Error: no sailing log selected"
        return
    log_dir = config.log_dir if config else ""
    path = os.path.join(log_dir, files[idx])
    if not os.path.exists(path):
        state._filter_analyze_status = f"Error: file not found: {files[idx]}"
        return
    state._filter_analyze_status = "Analyzing..."
    try:
        suggestions = analyze_log(path)
        state._filter_suggestions = [s.to_dict() for s in suggestions]
        if not suggestions:
            state._filter_analyze_status = "No analyzable signals (need >= 2 min of data)"
        else:
            state._filter_analyze_status = f"Found {len(suggestions)} suggestion(s)"
    except Exception as exc:
        _logger.warning("filter analysis failed: %s", exc, exc_info=True)
        state._filter_analyze_status = f"Error: {exc}"
        state._filter_suggestions = []


def _save_filters(state, config):
    """Persist filter config to polarprism.toml."""
    if config is None:
        return
    try:
        save_config(config)
        state._filter_save_status = "Saved to " + (config._source_path or "polarprism.toml")
    except Exception as exc:
        _logger.warning("could not write filter config: %s", exc, exc_info=True)
        state._filter_save_status = f"Save failed: {exc}"


def handle_click(state, mx, my, rect, sub_tab, config=None):
    if sub_tab == 0:
        url_input = getattr(state, "_sk_url_input", None)
        url_rect = getattr(state, "_sk_url_rect", None)
        if url_rect and url_rect.collidepoint(mx, my):
            if url_input is not None:
                if not url_input.active:
                    url_input.activate(config.signalk_url if config else "ws://localhost:3000")
                # Place the caret where the user clicked (works while already
                # editing too, so clicking mid-text just moves the caret).
                url_input.place_cursor_from_x(mx)
            return None
        if url_input is not None and url_input.active:
            url_input.deactivate()
        reconnect_rect = getattr(state, "_sk_reconnect_rect", None)
        if reconnect_rect and reconnect_rect.collidepoint(mx, my):
            return "sk_reconnect"
    elif sub_tab == 1:
        # Sails tab: Save button
        save_rect = getattr(state, "_sail_save_rect", None)
        if save_rect and save_rect.collidepoint(mx, my):
            _commit_sail_config(state, config)
            return None
    elif sub_tab == 2:
        minus_rect = getattr(state, "_offset_minus_rect", None)
        if minus_rect and minus_rect.collidepoint(mx, my):
            state.heading_offset -= 0.5
            return None
        plus_rect = getattr(state, "_offset_plus_rect", None)
        if plus_rect and plus_rect.collidepoint(mx, my):
            state.heading_offset += 0.5
            return None
    elif sub_tab == 3:
        _handle_filters_click(state, mx, my, config)
    elif sub_tab == 4:
        section_rects = getattr(state, "_setup_section_rects", None)
        if section_rects:
            expanded = getattr(state, "_setup_expanded", set())
            for key, rect_item in section_rects:
                if rect_item.collidepoint(mx, my):
                    expanded = expanded - {key} if key in expanded else expanded | {key}
                    state._setup_expanded = expanded
                    return None
    return None


def handle_key(state, event, sub_tab, config=None):
    """Route KEYDOWN events to the active UI element (e.g. the URL editor).

    Returns 'sk_reconnect' when a URL edit is committed and the connection
    should be restarted, otherwise None.
    """
    if sub_tab != 0:
        return None
    url_input = getattr(state, "_sk_url_input", None)
    if url_input is None or not url_input.active:
        return None
    result = url_input.handle_key(event)
    if result == "commit":
        return _commit_url(state, config)
    if result == "cancel":
        url_input.text = config.signalk_url if config else "ws://localhost:3000"
        return None
    return None
