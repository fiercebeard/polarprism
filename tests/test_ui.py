from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pages.ui import TextInput

pygame.init()
pygame.display.set_mode((400, 200))
_FONT = pygame.font.Font(None, 20)


def _make(text=""):
    inp = TextInput(pygame.Rect(0, 0, 400, 28), _FONT, text)
    inp.activate(text)
    return inp


def _key(key, unicode="", mod=0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode=unicode, mod=mod)


class TestCaretEditing:
    def test_activate_puts_caret_at_end(self):
        inp = _make("abc")
        assert inp.cursor_pos == 3

    def test_type_inserts_at_caret(self):
        inp = _make("ac")
        inp.cursor_pos = 1  # between a and c
        inp.handle_key(_key(pygame.K_b, "b"))
        assert inp.text == "abc"
        assert inp.cursor_pos == 2

    def test_insert_at_front_after_home(self):
        inp = _make("bc")
        inp.handle_key(_key(pygame.K_HOME))
        assert inp.cursor_pos == 0
        inp.handle_key(_key(pygame.K_a, "a"))
        assert inp.text == "abc"

    def test_backspace_deletes_before_caret(self):
        inp = _make("abc")
        inp.cursor_pos = 2
        inp.handle_key(_key(pygame.K_BACKSPACE))
        assert inp.text == "ac"
        assert inp.cursor_pos == 1

    def test_delete_removes_at_caret(self):
        inp = _make("abc")
        inp.cursor_pos = 1
        inp.handle_key(_key(pygame.K_DELETE))
        assert inp.text == "ac"
        assert inp.cursor_pos == 1

    def test_arrows_and_bounds(self):
        inp = _make("ab")
        inp.handle_key(_key(pygame.K_LEFT))
        assert inp.cursor_pos == 1
        inp.handle_key(_key(pygame.K_LEFT))
        inp.handle_key(_key(pygame.K_LEFT))  # clamp at 0
        assert inp.cursor_pos == 0
        inp.handle_key(_key(pygame.K_END))
        assert inp.cursor_pos == 2
        inp.handle_key(_key(pygame.K_RIGHT))  # clamp at len
        assert inp.cursor_pos == 2

    def test_backspace_at_start_is_noop(self):
        inp = _make("abc")
        inp.cursor_pos = 0
        inp.handle_key(_key(pygame.K_BACKSPACE))
        assert inp.text == "abc"

    def test_commit_and_cancel(self):
        inp = _make("abc")
        assert inp.handle_key(_key(pygame.K_RETURN)) == "commit"
        assert inp.active is False
        inp2 = _make("abc")
        assert inp2.handle_key(_key(pygame.K_ESCAPE)) == "cancel"
        assert inp2.active is False


class TestClickToCaret:
    def test_click_before_text_goes_to_start(self):
        inp = _make("ws://localhost:3000")
        inp.place_cursor_from_x(inp.rect.x - 50)
        assert inp.cursor_pos == 0

    def test_click_past_text_goes_to_end(self):
        inp = _make("ws://localhost")
        inp.place_cursor_from_x(inp.rect.x + 10_000)
        assert inp.cursor_pos == len(inp.text)

    def test_click_middle_lands_between_chars(self):
        text = "abcdefgh"
        inp = _make(text)
        # Click at the x of the boundary after the 4th char.
        target_px = inp.font.size(text[:4])[0]
        inp.place_cursor_from_x(inp.rect.x + inp.PAD_X + target_px)
        assert inp.cursor_pos == 4
