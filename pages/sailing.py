import pygame
from theme import BG, TEXT_MUTED, TEXT_WHITE


def render(surface, font, font_sm, state, rect, sub_tab):
    x, y, w, h = rect
    surface.fill(BG, (x, y, w, h))
    if sub_tab == 0:
        ts = font.render("Polar Performance", True, TEXT_MUTED)
        surface.blit(ts, (x + w // 2 - ts.get_width() // 2, y + h // 2 - 20))
        ts2 = font_sm.render("Coming soon - ORC polar data from Polars2024/", True, TEXT_MUTED)
        surface.blit(ts2, (x + w // 2 - ts2.get_width() // 2, y + h // 2 + 10))
    else:
        ts = font.render("Wind Data", True, TEXT_MUTED)
        surface.blit(ts, (x + w // 2 - ts.get_width() // 2, y + h // 2 - 20))
        ts2 = font_sm.render("Coming soon - apparent/true wind rose", True, TEXT_MUTED)
        surface.blit(ts2, (x + w // 2 - ts2.get_width() // 2, y + h // 2 + 10))