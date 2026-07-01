from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import nav
from main import _build_icon_font
from signalk.models import State
from theme import NAV_ITEMS

pygame.init()
pygame.display.set_mode((1000, 700))
_FONT = pygame.font.Font(None, 20)
_FONT_SM = pygame.font.Font(None, 14)


def _draw(state, win_w=1000, win_h=700):
    surface = pygame.Surface((win_w, win_h))
    icon_font = _build_icon_font(20)
    nav.draw_nav(surface, _FONT, _FONT_SM, state, win_h, icon_font=icon_font)
    return win_w


class TestNavClick:
    def test_draw_records_one_rect_per_item(self):
        st = State()
        _draw(st)
        assert len(st._nav_item_rects) == len(NAV_ITEMS)

    def test_click_maps_to_correct_item(self):
        st = State()
        win_w = _draw(st)
        for key, rect in st._nav_item_rects:
            cx = rect.x + 10
            cy = rect.y + rect.h // 2
            assert nav.get_nav_click(cx, cy, _FONT, st, win_w) == key

    def test_click_in_content_area_returns_none(self):
        st = State()
        win_w = _draw(st)
        # A click to the right of the nav column is not a nav click.
        assert nav.get_nav_click(win_w - 5, 30, _FONT, st, win_w) is None


class TestIconFont:
    def test_build_icon_font_returns_font(self):
        f = _build_icon_font(20)
        assert isinstance(f, pygame.font.Font)

    def test_nav_glyphs_render_as_distinct_glyphs(self):
        # Guards the original bug: the monospace font drew every icon as the
        # same blank .notdef box. A symbol font renders distinct glyphs, so at
        # least two icons should differ in rendered width. (Skipped if the
        # platform has no symbol font at all.)
        f = _build_icon_font(20)
        widths = {icon: f.size(icon)[0] for _, icon in NAV_ITEMS}
        if all(w == 0 for w in widths.values()):
            import pytest

            pytest.skip("no symbol font available on this platform")
        assert len(set(widths.values())) > 1
