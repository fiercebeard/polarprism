"""Replay file list page."""

from __future__ import annotations

import os
from typing import Any

from replay.controls import draw_replay_hub, handle_replay_hub_click


def draw_replay_page(
    surface: Any,
    font: Any,
    state: Any,
    rect: tuple[int, int, int, int],
    log_dir: str,
) -> None:
    """Draw the replay file list page."""
    log_files = _discover_log_files(log_dir)
    session = getattr(state, "_replay_session", None)
    draw_replay_hub(surface, font, state, rect, log_files, session)


def handle_replay_page_click(
    state: Any,
    mx: int,
    my: int,
    rect: tuple[int, int, int, int],
    log_dir: str,
    on_play: Any,
) -> str | None:
    """Handle click on replay page. Returns event string.
    
    Event strings:
        "play" or "playing" - start replaying the selected file
        "stop" - exit replay mode
        None - no event
    """
    log_files = _discover_log_files(log_dir)
    session = getattr(state, "_replay_session", None)
    event = handle_replay_hub_click(state, mx, my, rect, log_files, session, on_play)
    return event


def _discover_log_files(log_dir: str) -> list[str]:
    """Find all .jsonl sailing log files in log_dir, sorted newest first."""
    if not os.path.isdir(log_dir):
        return []
    files = [f for f in os.listdir(log_dir) if f.startswith("sailing_") and f.endswith(".jsonl")]
    if not files:
        return []
    files.sort(reverse=True)
    return [os.path.join(log_dir, f) for f in files]
