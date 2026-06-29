"""Shared helpers for drawing a polar-style rose diagram.

Used by ``pages/polar.py`` (the theoretical polar rose) and
``pages/polar_builder.py`` (the coverage heatmap rose). Both pages share the
same angle convention: 0 deg TWA at top (bow), positive clockwise, port and
starboard mirrored left/right.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pygame

from theme import POLAR_FILL, POLAR_GRID, POLAR_RING, TEXT_DIM, TEXT_WHITE

# TWA label map for the 30-degree radial spokes. Port and starboard mirror:
# 0 -> "B" (bow), 180 -> "180"; labels > 180 show the mirrored angle value.
_RADIAL_LABELS: dict[int, str] = {
    0: "B",
    30: "30",
    60: "60",
    90: "90",
    120: "120",
    150: "150",
    180: "180",
    210: "150",
    240: "120",
    270: "90",
    300: "60",
    330: "30",
}


def angle_to_screen(cx: int, cy: int, radius: float, twa_deg: float) -> tuple[float, float]:
    """Map a TWA (deg) + radius to a screen point. 0 deg at top, clockwise."""
    a_rad = math.radians(twa_deg) - math.pi / 2
    return cx + math.cos(a_rad) * radius, cy + math.sin(a_rad) * radius


def draw_rose_fill(surface: pygame.Surface, cx: int, cy: int, r: int) -> None:
    """Fill the rose circle."""
    pygame.draw.circle(surface, POLAR_FILL, (cx, cy), r)


def draw_speed_rings(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    cx: int,
    cy: int,
    r: int,
    max_speed: float,
    speed_step: int = 2,
) -> None:
    """Draw concentric speed rings labeled in knots."""
    for s in range(speed_step, int(max_speed) + 1, speed_step):
        ring_r = int(r * s / max_speed)
        if ring_r > 0:
            pygame.draw.circle(surface, POLAR_RING, (cx, cy), ring_r, 1)
            lbl = font_sm.render(f"{s}", True, TEXT_DIM)
            surface.blit(lbl, (cx + 2, cy - ring_r - lbl.get_height()))


def draw_radials(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    cx: int,
    cy: int,
    r: int,
    label_map: dict[int, str] | None = None,
) -> None:
    """Draw 30-degree radial spokes with TWA labels."""
    labels = label_map if label_map is not None else _RADIAL_LABELS
    for a_deg in range(0, 360, 30):
        a_rad = math.radians(a_deg) - math.pi / 2
        ex = cx + math.cos(a_rad) * r
        ey = cy + math.sin(a_rad) * r
        pygame.draw.line(surface, POLAR_GRID, (cx, cy), (int(ex), int(ey)), 1)
        lbl_text = labels.get(a_deg, "")
        if lbl_text:
            lx = cx + math.cos(a_rad) * (r + 14)
            ly = cy + math.sin(a_rad) * (r + 14)
            lbl = font_sm.render(lbl_text, True, TEXT_DIM)
            surface.blit(lbl, (int(lx - lbl.get_width() // 2), int(ly - lbl.get_height() // 2)))


def draw_center_dot(surface: pygame.Surface, cx: int, cy: int, radius: int = 3) -> None:
    """Draw the white center dot."""
    pygame.draw.circle(surface, TEXT_WHITE, (cx, cy), radius)


def polar_curve_points(
    cx: int,
    cy: int,
    r: int,
    max_speed: float,
    twa_list: list[float],
    speed_lookup: Callable[[float], float],
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Build port + starboard point lists for one polar curve.

    ``speed_lookup(twa_deg) -> speed_kts`` returns the boat speed at a given
    TWA. Points with speed <= 0 are skipped. Port uses +twa, starboard -twa
    (mirrored across the vertical axis).
    """
    pts_port: list[tuple[float, float]] = []
    pts_stbd: list[tuple[float, float]] = []
    for twa_deg in twa_list:
        spd = speed_lookup(twa_deg)
        if spd <= 0:
            continue
        pr = r * spd / max_speed
        px, py = angle_to_screen(cx, cy, pr, twa_deg)
        pts_port.append((px, py))
        sx, sy = angle_to_screen(cx, cy, pr, -twa_deg)
        pts_stbd.append((sx, sy))
    return pts_port, pts_stbd


def draw_filled_curve(
    surface: pygame.Surface,
    pts_port: list[tuple[float, float]],
    pts_stbd: list[tuple[float, float]],
    color: tuple[int, int, int],
    alpha: int,
    origin: tuple[int, int],
    size: tuple[int, int],
) -> None:
    """Draw a filled polygon (port + reversed starboard) at low alpha."""
    if len(pts_port) <= 2:
        return
    fill_pts = pts_port + list(reversed(pts_stbd))
    fill_surf = pygame.Surface(size, pygame.SRCALPHA)
    shifted = [(p[0] - origin[0], p[1] - origin[1]) for p in fill_pts]
    try:
        pygame.draw.polygon(fill_surf, (*color, alpha), shifted)
        surface.blit(fill_surf, origin)
    except (TypeError, ValueError):
        pass


def draw_curve_lines(
    surface: pygame.Surface,
    pts: list[tuple[float, float]],
    color: tuple[int, int, int],
    width: int,
) -> None:
    """Draw a polyline through ``pts`` with the given color/width."""
    if len(pts) > 1:
        pygame.draw.lines(surface, color, False, [(int(p[0]), int(p[1])) for p in pts], width)


def compute_max_speed(base: float, floor: float = 10.0, step: float = 2.0) -> float:
    """Round ``base`` up to the next ``step`` multiple, with a minimum floor."""
    val = math.ceil(base / step) * step if base > 0 else floor
    return max(val, floor)
