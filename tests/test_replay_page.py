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


class TestReplayKeys:
    """Regression: the speed keys used lowercase K_greater/K_less/K_period/
    K_comma (nonexistent in pygame), so any key besides Space/Esc during
    playback raised AttributeError and crashed the app."""

    def _session(self, d: str) -> ReplaySession:
        return ReplaySession(_write_log(d, "sailing_keys.jsonl"))

    def test_all_playback_keys_work(self):
        from main import _handle_replay_key

        with tempfile.TemporaryDirectory() as d:
            s = self._session(d)
            base = s._speed_index
            _handle_replay_key(s, pygame.K_GREATER)
            assert s._speed_index == base + 1
            _handle_replay_key(s, pygame.K_PERIOD)
            assert s._speed_index == base + 2
            _handle_replay_key(s, pygame.K_LESS)
            _handle_replay_key(s, pygame.K_COMMA)
            assert s._speed_index == base
            _handle_replay_key(s, pygame.K_SPACE)
            assert s.is_paused
            _handle_replay_key(s, pygame.K_r)
            assert not s.is_paused

    def test_unbound_keys_are_ignored(self):
        from main import _handle_replay_key

        with tempfile.TemporaryDirectory() as d:
            s = self._session(d)
            for key in (pygame.K_a, pygame.K_F1, pygame.K_TAB, pygame.K_1):
                _handle_replay_key(s, key)  # must not raise


class TestReplayDoesNotRecord:
    """Regression: replay set sailing_log_active and sailing_state='sailing',
    which satisfied the recorder's condition — playing a log re-recorded it
    into a brand-new sailing_*.jsonl file."""

    def test_recording_blocked_during_replay(self):
        from signalk.client import should_write_sailing_log

        st = State()
        st.sailing_log_active = True
        st.sailing_state = "sailing"
        assert should_write_sailing_log(st) is True  # live recording works
        st.replay_active = True
        assert should_write_sailing_log(st) is False  # replay never records

    def test_not_sailing_blocks_recording(self):
        from signalk.client import should_write_sailing_log

        st = State()
        st.sailing_log_active = True
        st.sailing_state = "motoring"
        assert should_write_sailing_log(st) is False


def test_all_pygame_key_constants_exist():
    """Every pygame.K_* referenced anywhere in the source must actually exist —
    a typo'd constant only explodes at runtime, on the exact keypress."""
    import pathlib
    import re

    pat = re.compile(r"pygame\.(K_\w+)")
    root = pathlib.Path(__file__).resolve().parents[1]
    missing = []
    for py in root.rglob("*.py"):
        if any(part in (".git", "polarprism.egg-info") for part in py.parts):
            continue
        for name in set(pat.findall(py.read_text(encoding="utf-8", errors="ignore"))):
            if not hasattr(pygame, name):
                missing.append(f"{py.relative_to(root)}: pygame.{name}")
    assert missing == [], f"nonexistent pygame key constants referenced: {missing}"
