from __future__ import annotations

import os
from typing import Any

import pygame

from replay.engine import ReplaySession
from theme import (
    BTN_BG,
    BTN_BORDER,
    REPLAY_BAR_BG,
    REPLAY_COLOR,
    REPLAY_LABEL,
    REPLAY_PROGRESS,
    TEXT_DIM,
    TEXT_MUTED,
    TEXT_VALUE,
    TEXT_WHITE,
)

BTN_W = 200
BTN_H = 36
FILE_LIST_PAD = 16
FILE_ITEM_H = 28
PROGRESS_H = 6
TITLE = "Replay Session"


def draw_replay_hub(
    surface: Any,
    font: Any,
    state: Any,
    rect: tuple[int, int, int, int],
    log_files: list[str],
    session: ReplaySession | None,
    log_dir: str = "",
) -> None:
    """Draw either the file list or the playing overlay.

    Records the clickable rects (Play buttons, Stop button) on ``state`` so
    :func:`handle_replay_hub_click` hit-tests exactly what was drawn. The
    layout used to be duplicated in the click handler and drifted — the click
    rects sat one row above the painted buttons, so Play played the wrong
    file (or nothing, with a single log).
    """
    x, y0, w, h = rect
    surface.fill((40, 35, 20), (x, y0, w, h))

    state._replay_play_rects = []
    state._replay_stop_rect = None

    py = y0 + 20
    label = font.render(TITLE, True, REPLAY_COLOR)
    surface.blit(label, (x + FILE_LIST_PAD, py))
    py += label.get_height() + 20

    if session is not None:
        _draw_playing_overlay(surface, font, state, session, rect)
        return

    _draw_file_list(surface, font, state, x, y0, w, h, log_files, py, log_dir)


def _draw_playing_overlay(
    surface: Any,
    font: Any,
    state: Any,
    session: ReplaySession,
    rect: tuple[int, int, int, int],
) -> None:
    x, y0, w, _h = rect
    py = y0 + 20

    status = "PAUSED" if session.is_paused else "PLAYING"
    status_color = TEXT_VALUE if session.is_paused else REPLAY_COLOR
    st = font.render(f"{REPLAY_LABEL}  {status}", True, status_color)
    surface.blit(st, (x + FILE_LIST_PAD, py))
    py += 24

    log_name = session.active_log_name
    nm = font.render(f"  {log_name}", True, TEXT_VALUE)
    surface.blit(nm, (x + FILE_LIST_PAD, py))
    py += 24

    time_range = f"{session.wall_start}  --  {session.wall_end}"
    tr = font.render(time_range, True, TEXT_DIM)
    surface.blit(tr, (x + FILE_LIST_PAD, py))
    py += 24

    current = f"Current: {session.wall_current}"
    cr = font.render(current, True, TEXT_VALUE)
    surface.blit(cr, (x + FILE_LIST_PAD, py))
    py += 24

    speed_label_text = f"Speed: {session.speed_label}"
    sp = font.render(speed_label_text, True, TEXT_VALUE)
    surface.blit(sp, (x + FILE_LIST_PAD, py))
    py += 24

    entry_count_text = f"Entries: {session.entry_count}"
    ec = font.render(entry_count_text, True, TEXT_DIM)
    surface.blit(ec, (x + FILE_LIST_PAD, py))
    py += 20

    progress_rect = pygame.Rect(x + 20, py + 8, w - 40, PROGRESS_H)
    pygame.draw.rect(surface, REPLAY_BAR_BG, progress_rect)
    bar_w = max(PROGRESS_H, int(progress_rect.width * session.progress_ratio))
    fill_rect = pygame.Rect(progress_rect.x, progress_rect.y, bar_w, progress_rect.height)
    pygame.draw.rect(surface, REPLAY_PROGRESS, fill_rect)
    py += progress_rect.height + 20

    help_text = "Esc: Stop    Space: Pause    >/<: Speed    R: Reset"
    hl = font.render(help_text, True, TEXT_MUTED)
    surface.blit(hl, (x + FILE_LIST_PAD, py))
    py += hl.get_height() + 16

    # Explicit Stop button. Previously any click anywhere on the page stopped
    # the replay, which read as the app breaking back to the file list.
    stop_rect = pygame.Rect(x + FILE_LIST_PAD, py, BTN_W, BTN_H)
    pygame.draw.rect(surface, BTN_BG, stop_rect, border_radius=4)
    pygame.draw.rect(surface, BTN_BORDER, stop_rect, 1, border_radius=4)
    stop_txt = font.render("Stop Replay", True, TEXT_WHITE)
    surface.blit(
        stop_txt,
        (
            stop_rect.x + stop_rect.w // 2 - stop_txt.get_width() // 2,
            stop_rect.y + stop_rect.h // 2 - stop_txt.get_height() // 2,
        ),
    )
    state._replay_stop_rect = stop_rect


