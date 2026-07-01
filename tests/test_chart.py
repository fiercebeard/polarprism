from __future__ import annotations

from chart.renderer import handle_chart_drag, handle_chart_scroll
from chart.tiles import (
    MAX_TILE_ZOOM,
    MIN_TILE_ZOOM,
    TILE_SIZE,
    latlon_to_tile_xy,
    tile_xy_to_latlon,
)
from signalk.models import State

RECT = (200, 40, 800, 600)  # x, y, w, h — a typical chart content area


def _make_state(lat=41.5, lon=-81.7, zoom=10) -> State:
    st = State()
    st.chart_center_lat = lat
    st.chart_center_lon = lon
    st.chart_zoom = zoom
    return st


def _pixel_of(st: State, rect, lat, lon):
    """Screen pixel of a geographic point, matching draw_chart's projection."""
    x, y, w, h = rect
    z = st.chart_zoom
    cxt, cyt = latlon_to_tile_xy(st.chart_center_lat, st.chart_center_lon, z)
    fx, fy = latlon_to_tile_xy(lat, lon, z)
    return x + w // 2 + (fx - cxt) * TILE_SIZE, y + h // 2 + (fy - cyt) * TILE_SIZE


class TestPan:
    def test_drag_moves_center_by_exact_pixels(self):
        st = _make_state()
        z = st.chart_zoom
        ox, oy = latlon_to_tile_xy(st.chart_center_lat, st.chart_center_lon, z)
        handle_chart_drag(st, 128, 64, RECT)
        nx, ny = latlon_to_tile_xy(st.chart_center_lat, st.chart_center_lon, z)
        # Dragging content right/down shifts the center tile left/up by exactly
        # the pixel delta (in tiles). This is what makes the map track the cursor.
        assert abs((ox - 128 / TILE_SIZE) - nx) < 1e-9
        assert abs((oy - 64 / TILE_SIZE) - ny) < 1e-9

    def test_horizontal_pan_is_latitude_independent(self):
        # The old degree-based math scaled longitude by 1/cos(lat), so panning
        # sped up toward the poles. In tile space it must not.
        deltas = []
        for lat in (0.0, 41.5, 70.0):
            st = _make_state(lat=lat)
            z = st.chart_zoom
            ox, _ = latlon_to_tile_xy(st.chart_center_lat, st.chart_center_lon, z)
            handle_chart_drag(st, 100, 0, RECT)
            nx, _ = latlon_to_tile_xy(st.chart_center_lat, st.chart_center_lon, z)
            deltas.append(ox - nx)
        assert all(abs(d - 100 / TILE_SIZE) < 1e-9 for d in deltas)

    def test_latitude_is_clamped(self):
        st = _make_state(lat=84.9, zoom=7)
        handle_chart_drag(st, 0, -5000, RECT)  # drag far "up"
        assert st.chart_center_lat <= 85.0


class TestZoom:
    def test_scroll_keeps_point_under_cursor(self):
        st = _make_state()
        mx, my = 700, 150
        x, y, w, h = RECT
        z0 = st.chart_zoom
        # Geographic point under the cursor before zooming.
        off_x = (mx - (x + w // 2)) / TILE_SIZE
        off_y = (my - (y + h // 2)) / TILE_SIZE
        cxt, cyt = latlon_to_tile_xy(st.chart_center_lat, st.chart_center_lon, z0)
        cur_lat, cur_lon = tile_xy_to_latlon(cxt + off_x, cyt + off_y, z0)

        handle_chart_scroll(st, mx, my, RECT, direction=1)
        assert st.chart_zoom == z0 + 1

        # That same point should still be under the cursor after zooming.
        px, py = _pixel_of(st, RECT, cur_lat, cur_lon)
        assert abs(px - mx) < 1.0
        assert abs(py - my) < 1.0

    def test_scroll_clamps_at_bounds(self):
        st = _make_state(zoom=MAX_TILE_ZOOM)
        handle_chart_scroll(st, 700, 150, RECT, direction=1)
        assert st.chart_zoom == MAX_TILE_ZOOM

        st = _make_state(zoom=MIN_TILE_ZOOM)
        handle_chart_scroll(st, 700, 150, RECT, direction=-1)
        assert st.chart_zoom == MIN_TILE_ZOOM

    def test_scroll_outside_chart_is_ignored(self):
        st = _make_state()
        before = st.chart_zoom
        handle_chart_scroll(st, RECT[0] - 5, 150, RECT, direction=1)  # left of chart
        assert st.chart_zoom == before
