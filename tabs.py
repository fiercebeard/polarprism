import pygame

from theme import (
    BG,
    CONNECTED,
    DISCONNECTED,
    NAV_TABS,
    TAB_ACCENT,
    TAB_ACCENT_THICKNESS,
    TAB_ACTIVE,
    TAB_HEIGHT,
    TAB_INACTIVE,
)


def draw_tabs(surface, font, font_sm, state, content_x, content_w):
    tab_rect = pygame.Rect(content_x, 0, content_w, TAB_HEIGHT)
    pygame.draw.rect(surface, BG, tab_rect)

    tabs = NAV_TABS.get(state.active_nav, [])
    if not tabs:
        return

    x = content_x + 20
    for i, tab_name in enumerate(tabs):
        is_active = state.active_tab == i
        if is_active:
            ts = font.render(tab_name, True, TAB_ACTIVE)
            text_w = ts.get_width()
            surface.blit(ts, (x, (TAB_HEIGHT - ts.get_height()) // 2))
            accent_y = TAB_HEIGHT - TAB_ACCENT_THICKNESS
            pygame.draw.rect(surface, TAB_ACCENT, (x, accent_y, text_w, TAB_ACCENT_THICKNESS))
        else:
            ts = font.render(tab_name, True, TAB_INACTIVE)
            surface.blit(ts, (x, (TAB_HEIGHT - ts.get_height()) // 2))
        x += ts.get_width() + 32

    conn_color = CONNECTED if state.connected else DISCONNECTED
    conn_text = "WS:OK" if state.connected else "WS:--"
    ct = font_sm.render(conn_text, True, conn_color)
    surface.blit(
        ct, (content_x + content_w - ct.get_width() - 12, (TAB_HEIGHT - ct.get_height()) // 2)
    )


def get_tab_click(mx, my, font, state, content_x, content_w):
    if my >= TAB_HEIGHT:
        return None

    tabs = NAV_TABS.get(state.active_nav, [])
    if not tabs:
        return None

    x = content_x + 20
    for i, tab_name in enumerate(tabs):
        is_active = state.active_tab == i
        color = TAB_ACTIVE if is_active else TAB_INACTIVE
        ts = font.render(tab_name, True, color)
        if x <= mx <= x + ts.get_width():
            return i
        x += ts.get_width() + 32

    return None