def _draw_file_list(
    surface: Any,
    font: Any,
    state: Any,
    x: int,
    y0: int,
    w: int,
    h: int,
    log_files: list[str],
    py0: int,
    log_dir: str,
) -> None:
    max_py = y0 + h - 60
    py = py0

    if not log_files:
        # Tell the user exactly where logs are expected — a recipient of a
        # shared .jsonl otherwise sees a blank page with no explanation.
        lines = [
            "No sailing logs found.",
            "Put files named sailing_*.jsonl in:",
            f"  {log_dir}" if log_dir else "  (the configured [paths] log_dir)",
            "then reopen this page.",
        ]
        for line in lines:
            txt = font.render(line, True, TEXT_MUTED)
            surface.blit(txt, (x + FILE_LIST_PAD, py))
            py += txt.get_height() + 8
        return

    for fpath in log_files:
        if py > max_py:
            break
        fname = os.path.basename(fpath)
        size = os.path.getsize(fpath)
        size_str = _format_size(size)
        line = f"  {fname}  ({size_str})"
        txt = font.render(line, True, TEXT_VALUE)
        surface.blit(txt, (x + FILE_LIST_PAD, py))

        btn = pygame.Rect(x + w // 2 - BTN_W // 2 + 80, py + 2, BTN_W, BTN_H)
        pygame.draw.rect(surface, BTN_BG, btn, border_radius=4)
        pygame.draw.rect(surface, BTN_BORDER, btn, 1, border_radius=4)
        play_txt = font.render("Play", True, TEXT_WHITE)
        cx = btn.x + btn.w // 2 - play_txt.get_width() // 2
        cy = btn.y + btn.h // 2 - play_txt.get_height() // 2
        surface.blit(play_txt, (cx, cy))

        state._replay_play_rects.append((fpath, btn))
        py += FILE_ITEM_H + 8


def _format_size(b: int) -> str:
    if b < 1024:
        return f"{b}B"
    if b < 1024 * 1024:
        return f"{b / 1024:.0f}K"
    return f"{b / (1024 * 1024):.1f}M"


def handle_replay_hub_click(
    state: Any,
    mx: int,
    my: int,
    rect: tuple[int, int, int, int],
    log_files: list[str],
    session: ReplaySession | None,
    on_play: callable | None = None,
) -> str | None:
    """Handle click on the replay page, using the rects recorded at draw time.

    Returns "stop" (Stop button while playing), "playing" (a Play button),
    or None. Clicks anywhere else are ignored — previously any click during
    playback stopped the replay.
    """
    if session is not None:
        stop_rect = getattr(state, "_replay_stop_rect", None)
        if stop_rect is not None and stop_rect.collidepoint(mx, my):
            return "stop"
        return None

    for fpath, btn in getattr(state, "_replay_play_rects", []):
        if btn.collidepoint(mx, my) and os.path.exists(fpath):
            if on_play:
                on_play(fpath)
            return "playing"
    return None
