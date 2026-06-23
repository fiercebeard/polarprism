import math

import pygame

from polars.parser import compute_true_wind
from signalk.models import MS_TO_KNOTS, derive_true_heading, rad_to_deg
from theme import (
    BG,
    POLAR_FILL,
    POLAR_GRID,
    POLAR_RING,
    TEXT_DIM,
    TEXT_LABEL,
    TEXT_VALUE,
    TEXT_WHITE,
    WIND_APPARENT,
    WIND_DIR_ARROW,
    WIND_TRUE,
)


def draw_wind(surface, font, font_sm, state, rect):
    x, y0, w, h = rect
    surface.fill(BG, (x, y0, w, h))

    awa_rad = state.values.get("windAngleApparent")
    aws_ms = state.values.get("windSpeedApparent")
    stw_ms = state.values.get("speedThroughWater")
    hm_rad = state.values.get("headingMagnetic")
    mv_rad = state.values.get("magneticVariation")

    twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)

    cx = x + w // 2
    cy = y0 + h // 2 - 40
    r = min(w, h) // 2 - 60

    pygame.draw.circle(surface, POLAR_FILL, (cx, cy), r)
    for ring_r in range(r // 4, r + 1, r // 4):
        pygame.draw.circle(surface, POLAR_RING, (cx, cy), ring_r, 1)

    for a_deg in range(0, 360, 30):
        a_rad = math.radians(a_deg) - math.pi / 2
        ex = cx + math.cos(a_rad) * r
        ey = cy + math.sin(a_rad) * r
        pygame.draw.line(surface, POLAR_GRID, (cx, cy), (int(ex), int(ey)), 1)

    lbl_map = {0: "B", 90: "S", 180: "B", 270: "S"}
    for a_deg in [0, 90, 180, 270]:
        a_rad = math.radians(a_deg) - math.pi / 2
        lx = cx + math.cos(a_rad) * (r + 16)
        ly = cy + math.sin(a_rad) * (r + 16)
        lbl = font_sm.render(lbl_map[a_deg], True, TEXT_DIM)
        surface.blit(lbl, (int(lx - lbl.get_width() // 2), int(ly - lbl.get_height() // 2)))

    heading_rad = None
    if hm_rad is not None:
        mv = mv_rad or 0
        heading_rad = hm_rad + mv
    elif state.values.get("cogTrue") is not None:
        heading_rad = state.values["cogTrue"]

    if heading_rad is not None and twa_rad is not None:
        twd_rad = heading_rad + twa_rad
        a = twd_rad - math.pi / 2
        ex = cx + math.cos(a) * (r - 4)
        ey = cy + math.sin(a) * (r - 4)
        pygame.draw.line(surface, WIND_DIR_ARROW, (cx, cy), (int(ex), int(ey)), 3)
        hx = ex + math.cos(a + 2.6) * 12
        hy = ey + math.sin(a + 2.6) * 12
        hx2 = ex + math.cos(a - 2.6) * 12
        hy2 = ey + math.sin(a - 2.6) * 12
        pygame.draw.polygon(
            surface, WIND_DIR_ARROW, [(int(ex), int(ey)), (int(hx), int(hy)), (int(hx2), int(hy2))]
        )

    if awa_rad is not None:
        a = awa_rad - math.pi / 2
        a_len = r * 0.6
        ex = cx + math.cos(a) * a_len
        ey = cy + math.sin(a) * a_len
        pygame.draw.line(surface, WIND_APPARENT, (cx, cy), (int(ex), int(ey)), 2)

    if twa_rad is not None:
        a = twa_rad - math.pi / 2
        a_len = r * 0.8
        ex = cx + math.cos(a) * a_len
        ey = cy + math.sin(a) * a_len
        pygame.draw.line(surface, WIND_TRUE, (cx, cy), (int(ex), int(ey)), 2)

    pygame.draw.circle(surface, TEXT_WHITE, (cx, cy), 4)

    ny = cy + r + 30
    row_h = 20

    def row(label, val, color=TEXT_VALUE):
        nonlocal ny
        tl = font_sm.render(label, True, TEXT_LABEL)
        tv = font_sm.render(val, True, color)
        surface.blit(tl, (x + 20, ny))
        surface.blit(tv, (x + 140, ny))
        ny += row_h

    ht_val = derive_true_heading(state)
    ht_deg = rad_to_deg(ht_val) if ht_val is not None else None
    twd_deg = None
    if ht_deg is not None and twa_rad is not None:
        twd_deg = (ht_deg + math.degrees(twa_rad)) % 360

    awa_deg = math.degrees(awa_rad) if awa_rad is not None else None
    aws_kts = aws_ms * MS_TO_KNOTS if aws_ms is not None else None
    twa_deg = math.degrees(twa_rad) if twa_rad is not None else None
    tws_kts = tws_ms * MS_TO_KNOTS if tws_ms is not None else None

    row("TWD:", f"{twd_deg:.1f}\u00b0" if twd_deg is not None else "---\u00b0", WIND_DIR_ARROW)
    row("TWS:", f"{tws_kts:.1f} kts" if tws_kts is not None else "--- kts", WIND_TRUE)
    row("TWA:", f"{twa_deg:.1f}\u00b0" if twa_deg is not None else "---\u00b0", WIND_TRUE)
    row("AWA:", f"{awa_deg:.1f}\u00b0" if awa_deg is not None else "---\u00b0", WIND_APPARENT)
    row("AWS:", f"{aws_kts:.1f} kts" if aws_kts is not None else "--- kts", WIND_APPARENT)
    row("Heading:", f"{ht_deg:.1f}\u00b0" if ht_deg is not None else "---\u00b0")
