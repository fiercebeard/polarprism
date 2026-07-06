from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from pages import replay as replay_page
from replay.engine import ReplaySession
from signalk.models import State

pygame.init()
pygame.display.set_mode((1400, 900))
_FONT = pygame.font.SysFont("monospace", 20, bold=True)

RECT = (380, 40, 1000, 860)  # typical content rect


def _write_log(directory: str, name: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(json.dumps({"ts": "2026-06-01T10:00:00+00:00", "stw": 5.0}) + "\n")
        f.write(json.dumps({"ts": "2026-06-01T10:00:01+00:00", "stw": 5.1}) + "\n")
    return path


def _draw(state: State, log_dir: str) -> None:
    surface = pygame.Surface((1400, 900))
    replay_page.draw_replay_page(surface, _FONT, state, RECT, log_dir)


class TestPlayButtons:
    def test_click_plays_exactly_the_drawn_file(self):
        # Regression: the click handler re-derived the layout without the
        # title offset, so every Play button played the file one row below
        # (or nothing, for the last row).
        with tempfile.TemporaryDirectory() as d:
            for n in ("sailing_1.jsonl", "sailing_2.jsonl", "sailing_3.jsonl"):
                _write_log(d, n)
            st = State()
            _draw(st, d)
            assert len(st._replay_play_rects) == 3
            for fpath, btn in st._replay_play_rects:
                played: list[str] = []
                ev = replay_page.handle_replay_page_click(
                    st, btn.centerx, btn.centery, RECT, d, played.append
                )
                assert ev == "playing"
                assert played == [fpath]

    def test_single_file_play_works(self):
        # The most common sharing case: exactly one log. Previously dead.
        with tempfile.TemporaryDirectory() as d:
            _write_log(d, "sailing_only.jsonl")
            st = State()
            _draw(st, d)
            (fpath, btn) = st._replay_play_rects[0]
            played: list[str] = []
            ev = replay_page.handle_replay_page_click(
                st, btn.centerx, btn.centery, RECT, d, played.append
            )
            assert ev == "playing"
            assert played == [fpath]

    def test_click_off_buttons_does_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            _write_log(d, "sailing_only.jsonl")
            st = State()
            _draw(st, d)
            ev = replay_page.handle_replay_page_click(st, RECT[0] + 5, RECT[1] + 5, RECT, d, None)
            assert ev is None

    def test_empty_dir_draws_without_rects(self):
        with tempfile.TemporaryDirectory() as d:
            st = State()
            _draw(st, d)  # renders the "no logs found" explanation
            assert st._replay_play_rects == []


class TestPlayingOverlay:
    def _session_state(self, d: str) -> tuple[State, str]:
        fpath = _write_log(d, "sailing_only.jsonl")
        st = State()
        st._replay_session = ReplaySession(fpath)
        return st, fpath

    def test_stop_button_stops(self):
        with tempfile.TemporaryDirectory() as d:
            st, _ = self._session_state(d)
            _draw(st, d)
            assert st._replay_stop_rect is not None
            btn = st._replay_stop_rect
            ev = replay_page.handle_replay_page_click(st, btn.centerx, btn.centery, RECT, d, None)
            assert ev == "stop"

    def test_stray_click_does_not_stop(self):
        # Regression: any click anywhere on the page used to stop the replay.
        with tempfile.TemporaryDirectory() as d:
            st, _ = self._session_state(d)
            _draw(st, d)
            ev = replay_page.handle_replay_page_click(
                st, RECT[0] + RECT[2] - 10, RECT[1] + RECT[3] - 10, RECT, d, None
            )
            assert ev is None
