import math
from collections.abc import Callable

import pygame

from signalk.models import State, derive_true_heading
from theme import (
    CHART_BORDER,
    GRID,
    GRID_LABEL,
    GRID_MAJOR,
    ROUTE_ACTIVE_LEG,
    ROUTE_LEG_DONE,
    ROUTE_LINE,
    ROUTE_NEXT_WAYPOINT,
    ROUTE_WAYPOINT,
    SIGNAL_COLORS,
    TEXT_MUTED,
    TEXT_WHITE,
    VESSEL,
    VESSEL_OUTLINE,
    WATER,
    WP_LINE,
    ZOOM_BTN_BG,
    ZOOM_BTN_BORDER,
)

from .tiles import (
    MAX_TILE_ZOOM,
    MIN_TILE_ZOOM,
    TILE_SIZE,
    get_tile,
    is_tile_online,
    latlon_to_tile_xy,
    pending_tile_count,
    queue_tile_fetch,
    tile_xy_to_latlon,
)

ZOOM_BTN_SIZE = 28
ZOOM_BTN_MARGIN = 8


def _draw_grid(
    surface: pygame.Surface,
    state: State,
    rect: tuple[int, int, int, int],
    center_lat: float,
    center_lon: float,
    ll_to_px: Callable[[float, float], tuple[float, float]],
    font_sm: pygame.font.Font,
) -> None:
    x, y, w, h = rect
    z = state.chart_zoom

    center_tile_x, center_tile_y = latlon_to_tile_xy(center_lat, center_lon, z)
    half_w = w // 2
    half_h = h // 2

    lon_left, lat_top = tile_xy_to_latlon(
        center_tile_x - (half_w / TILE_SIZE),
        center_tile_y - (half_h / TILE_SIZE),
        z,
    )
    lon_right, lat_bottom = tile_xy_to_latlon(
        center_tile_x + (half_w / TILE_SIZE),
        center_tile_y + (half_h / TILE_SIZE),
        z,
    )

    span = max(lat_top - lat_bottom, lon_right - lon_left)
    grid_step = 0.001
    if span > 20:
        grid_step = 10.0
    elif span > 10:
        grid_step = 5.0
    elif span > 4:
        grid_step = 2.0
    elif span > 1:
        grid_step = 1.0
    elif span > 0.4:
        grid_step = 0.2
    elif span > 0.1:
        grid_step = 0.05
    elif span > 0.04:
        grid_step = 0.02
    elif span > 0.01:
        grid_step = 0.005

    lat_g = math.floor(lat_bottom / grid_step) * grid_step
    while lat_g <= lat_top + grid_step:
        px, py = ll_to_px(lat_g, center_lon)
        if y <= py <= y + h:
            is_major = (
                abs(lat_g - round(lat_g / (grid_step * 2)) * (grid_step * 2)) < grid_step * 0.01
            )
            c = GRID_MAJOR if is_major else GRID
            pygame.draw.line(surface, c, (x, int(py)), (x + w, int(py)), 1)
            if grid_step < 0.01:
                lbl = f"{lat_g:.4f}\u00b0"
            elif grid_step < 0.1:
                lbl = f"{lat_g:.3f}\u00b0"
            else:
                lbl = f"{lat_g:.1f}\u00b0"
            ts = font_sm.render(lbl, True, GRID_LABEL)
            surface.blit(ts, (x + 4, int(py) + 2))
        lat_g += grid_step

    lon_g = math.floor(lon_left / grid_step) * grid_step
    while lon_g <= lon_right + grid_step:
        px, py = ll_to_px(center_lat, lon_g)
        if x <= px <= x + w:
            is_major = (
                abs(lon_g - round(lon_g / (grid_step * 2)) * (grid_step * 2)) < grid_step * 0.01
            )
            c = GRID_MAJOR if is_major else GRID
            pygame.draw.line(surface, c, (int(px), y), (int(px), y + h), 1)
            if grid_step < 0.01:
                lbl = f"{lon_g:.4f}\u00b0"
            elif grid_step < 0.1:
                lbl = f"{lon_g:.3f}\u00b0"
            else:
                lbl = f"{lon_g:.1f}\u00b0"
            ts = font_sm.render(lbl, True, GRID_LABEL)
            surface.blit(ts, (int(px) + 4, y + h - 18))
        lon_g += grid_step


