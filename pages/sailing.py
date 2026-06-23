import pygame

from pages.log import _handle_log_click, _handle_log_key, draw_log
from pages.polar import _handle_polar_click, _handle_polar_key, draw_polar_rose
from pages.route import _cycle_route, _handle_route_click, _handle_route_key, draw_route
from pages.wind import draw_wind
from signalk.models import _refresh_route_cache


def render(surface, font, font_sm, state, rect, sub_tab):
    if sub_tab == 0:
        _refresh_route_cache(state)
        draw_polar_rose(surface, font, font_sm, state, rect)
    elif sub_tab == 1:
        _refresh_route_cache(state)
        draw_wind(surface, font, font_sm, state, rect)
    elif sub_tab == 2:
        draw_log(surface, font, font_sm, state, rect)
    elif sub_tab == 3:
        draw_route(surface, font, font_sm, state, rect)


def handle_click(state, mx, my, rect, sub_tab):
    if sub_tab == 0:
        return _handle_polar_click(state, mx, my, rect)
    elif sub_tab == 2:
        return _handle_log_click(state, mx, my, rect)
    elif sub_tab == 3:
        return _handle_route_click(state, mx, my, rect)
    return None


def handle_key(state, key, sub_tab):
    if sub_tab == 0:
        result = _handle_polar_key(state, key)
        if result is not None:
            return result
        if key == pygame.K_r:
            _cycle_route(state, +1)
            return "route_cycle"
    elif sub_tab == 2:
        return _handle_log_key(state, key)
    elif sub_tab == 3:
        return _handle_route_key(state, key)
    return None
