import pygame

from signalk.models import toggle_sail
from theme import (
    BG,
    BTN_ACTIVE_BG,
    BTN_BG,
    BTN_BORDER,
    CALC,
    IDLE_COLOR,
    MOTORING_COLOR,
    OK,
    SAILING_ACTIVE,
    SAILING_INACTIVE,
    SECTION,
    TEXT_DIM,
    TEXT_LABEL,
    TEXT_MUTED,
    TEXT_VALUE,
    TEXT_WHITE,
    WARN,
)


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
    surface.blit(
        bt, (btn.x + btn_w // 2 - bt.get_width() // 2, btn.y + btn_h // 2 - bt.get_height() // 2)
    )
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
        tl = font_sm.render(f"{i + 1}:{sname.capitalize()}", True, tc)
        surface.blit(tl, (brect.x + bw // 2 - tl.get_width() // 2, brect.y + 4))
    py += 34

    heading("--- Sails ---")
    for group_name, group_sails in state.sail_groups:
        group_label = font_sm.render(group_name.capitalize(), True, TEXT_DIM)
        surface.blit(group_label, (x + 22, py))
        py += 18
        for sail in group_sails:
            is_active = sail in state.active_sails
            bg = BTN_ACTIVE_BG if is_active else BTN_BG
            border_c = state.sail_colors.get(sail, BTN_BORDER) if is_active else BTN_BORDER
            brect = pygame.Rect(x + 20, py, 160, 24)
            pygame.draw.rect(surface, bg, brect, border_radius=4)
            pygame.draw.rect(surface, border_c, brect, 1, border_radius=4)
            sc = state.sail_colors.get(sail, TEXT_WHITE) if is_active else TEXT_MUTED
            tl = font_sm.render(sail, True, sc)
            surface.blit(tl, (x + 28, py + 4))
            py += 28
    py += 8

    heading("--- Polar Profile ---")
    short = (
        state.polar_display_names.get(state.polar_active, state.polar_active)
        if state.polar_active
        else "---"
    )
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


def _handle_log_click(state, mx, my, rect):
    x, y0, _w, _h = rect
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

    py += 28 + 4
    for _group_name, group_sails in state.sail_groups:
        py += 18
        for sail in group_sails:
            brect = pygame.Rect(x + 20, py, 160, 24)
            if brect.collidepoint(mx, my):
                toggle_sail(state, sail)
                return "sail_toggle"
            py += 28

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