def _draw_vessel(
    surface: pygame.Surface,
    state: State,
    rect: tuple[int, int, int, int],
    center_lat: float,
    center_lon: float,
    ll_to_px: Callable[[float, float], tuple[float, float]],
) -> None:
    _x, _y, w, h = rect

    vessel_px, vessel_py = ll_to_px(
        state.position.get("lat") or center_lat,
        state.position.get("lon") or center_lon,
    )

    heading_for_rotation = state.values.get("headingMagnetic")
    if heading_for_rotation is None:
        heading_for_rotation = state.values.get("cogTrue") or 0.0

    line_len = max(w, h) * 0.8
    bearing_keys = ["headingMagnetic", "headingTrue", "cogTrue", "apTargetMagnetic"]
    wp_keys = [
        "calcBearingTrue",
        "nextPointBearingTrue",
        "gcNextPointBearingTrue",
        "courseBearingTrue",
        "courseRhumblineBearingTrue",
    ]
    for key in bearing_keys:
        val = derive_true_heading(state) if key == "headingTrue" else state.values.get(key)
        if val is None:
            continue
        color = SIGNAL_COLORS.get(key, TEXT_WHITE)
        a = val
        end_x = vessel_px + math.sin(a) * line_len
        end_y = vessel_py - math.cos(a) * line_len
        start_x = vessel_px + math.sin(a) * 12
        start_y = vessel_py - math.cos(a) * 12
        pygame.draw.line(surface, color, (start_x, start_y), (end_x, end_y), 2)

    wp_val = None
    for wk in wp_keys:
        wp_val = state.values.get(wk)
        if wp_val is not None:
            break
    route_wp_val = state.route_next_wp_bearing_rad
    if route_wp_val is not None:
        wp_val = route_wp_val
    if wp_val is not None:
        a = wp_val
        end_x = vessel_px + math.sin(a) * line_len
        end_y = vessel_py - math.cos(a) * line_len
        start_x = vessel_px + math.sin(a) * 12
        start_y = vessel_py - math.cos(a) * 12
        pygame.draw.line(surface, WP_LINE, (start_x, start_y), (end_x, end_y), 2)

    boat_size = 10
    a = heading_for_rotation
    bow = (vessel_px + math.sin(a) * boat_size * 1.5, vessel_py - math.cos(a) * boat_size * 1.5)
    port = (vessel_px + math.sin(a + 2.5) * boat_size, vessel_py - math.cos(a + 2.5) * boat_size)
    starboard = (
        vessel_px + math.sin(a - 2.5) * boat_size,
        vessel_py - math.cos(a - 2.5) * boat_size,
    )
    stern = (vessel_px - math.sin(a) * boat_size * 0.8, vessel_py + math.cos(a) * boat_size * 0.8)
    pygame.draw.polygon(surface, VESSEL, [bow, port, stern, starboard])
    pygame.draw.polygon(surface, VESSEL_OUTLINE, [bow, port, stern, starboard], 1)


