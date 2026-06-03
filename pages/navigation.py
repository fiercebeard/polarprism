import pygame
from chart.renderer import draw_chart, handle_chart_click, handle_chart_scroll, handle_chart_drag
from signalk.models import State


def render(surface, font, font_sm, state, rect):
    draw_chart(surface, font, font_sm, state, rect)


def handle_click(state, mx, my, rect):
    return handle_chart_click(state, mx, my, rect)


def handle_scroll(state, mx, my, rect, direction):
    handle_chart_scroll(state, mx, my, rect, direction)


def handle_drag(state, dx, dy, rect):
    handle_chart_drag(state, dx, dy, rect)