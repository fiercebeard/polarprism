import math
import pygame
from .tiles import TILE_SIZE, MIN_TILE_ZOOM, MAX_TILE_ZOOM, latlon_to_tile_xy, tile_xy_to_latlon, get_tile
from signalk.models import derive_true_heading, norm_angle
from theme import (
    WATER, GRID, GRID_MAJOR, GRID_LABEL, VESSEL, VESSEL_OUTLINE,
    TEXT_WHITE, TEXT_MUTED, CHART_BORDER, ZOOM_BTN_BG, ZOOM_BTN_BORDER,
    SIGNAL_COLORS, CONNECTED, DISCONNECTED,
)

ZOOM_BTN_SIZE = 28
ZOOM_BTN_MARGIN = 8


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
    n = 2 ** z

    center_tile_x, center_tile_y = latlon_to_tile_xy(center_lat, center_lon, z)
    frac_x = center_tile_x - int(center_tile_x)
    frac_y = center_tile_y - int(center_tile_y)

    half_w = w // 2
    half_h = h // 2

    pixel_offset_x = half_w - frac_x * TILE_SIZE
    pixel_offset_y = half_h - frac_y * TILE_SIZE

    start_tx = int(center_tile_x) - int(math.ceil(half_w / TILE_SIZE)) - 1
    start_ty = int(center_tile_y) - int(math.ceil(half_h / TILE_SIZE)) - 1
    end_tx = int(center_tile_x) + int(math.ceil(half_w / TILE_SIZE)) + 2
    end_ty = int(center_tile_y) + int(math.ceil(half_h / TILE_SIZE)) + 2

    surface.set_clip(chart_rect)

    for tx in range(start_tx, end_tx):
        for ty in range(start_ty, end_ty):
            if tx < 0 or ty < 0 or tx >= n or ty >= n:
                continue
            tile_surf = get_tile(z, tx, ty)
            if tile_surf is None:
                continue
            px = x + pixel_offset_x + (tx - int(center_tile_x)) * TILE_SIZE
            py = y + pixel_offset_y + (ty - int(center_tile_y)) * TILE_SIZE
            surface.blit(tile_surf, (int(px), int(py)))

    surface.set_clip(None)

    def ll_to_px(lat, lon):
        fx, fy = latlon_to_tile_xy(lat, lon, z)
        px = x + half_w + (fx - center_tile_x) * TILE_SIZE
        py = y + half_h + (fy - center_tile_y) * TILE_SIZE
        return px, py

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
            is_major = abs(lat_g - round(lat_g / (grid_step * 2)) * (grid_step * 2)) < grid_step * 0.01
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
            is_major = abs(lon_g - round(lon_g / (grid_step * 2)) * (grid_step * 2)) < grid_step * 0.01
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

    vessel_px, vessel_py = ll_to_px(
        state.position.get("lat") or center_lat,
        state.position.get("lon") or center_lon,
    )

    heading_for_rotation = state.values.get("headingMagnetic")
    if heading_for_rotation is None:
        heading_for_rotation = state.values.get("cogTrue") or 0.0

    line_len = max(w, h) * 0.8
    bearing_keys = ["headingMagnetic", "headingTrue", "cogTrue", "apTargetMagnetic"]
    if state.emulation_active:
        bearing_keys.append("fusionTrue")
    for key in bearing_keys:
        if key == "headingTrue":
            val = derive_true_heading(state)
        elif key == "fusionTrue":
            val = state.fusion_heading
        else:
            val = state.values.get(key)
        if val is None:
            continue
        color = SIGNAL_COLORS[key]
        a = val
        end_x = vessel_px + math.sin(a) * line_len
        end_y = vessel_py - math.cos(a) * line_len
        start_x = vessel_px + math.sin(a) * 12
        start_y = vessel_py - math.cos(a) * 12
        pygame.draw.line(surface, color, (start_x, start_y), (end_x, end_y), 2)

    boat_size = 10
    a = heading_for_rotation
    bow = (vessel_px + math.sin(a) * boat_size * 1.5, vessel_py - math.cos(a) * boat_size * 1.5)
    port = (vessel_px + math.sin(a + 2.5) * boat_size, vessel_py - math.cos(a + 2.5) * boat_size)
    starboard = (vessel_px + math.sin(a - 2.5) * boat_size, vessel_py - math.cos(a - 2.5) * boat_size)
    stern = (vessel_px - math.sin(a) * boat_size * 0.8, vessel_py + math.cos(a) * boat_size * 0.8)
    pygame.draw.polygon(surface, VESSEL, [bow, port, stern, starboard])
    pygame.draw.polygon(surface, VESSEL_OUTLINE, [bow, port, stern, starboard], 1)

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
    pygame.draw.line(surface, TEXT_WHITE, (bar_x + int(scale_px), bar_y - 5), (bar_x + int(scale_px), bar_y + 5), 2)
    if scale_nm >= 1:
        scale_lbl = f"{scale_nm:.0f} nm"
    elif scale_nm >= 0.1:
        scale_lbl = f"{scale_nm:.1f} nm"
    else:
        scale_lbl = f"{scale_nm:.2f} nm"
    ts2 = font_sm.render(scale_lbl, True, TEXT_WHITE)
    surface.blit(ts2, (bar_x + int(scale_px) // 2 - ts2.get_width() // 2, bar_y + 4))

    pygame.draw.rect(surface, CHART_BORDER, chart_rect, 1)

    btn_x = x + w - ZOOM_BTN_MARGIN - ZOOM_BTN_SIZE
    btn_y_plus = y + ZOOM_BTN_MARGIN
    btn_y_minus = btn_y_plus + ZOOM_BTN_SIZE + 4

    for by, sym in [(btn_y_plus, "+"), (btn_y_minus, "\u2013")]:
        btn_rect = pygame.Rect(btn_x, by, ZOOM_BTN_SIZE, ZOOM_BTN_SIZE)
        pygame.draw.rect(surface, ZOOM_BTN_BG, btn_rect)
        pygame.draw.rect(surface, ZOOM_BTN_BORDER, btn_rect, 1)
        ts = font.render(sym, True, TEXT_WHITE)
        surface.blit(ts, (btn_x + ZOOM_BTN_SIZE // 2 - ts.get_width() // 2,
                          by + ZOOM_BTN_SIZE // 2 - ts.get_height() // 2))

    return btn_x, btn_y_plus, btn_y_minus


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


def handle_chart_scroll(state, mx, my, rect, direction):
    x, y, w, h = rect
    if mx < x or mx > x + w:
        return

    if direction > 0:
        chart_mx = mx - x - w // 2
        chart_my = my - y - h // 2
        n = 2 ** state.chart_zoom
        deg_per_px = 360.0 / (n * TILE_SIZE)
        cos_lat = math.cos(math.radians(state.chart_center_lat))
        state.chart_center_lon -= chart_mx * deg_per_px / cos_lat
        state.chart_center_lat += chart_my * deg_per_px
        if state.chart_zoom < MAX_TILE_ZOOM:
            state.chart_zoom += 1
    else:
        if state.chart_zoom > MIN_TILE_ZOOM:
            state.chart_zoom -= 1


def handle_chart_drag(state, dx, dy, rect):
    n = 2 ** state.chart_zoom
    deg_per_px = 360.0 / (n * TILE_SIZE)
    cos_lat = math.cos(math.radians(state.chart_center_lat))
    state.chart_center_lon -= dx * deg_per_px / cos_lat
    state.chart_center_lat += dy * deg_per_px
    state.chart_center_lat = max(-85, min(85, state.chart_center_lat))