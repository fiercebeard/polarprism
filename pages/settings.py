import logging

import pygame

from config import SETUP_CHECKLIST, save_config
from pages.ui import TextInput, draw_heading, draw_row
from theme import (
    BG,
    BTN_ACTIVE_BG,
    BTN_ACTIVE_BORDER,
    BTN_BG,
    BTN_BORDER,
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

        draw_row(
            surface, font_sm, x, ry, "Fusion:", "[F] key to toggle", label_x=x + 20, value_x=x + 200
        )
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

    else:
        _draw_setup_tab(surface, font, font_sm, state, rect, config)


def handle_click(state, mx, my, rect, sub_tab, config=None):
    if sub_tab == 0:
        url_input = getattr(state, "_sk_url_input", None)
        url_rect = getattr(state, "_sk_url_rect", None)
        if url_rect and url_rect.collidepoint(mx, my):
            if url_input is not None:
                url_input.activate(config.signalk_url if config else "ws://localhost:3000")
            return None
        if url_input is not None and url_input.active:
            # Click outside the field cancels the edit.
            url_input.deactivate()
        reconnect_rect = getattr(state, "_sk_reconnect_rect", None)
        if reconnect_rect and reconnect_rect.collidepoint(mx, my):
            return "sk_reconnect"
    elif sub_tab == 1:
        minus_rect = getattr(state, "_offset_minus_rect", None)
        if minus_rect and minus_rect.collidepoint(mx, my):
            state.heading_offset -= 0.5
            return None
        plus_rect = getattr(state, "_offset_plus_rect", None)
        if plus_rect and plus_rect.collidepoint(mx, my):
            state.heading_offset += 0.5
            return None
    elif sub_tab == 2:
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
