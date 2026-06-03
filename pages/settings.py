import math
import pygame
from theme import BG, TEXT_MUTED, TEXT_WHITE, TEXT_LABEL, TEXT_VALUE, SECTION, CONNECTED, DISCONNECTED


def render(surface, font, font_sm, state, rect, sub_tab):
    x, y, w, h = rect
    surface.fill(BG, (x, y, w, h))

    row_h = 24
    ry = y + 20

    def row(label, value_str, color=TEXT_VALUE):
        nonlocal ry
        ts_l = font_sm.render(label, True, TEXT_LABEL)
        surface.blit(ts_l, (x + 20, ry))
        ts_v = font_sm.render(value_str, True, color)
        surface.blit(ts_v, (x + 200, ry))
        ry += row_h

    if sub_tab == 0:
        ry += 4
        ts = font_sm.render("--- SignalK Connection ---", True, SECTION)
        surface.blit(ts, (x + 20, ry))
        ry += row_h

        conn_color = CONNECTED if state.connected else DISCONNECTED
        row("WebSocket:", "CONNECTED" if state.connected else "DISCONNECTED", conn_color)
        row("URL:", "ws://localhost:3000")
        row("Vessel:", state.vessel_name or "---")

        ry += 12
        ts = font_sm.render("--- N2K Devices ---", True, SECTION)
        surface.blit(ts, (x + 20, ry))
        ry += row_h

        for src, name in sorted(state.device_names.items()):
            row(f"{src}:", name, TEXT_MUTED)

    else:
        ry += 4
        ts = font_sm.render("--- Display ---", True, SECTION)
        surface.blit(ts, (x + 20, ry))
        ry += row_h

        row("Heading Offset:", f"{state.heading_offset:+.1f}\u00b0")
        row("Adjust:", "[\u200b / ] keys")
        row("Fusion:", "[F] key to toggle")