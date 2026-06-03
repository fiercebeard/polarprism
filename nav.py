import pygame
from theme import (
    NAV_ITEMS, NAV_ITEM_LABELS, NAV_TABS,
    NAV_WIDTH_RATIO, TAB_HEIGHT, FILTER_ROW_HEIGHT, CONTENT_PAD, NAV_GAP,
    NAV_INACTIVE, NAV_ACTIVE_BG, NAV_ACTIVE_TEXT,
    NAV_BG, BG, TAB_INACTIVE, TAB_ACTIVE, TAB_ACCENT, TAB_ACCENT_THICKNESS,
    TEXT_WHITE, TEXT_MUTED,
)
from signalk.models import State


def get_layout(window_w, window_h):
    nav_w = max(int(window_w * NAV_WIDTH_RATIO), 160)
    content_x = nav_w
    content_y = 0
    content_w = window_w - nav_w
    content_h = window_h
    return nav_w, content_x, content_y, content_w, content_h


def get_content_rect(window_w, window_h):
    nav_w, cx, cy, cw, ch = get_layout(window_w, window_h)
    tab_h = TAB_HEIGHT
    return cx, cy + tab_h, cw, ch - tab_h


def draw_nav(surface, font, font_sm, state, window_h, nav_w=None):
    if nav_w is None:
        nav_w = max(int(surface.get_width() * NAV_WIDTH_RATIO), 160)
    nav_rect = pygame.Rect(0, 0, nav_w, window_h)
    pygame.draw.rect(surface, NAV_BG, nav_rect)

    y = 24
    for key, icon in NAV_ITEMS:
        label = NAV_ITEM_LABELS[key]
        is_active = state.active_nav == key
        text = f"{icon}  {label}"
        if is_active:
            ts = font.render(text, True, NAV_ACTIVE_TEXT)
            tw = ts.get_width() + 32
            pill_rect = pygame.Rect(8, y - 4, tw, ts.get_height() + 8)
            pygame.draw.rect(surface, NAV_ACTIVE_BG, pill_rect, border_radius=9999)
            surface.blit(ts, (24, y))
        else:
            ts = font.render(text, True, NAV_INACTIVE)
            surface.blit(ts, (24, y))
        y += ts.get_height() + NAV_GAP + 8

    return y


def get_nav_click(mx, my, font, state, window_w):
    nav_w = max(int(window_w * NAV_WIDTH_RATIO), 160)
    if mx >= nav_w:
        return None

    y = 24
    for key, icon in NAV_ITEMS:
        label = NAV_ITEM_LABELS[key]
        text = f"{icon}  {label}"
        is_active = state.active_nav == key
        if is_active:
            ts = font.render(text, True, NAV_ACTIVE_TEXT)
        else:
            ts = font.render(text, True, NAV_INACTIVE)
        item_h = ts.get_height() + 8
        if y - 4 <= my <= y + item_h + 4:
            return key
        y += ts.get_height() + NAV_GAP + 8

    return None