def _draw_scale_bar(
    surface: pygame.Surface,
    state: State,
    rect: tuple[int, int, int, int],
    font_sm: pygame.font.Font,
) -> None:
    x, y, w, h = rect
    center_lat = state.chart_center_lat
    z = state.chart_zoom
    n = 2**z

    world_px = n * TILE_SIZE
    deg_per_px = 360.0 / world_px
    m_per_px = deg_per_px * 60.0 * 1852.0 * math.cos(math.radians(center_lat))
    nm_per_px = m_per_px / 1852.0
    scale_nm = 0.01
    while scale_nm / nm_per_px < 50:
        if scale_nm < 0.1:
            scale_nm *= 2
        elif scale_nm < 1:
            scale_nm *= 2.5
        else:
            scale_nm *= 2
        if scale_nm > 500:
            break
    while scale_nm / nm_per_px > 150:
        scale_nm /= 2
        if scale_nm < 0.01:
            break
    scale_px = scale_nm / nm_per_px
    bar_y = y + h - 25
    bar_x = x + w - 20 - int(scale_px)
    pygame.draw.line(surface, TEXT_WHITE, (bar_x, bar_y), (bar_x + int(scale_px), bar_y), 2)
    pygame.draw.line(surface, TEXT_WHITE, (bar_x, bar_y - 5), (bar_x, bar_y + 5), 2)
    pygame.draw.line(
        surface,
        TEXT_WHITE,
        (bar_x + int(scale_px), bar_y - 5),
        (bar_x + int(scale_px), bar_y + 5),
        2,
    )
    if scale_nm >= 1:
        scale_lbl = f"{scale_nm:.0f} nm"
    elif scale_nm >= 0.1:
        scale_lbl = f"{scale_nm:.1f} nm"
    else:
        scale_lbl = f"{scale_nm:.2f} nm"
    ts2 = font_sm.render(scale_lbl, True, TEXT_WHITE)
    surface.blit(ts2, (bar_x + int(scale_px) // 2 - ts2.get_width() // 2, bar_y + 4))


def _draw_zoom_buttons(
    surface: pygame.Surface,
    rect: tuple[int, int, int, int],
    font: pygame.font.Font,
) -> tuple[int, int, int]:
    x, y, w, _h = rect
    btn_x = x + w - ZOOM_BTN_MARGIN - ZOOM_BTN_SIZE
    btn_y_plus = y + ZOOM_BTN_MARGIN
    btn_y_minus = btn_y_plus + ZOOM_BTN_SIZE + 4

    for by, sym in [(btn_y_plus, "+"), (btn_y_minus, "\u2013")]:
        btn_rect = pygame.Rect(btn_x, by, ZOOM_BTN_SIZE, ZOOM_BTN_SIZE)
        pygame.draw.rect(surface, ZOOM_BTN_BG, btn_rect)
        pygame.draw.rect(surface, ZOOM_BTN_BORDER, btn_rect, 1)
        ts = font.render(sym, True, TEXT_WHITE)
        surface.blit(
            ts,
            (
                btn_x + ZOOM_BTN_SIZE // 2 - ts.get_width() // 2,
                by + ZOOM_BTN_SIZE // 2 - ts.get_height() // 2,
            ),
        )

    return btn_x, btn_y_plus, btn_y_minus


def _draw_tile_status(
    surface: pygame.Surface,
    font_sm: pygame.font.Font,
    rect: tuple[int, int, int, int],
    tiles_drawn: int,
) -> None:
    """Explain a sparse/blank chart: downloading, loading, or offline.

    Stays silent once tiles are on screen and nothing is queued — no point
    nagging when the chart is fully drawn.
    """
    pending = pending_tile_count()
    if pending > 0:
        msg = f"downloading tiles… ({pending})"
    elif tiles_drawn == 0:
        msg = "no cached tiles — enable [tile] online" if not is_tile_online() else "loading tiles…"
    else:
        return

    x, y, w, _h = rect
    ts = font_sm.render(msg, True, TEXT_WHITE)
    pad = 6
    bg = pygame.Surface((ts.get_width() + pad * 2, ts.get_height() + pad), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 150))
    bx = x + w // 2 - bg.get_width() // 2
    surface.blit(bg, (bx, y + 6))
    surface.blit(ts, (bx + pad, y + 6 + pad // 2))


def draw_chart(surface, font, font_sm, state, rect):
    x, y, w, h = rect
    chart_rect = pygame.Rect(x, y, w, h)
    pygame.draw.rect(surface, WATER, chart_rect)

    if not state.chart_centered:
        lat = state.position.get("lat")
        lon = state.position.get("lon")
        if lat is not None and lon is not None:
            state.chart_center_lat = lat
            state.chart_center_lon = lon
            state.chart_centered = True

    center_lat = state.chart_center_lat
    center_lon = state.chart_center_lon
    z = state.chart_zoom
    n = 2**z

    center_tile_x, center_tile_y = latlon_to_tile_xy(center_lat, center_lon, z)
    frac_x = center_tile_x - int(center_tile_x)
    frac_y = center_tile_y - int(center_tile_y)

    half_w = w // 2
    half_h = h // 2

    pixel_offset_x = half_w - frac_x * TILE_SIZE
    pixel_offset_y = half_h - frac_y * TILE_SIZE

    start_tx = int(center_tile_x) - math.ceil(half_w / TILE_SIZE) - 1
    start_ty = int(center_tile_y) - math.ceil(half_h / TILE_SIZE) - 1
    end_tx = int(center_tile_x) + math.ceil(half_w / TILE_SIZE) + 2
    end_ty = int(center_tile_y) + math.ceil(half_h / TILE_SIZE) + 2

    surface.set_clip(chart_rect)

    tiles_drawn = 0
    for tx in range(start_tx, end_tx):
        for ty in range(start_ty, end_ty):
            if tx < 0 or ty < 0 or tx >= n or ty >= n:
                continue
            tile_surf = get_tile(z, tx, ty)
            if tile_surf is None:
                # Not cached on disk — queue it for the background fetcher.
                queue_tile_fetch(z, tx, ty)
                continue
            px = x + pixel_offset_x + (tx - int(center_tile_x)) * TILE_SIZE
            py = y + pixel_offset_y + (ty - int(center_tile_y)) * TILE_SIZE
            surface.blit(tile_surf, (int(px), int(py)))
            tiles_drawn += 1

    surface.set_clip(None)

    def ll_to_px(lat, lon):
        fx, fy = latlon_to_tile_xy(lat, lon, z)
        px = x + half_w + (fx - center_tile_x) * TILE_SIZE
        py = y + half_h + (fy - center_tile_y) * TILE_SIZE
        return px, py

    _draw_grid(surface, state, rect, center_lat, center_lon, ll_to_px, font_sm)

    _draw_vessel(surface, state, rect, center_lat, center_lon, ll_to_px)

    _draw_route_overlay(surface, state, ll_to_px, rect=(x, y, w, h), font_sm=font_sm)

    lat_v = state.position.get("lat")
    lon_v = state.position.get("lon")
    lat_s = f"{lat_v:.5f}" if lat_v is not None else "---.-----"
    lon_s = f"{lon_v:.5f}" if lon_v is not None else "---.-----"
    pos_text = f"{lat_s}N  {lon_s}W"
    ts = font_sm.render(pos_text, True, TEXT_WHITE)
    pos_bg = pygame.Surface((ts.get_width() + 8, ts.get_height() + 4), pygame.SRCALPHA)
    pos_bg.fill((0, 0, 0, 150))
    surface.blit(pos_bg, (x + 4, y + 4))
    surface.blit(ts, (x + 8, y + 6))

    zoom_text = f"z{z}"
    zt = font_sm.render(zoom_text, True, TEXT_MUTED)
    surface.blit(zt, (x + w - zt.get_width() - 8, y + 6))

    _draw_tile_status(surface, font_sm, rect, tiles_drawn)

    _draw_scale_bar(surface, state, rect, font_sm)

    pygame.draw.rect(surface, CHART_BORDER, chart_rect, 1)

    return _draw_zoom_buttons(surface, rect, font)


def handle_chart_click(state, mx, my, rect):
    x, y, w, h = rect
    if mx < x or mx > x + w or my < y or my > y + h:
        return None

    btn_x = x + w - ZOOM_BTN_MARGIN - ZOOM_BTN_SIZE
    btn_y_plus = y + ZOOM_BTN_MARGIN
    btn_y_minus = btn_y_plus + ZOOM_BTN_SIZE + 4

    if btn_x <= mx <= btn_x + ZOOM_BTN_SIZE:
        if btn_y_plus <= my <= btn_y_plus + ZOOM_BTN_SIZE:
            if state.chart_zoom < MAX_TILE_ZOOM:
                state.chart_zoom += 1
            return "zoom_plus"
        if btn_y_minus <= my <= btn_y_minus + ZOOM_BTN_SIZE:
            if state.chart_zoom > MIN_TILE_ZOOM:
                state.chart_zoom -= 1
            return "zoom_minus"

    return "drag"


def _normalize_lon(lon: float) -> float:
    """Wrap longitude into [-180, 180)."""
    return ((lon + 180.0) % 360.0) - 180.0


def handle_chart_scroll(state, mx, my, rect, direction):
    """Zoom one step toward/away, keeping the point under the cursor fixed.

    Zoom-about-cursor (like web maps) rather than about the center, so the
    feature you point at stays put instead of sliding away as you zoom.
    """
    x, y, w, h = rect
    if mx < x or mx > x + w or my < y or my > y + h:
        return

    old_z = state.chart_zoom
    new_z = max(MIN_TILE_ZOOM, min(MAX_TILE_ZOOM, old_z + (1 if direction > 0 else -1)))
    if new_z == old_z:
        return

    # Cursor offset from the chart center, in tiles (matches draw_chart's projection).
    off_x = (mx - (x + w // 2)) / TILE_SIZE
    off_y = (my - (y + h // 2)) / TILE_SIZE

    # Geographic point currently under the cursor.
    cx_tile, cy_tile = latlon_to_tile_xy(state.chart_center_lat, state.chart_center_lon, old_z)
    cur_lat, cur_lon = tile_xy_to_latlon(cx_tile + off_x, cy_tile + off_y, old_z)

    # Re-center at the new zoom so that same point stays under the cursor.
    state.chart_zoom = new_z
    ncx_tile, ncy_tile = latlon_to_tile_xy(cur_lat, cur_lon, new_z)
    lat, lon = tile_xy_to_latlon(ncx_tile - off_x, ncy_tile - off_y, new_z)
    state.chart_center_lat = max(-85.0, min(85.0, lat))
    state.chart_center_lon = _normalize_lon(lon)


def handle_chart_drag(state, dx, dy, rect):
    """Pan the chart by a pixel delta, exact at any latitude.

    Convert the drag straight into Web-Mercator tile space (the projection
    draw_chart uses) so the map tracks the cursor 1:1. Working in lat/lon
    degrees instead needs a cos(latitude) correction that is easy to get
    backwards — longitude is linear in Mercator, latitude is not — which made
    panning drift and feel glitchy.
    """
    z = state.chart_zoom
    cx_tile, cy_tile = latlon_to_tile_xy(state.chart_center_lat, state.chart_center_lon, z)
    cx_tile -= dx / TILE_SIZE
    cy_tile -= dy / TILE_SIZE
    lat, lon = tile_xy_to_latlon(cx_tile, cy_tile, z)
    state.chart_center_lat = max(-85.0, min(85.0, lat))
    state.chart_center_lon = _normalize_lon(lon)


def _draw_route_overlay(surface, state, ll_to_px, rect, font_sm):
    x, y, w, h = rect
    if not state.route_active:
        return
    route = state.routes.get(state.route_active)
    if route is None or len(route.waypoints) < 2:
        return

    leg_idx = state.route_leg_index
    if leg_idx < 0:
        leg_idx = 0
    if leg_idx >= route.leg_count():
        leg_idx = route.leg_count() - 1

    clip = pygame.Rect(x, y, w, h)
    prev_clip = surface.get_clip()
    surface.set_clip(clip)

    pts = []
    for wp in route.waypoints:
        px, py = ll_to_px(wp.lat, wp.lon)
        pts.append((px, py))

    for i in range(len(pts) - 1):
        if i < leg_idx:
            color = ROUTE_LEG_DONE
            lw = 2
        elif i == leg_idx:
            color = ROUTE_ACTIVE_LEG
            lw = 3
        else:
            color = ROUTE_LINE
            lw = 2
        pygame.draw.line(
            surface,
            color,
            (int(pts[i][0]), int(pts[i][1])),
            (int(pts[i + 1][0]), int(pts[i + 1][1])),
            lw,
        )

    for i, (px, py) in enumerate(pts):
        if i < leg_idx:
            ring_color = ROUTE_LEG_DONE
            fill_color = ROUTE_LEG_DONE
            r_out = 6
        elif i == leg_idx:
            ring_color = ROUTE_WAYPOINT
            fill_color = ROUTE_WAYPOINT
            r_out = 7
        elif i == leg_idx + 1:
            ring_color = ROUTE_NEXT_WAYPOINT
            fill_color = ROUTE_NEXT_WAYPOINT
            r_out = 9
        else:
            ring_color = ROUTE_WAYPOINT
            fill_color = ROUTE_WAYPOINT
            r_out = 6
        if i == leg_idx + 1:
            halo = pygame.Surface((r_out * 3, r_out * 3), pygame.SRCALPHA)
            pygame.draw.circle(halo, (*ring_color, 80), (r_out * 3 // 2, r_out * 3 // 2), r_out + 3)
            surface.blit(halo, (int(px) - r_out * 3 // 2, int(py) - r_out * 3 // 2))
        pygame.draw.circle(surface, fill_color, (int(px), int(py)), r_out)
        pygame.draw.circle(surface, (15, 16, 20), (int(px), int(py)), r_out, 1)
        lbl = str(i + 1)
        ts = font_sm.render(lbl, True, (15, 16, 20))
        surface.blit(ts, (int(px) - ts.get_width() // 2, int(py) - ts.get_height() // 2))

    if leg_idx + 1 < len(pts):
        a_px, a_py = pts[leg_idx]
        b_px, b_py = pts[leg_idx + 1]
        pygame.draw.line(
            surface, ROUTE_NEXT_WAYPOINT, (int(a_px), int(a_py)), (int(b_px), int(b_py)), 4
        )

    surface.set_clip(prev_clip)
