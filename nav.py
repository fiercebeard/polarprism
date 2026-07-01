import pygame

from theme import (
    NAV_ACTIVE_BG,
    NAV_ACTIVE_TEXT,
    NAV_BG,
    NAV_GAP,
    NAV_INACTIVE,
    NAV_ITEM_LABELS,
    NAV_ITEMS,
    NAV_WIDTH_RATIO,
    TAB_HEIGHT,
)


def get_layout(window_w, window_h):
    nav_w = max(int(window_w * NAV_WIDTH_RATIO), 160)
    content_x = nav_w
    content_y = 0
    content_w = window_w - nav_w
    content_h = window_h
    return nav_w, content_x, content_y, content_w, content_h


def get_content_rect(window_w, window_h):
    _nav_w, cx, cy, cw, ch = get_layout(window_w, window_h)
    tab_h = TAB_HEIGHT
    return cx, cy + tab_h, cw, ch - tab_h


ICON_X = 24
ICON_SLOT_W = 24  # reserve a fixed column so labels align regardless of glyph width
ICON_LABEL_GAP = 12


def draw_nav(surface, font, font_sm, state, window_h, nav_w=None, icon_font=None):
    if nav_w is None:
        nav_w = max(int(surface.get_width() * NAV_WIDTH_RATIO), 160)
    if icon_font is None:
        icon_font = font
    nav_rect = pygame.Rect(0, 0, nav_w, window_h)
    pygame.draw.rect(surface, NAV_BG, nav_rect)

    y = 24
    item_rects = []
    label_x = ICON_X + ICON_SLOT_W + ICON_LABEL_GAP
    for key, icon in NAV_ITEMS:
        label = NAV_ITEM_LABELS[key]
        is_active = state.active_nav == key
        color = NAV_ACTIVE_TEXT if is_active else NAV_INACTIVE

        icon_surf = icon_font.render(icon, True, color)
        label_surf = font.render(label, True, color)
        row_h = max(icon_surf.get_height(), label_surf.get_height())

        if is_active:
            pill_w = (label_x + label_surf.get_width()) - 8 + 16
            pill_rect = pygame.Rect(8, y - 4, pill_w, row_h + 8)
            pygame.draw.rect(surface, NAV_ACTIVE_BG, pill_rect, border_radius=9999)

        # Center the icon in its slot and vertically align both to the row.
        icon_x = ICON_X + (ICON_SLOT_W - icon_surf.get_width()) // 2
        surface.blit(icon_surf, (icon_x, y + (row_h - icon_surf.get_height()) // 2))
        surface.blit(label_surf, (label_x, y + (row_h - label_surf.get_height()) // 2))

        item_rects.append((key, pygame.Rect(0, y - 4, nav_w, row_h + 8)))
        y += row_h + NAV_GAP + 8

    state._nav_item_rects = item_rects
    return y


def get_nav_click(mx, my, font, state, window_w):
    nav_w = max(int(window_w * NAV_WIDTH_RATIO), 160)
    if mx >= nav_w:
        return None
    for key, rect in getattr(state, "_nav_item_rects", []):
        if rect.collidepoint(mx, my):
            return key
    return None
