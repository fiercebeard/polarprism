"""Trends page: rolling strip charts of live sailing metrics.

Four stacked panels mirroring the offline analysis report: speeds/VMC,
wind & waypoint angles (with point-of-sail bands), performance percentages,
and directional metrics. Data comes from ``state.trend_samples``, fed at
1 Hz by ``signalk.client.trend_sampler`` — live or during replay.

Drawn natively with pygame (like every other page) rather than a charting
library: the only candidate, pygame-chart, is a single-release static-figure
package that would fight the dark theme and the 30 fps redraw.
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

import pygame

from theme import (
    BG,
    OK,
    POLAR_FILL,
    POLAR_GRID,
    SECTION,
    SIGNAL_COLORS,
    TEXT_DIM,
    TEXT_MUTED,
    TEXT_VALUE,
    TEXT_WHITE,
    WARN,
    WIND_APPARENT,
    WIND_DIR_ARROW,
    WIND_TRUE,
    WP_LINE,
)

# Rolling display windows, matching the NAV_TABS labels for "trends".
TREND_WINDOWS_S = [300, 900, 1800, 3600]

LEGEND_W = 130
PANEL_GAP = 10
AXIS_W = 44
TIME_AXIS_H = 18

Series = tuple[str, tuple[int, int, int], str]  # (label, color, sample key)

# Panel definitions. "span" fixes the y-range; "auto" scales to the data.
_SPEED_SERIES: list[Series] = [
    ("TWS", (150, 150, 150), "tws"),
    ("STW", TEXT_WHITE, "stw"),
    ("SOG", (120, 180, 255), "sog"),
    ("VMC", (80, 130, 255), "vmc"),
    ("Tgt VMC", WARN, "tgt_vmc"),
]
_ANGLE_SERIES: list[Series] = [
    ("TWA", WIND_TRUE, "twa"),
    ("AWA", WIND_APPARENT, "awa"),
    ("WP angle", TEXT_WHITE, "wp_angle"),
    ("Tgt TWA S", OK, "tgt_twa"),
    ("Tgt TWA P", WARN, "_tgt_twa_neg"),
]
_PERF_SERIES: list[Series] = [
    ("Polar %", (190, 120, 255), "perf"),
    ("%VMC", (255, 170, 40), "vmc_pct"),
]
_DIR_SERIES: list[Series] = [
    ("TWD", WIND_DIR_ARROW, "twd"),
    ("HDG", SIGNAL_COLORS["headingTrue"], "hdg"),
    ("COG", SIGNAL_COLORS["cogTrue"], "cog"),
    ("BTW", WP_LINE, "btw"),
]

# Point-of-sail bands for the angle panel: (|angle| lo, hi, color). Drawn
# translucent, mirrored across zero.
_POS_BANDS = [
    (40, 65, (60, 130, 220)),  # close reach
    (65, 105, (60, 200, 100)),  # beam reach
    (105, 150, (230, 200, 60)),  # broad reach
    (150, 180, (230, 80, 60)),  # run
]


def _sample_value(sample: dict[str, Any], key: str) -> float | None:
    """Series accessor; virtual keys are computed from real ones."""
    if key == "_tgt_twa_neg":
        v = sample.get("tgt_twa")
        return -v if v is not None else None
    return sample.get(key)


def y_to_px(value: float, vmin: float, vmax: float, top: int, height: int) -> int:
    """Map a data value to a pixel row inside a panel (vmax at top)."""
    if vmax <= vmin:
        return top + height // 2
    frac = (value - vmin) / (vmax - vmin)
    frac = max(0.0, min(1.0, frac))
    return int(top + (1.0 - frac) * height)


def _auto_range(
    samples: list[dict[str, Any]], series: list[Series], min_span: float
) -> tuple[float, float]:
    lo, hi = math.inf, -math.inf
    for s in samples:
        for _label, _color, key in series:
            v = _sample_value(s, key)
            if v is not None:
                lo = min(lo, v)
                hi = max(hi, v)
    if lo > hi:
        return 0.0, min_span
    if hi - lo < min_span:
        pad = (min_span - (hi - lo)) / 2
        lo -= pad
        hi += pad
    lo = min(lo, 0.0) if lo > -0.5 else lo  # anchor speed panels near zero
    return lo, hi


def _draw_panel(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    rect: tuple[int, int, int, int],
    title: str,
    series: list[Series],
    samples: list[dict[str, Any]],
    t0: float,
    t1: float,
    y_range: tuple[float, float] | None,
    min_span: float = 10.0,
    pos_bands: bool = False,
) -> None:
    x, y, w, h = rect
    plot_x = x + AXIS_W
    plot_w = w - AXIS_W - LEGEND_W
    title_h = 16
    plot_y = y + title_h
    plot_h = h - title_h

    ts = font_sm.render(title, True, SECTION)
    surface.blit(ts, (plot_x, y))

    pygame.draw.rect(surface, POLAR_FILL, (plot_x, plot_y, plot_w, plot_h))

    vmin, vmax = y_range if y_range is not None else _auto_range(samples, series, min_span)

    if pos_bands:
        band_surf = pygame.Surface((plot_w, plot_h), pygame.SRCALPHA)
        for lo, hi, color in _POS_BANDS:
            for sign in (1, -1):
                py_top = y_to_px(sign * hi if sign > 0 else sign * lo, vmin, vmax, 0, plot_h)
                py_bot = y_to_px(sign * lo if sign > 0 else sign * hi, vmin, vmax, 0, plot_h)
                band_surf.fill((*color, 26), (0, py_top, plot_w, max(1, py_bot - py_top)))
        surface.blit(band_surf, (plot_x, plot_y))

    # Horizontal grid + y labels (5 lines).
    for i in range(5):
        gy = plot_y + int(plot_h * i / 4)
        pygame.draw.line(surface, POLAR_GRID, (plot_x, gy), (plot_x + plot_w, gy), 1)
        val = vmax - (vmax - vmin) * i / 4
        lbl = font_sm.render(f"{val:.0f}", True, TEXT_DIM)
        surface.blit(lbl, (plot_x - lbl.get_width() - 4, gy - lbl.get_height() // 2))

    # Vertical time grid (4 intervals).
    for i in range(1, 4):
        gx = plot_x + int(plot_w * i / 4)
        pygame.draw.line(surface, POLAR_GRID, (gx, plot_y), (gx, plot_y + plot_h), 1)

    # Series polylines; None values break the line into segments.
    span = t1 - t0
    for label_i, (_label, color, key) in enumerate(series):
        del label_i
        segment: list[tuple[int, int]] = []
        for s in samples:
            v = _sample_value(s, key)
            if v is None:
                if len(segment) >= 2:
                    pygame.draw.lines(surface, color, False, segment, 2)
                segment = []
                continue
            px = plot_x + int((s["t"] - t0) / span * plot_w) if span > 0 else plot_x
            py = plot_y + (y_to_px(v, vmin, vmax, 0, plot_h))
            segment.append((px, py))
        if len(segment) >= 2:
            pygame.draw.lines(surface, color, False, segment, 2)
        elif len(segment) == 1:
            pygame.draw.circle(surface, color, segment[0], 2)

    # Legend column with the latest value per series.
    ly = plot_y
    latest = samples[-1] if samples else {}
    for label, color, key in series:
        v = _sample_value(latest, key)
        val_txt = f"{v:.1f}" if v is not None else "---"
        lbl = font_sm.render(f"{label}: {val_txt}", True, color)
        surface.blit(lbl, (plot_x + plot_w + 8, ly))
        ly += lbl.get_height() + 2

    pygame.draw.rect(surface, POLAR_GRID, (plot_x, plot_y, plot_w, plot_h), 1)


def _draw_time_axis(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    x: int,
    y: int,
    w: int,
    t0: float,
    t1: float,
) -> None:
    plot_x = x + AXIS_W
    plot_w = w - AXIS_W - LEGEND_W
    for i in range(5):
        t = t0 + (t1 - t0) * i / 4
        label = datetime.fromtimestamp(t).strftime("%H:%M:%S")
        lbl = font_sm.render(label, True, TEXT_MUTED)
        lx = plot_x + int(plot_w * i / 4) - lbl.get_width() // 2
        surface.blit(lbl, (max(x, lx), y))


def draw_trend_page(surface, font, font_sm, state, rect, sub_tab: int) -> None:
    x, y, w, h = rect
    surface.fill(BG, (x, y, w, h))

    window_s = TREND_WINDOWS_S[max(0, min(sub_tab, len(TREND_WINDOWS_S) - 1))]
    t1 = time.time()
    t0 = t1 - window_s
    samples = [s for s in state.trend_samples if s["t"] >= t0]

    if len(samples) < 2:
        msg = "Collecting data… trends appear after a few seconds of live or replayed input."
        ts = font_sm.render(msg, True, TEXT_VALUE)
        surface.blit(ts, (x + w // 2 - ts.get_width() // 2, y + h // 2))
        return

    # Downsample so each panel draws at most ~2 points per pixel column.
    plot_w = max(1, w - AXIS_W - LEGEND_W)
    step = max(1, len(samples) // (plot_w * 2))
    if step > 1:
        samples = samples[::step]

    panel_h = (h - TIME_AXIS_H - 3 * PANEL_GAP - 8) // 4
    py = y + 4
    panels = [
        ("Speed & VMC (kts)", _SPEED_SERIES, None, 10.0, False),
        ("Wind & Waypoint Angles (°)", _ANGLE_SERIES, (-180.0, 180.0), 0.0, True),
        ("Performance (%)", _PERF_SERIES, (0.0, 150.0), 0.0, False),
        ("Direction (°T)", _DIR_SERIES, (0.0, 360.0), 0.0, False),
    ]
    for title, series, y_range, min_span, bands in panels:
        _draw_panel(
            surface,
            font_sm,
            (x, py, w, panel_h),
            title,
            series,
            samples,
            t0,
            t1,
            y_range,
            min_span,
            pos_bands=bands,
        )
        py += panel_h + PANEL_GAP

    _draw_time_axis(surface, font_sm, x, py - PANEL_GAP + 2, w, t0, t1)
