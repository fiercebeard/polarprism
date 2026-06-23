from __future__ import annotations

import math

from routes.parser import Route, Waypoint, haversine_distance_m, initial_bearing_rad


class TestWaypoint:
    def test_creation_with_defaults(self) -> None:
        wp = Waypoint(10.5, -20.3)
        assert wp.lat == 10.5
        assert wp.lon == -20.3
        assert wp.name == ""

    def test_creation_with_name(self) -> None:
        wp = Waypoint(0.0, 0.0, "Start")
        assert wp.name == "Start"

    def test_coerces_to_float(self) -> None:
        wp = Waypoint(1, 2, "int")
        assert isinstance(wp.lat, float)
        assert isinstance(wp.lon, float)
        assert wp.lat == 1.0
        assert wp.lon == 2.0


class TestRoute:
    def test_creation(self) -> None:
        wps = [Waypoint(0, 0, "A"), Waypoint(1, 1, "B")]
        r = Route("TestRoute", wps, "/tmp/test.gpx")
        assert r.name == "TestRoute"
        assert r.source_path == "/tmp/test.gpx"
        assert r.waypoints is wps

    def test_len(self) -> None:
        wps = [Waypoint(0, 0), Waypoint(1, 1), Waypoint(2, 2)]
        assert len(Route("R", wps)) == 3

    def test_leg_count(self) -> None:
        wps = [Waypoint(0, 0), Waypoint(1, 1), Waypoint(2, 2)]
        r = Route("R", wps)
        assert r.leg_count() == 2

    def test_leg_count_single_waypoint(self) -> None:
        assert Route("R", [Waypoint(0, 0)]).leg_count() == 0

    def test_leg_count_empty(self) -> None:
        assert Route("R", []).leg_count() == 0

    def test_leg_bearing_rad_valid(self) -> None:
        wps = [Waypoint(0, 0), Waypoint(1, 0)]
        r = Route("R", wps)
        bearing = r.leg_bearing_rad(0)
        assert bearing is not None
        expected = initial_bearing_rad(0, 0, 1, 0)
        assert abs(bearing - expected) < 1e-6

    def test_leg_bearing_rad_invalid_index(self) -> None:
        r = Route("R", [Waypoint(0, 0), Waypoint(1, 1)])
        assert r.leg_bearing_rad(-1) is None
        assert r.leg_bearing_rad(1) is None

    def test_leg_distance_m_valid(self) -> None:
        wps = [Waypoint(0, 0), Waypoint(0, 1)]
        r = Route("R", wps)
        dist = r.leg_distance_m(0)
        expected = haversine_distance_m(0, 0, 0, 1)
        assert abs(dist - expected) < 1.0

    def test_leg_distance_m_invalid_index(self) -> None:
        r = Route("R", [Waypoint(0, 0)])
        assert r.leg_distance_m(0) == 0.0

    def test_total_distance_m(self) -> None:
        wps = [Waypoint(0, 0), Waypoint(0, 1), Waypoint(0, 2)]
        r = Route("R", wps)
        total = r.total_distance_m()
        expected = 2 * haversine_distance_m(0, 0, 0, 1)
        assert abs(total - expected) < 2.0

    def test_total_distance_m_single_waypoint(self) -> None:
        assert Route("R", [Waypoint(0, 0)]).total_distance_m() == 0.0


class TestHaversineDistance:
    def test_same_point(self) -> None:
        assert haversine_distance_m(40.0, -74.0, 40.0, -74.0) == 0.0

    def test_one_degree_longitude_at_equator(self) -> None:
        dist = haversine_distance_m(0, 0, 0, 1)
        assert abs(dist - 111195) < 500

    def test_one_degree_latitude(self) -> None:
        dist = haversine_distance_m(0, 0, 1, 0)
        assert abs(dist - 111195) < 500

    def test_nyc_to_london(self) -> None:
        dist = haversine_distance_m(40.7128, -74.0060, 51.5074, -0.1278)
        assert abs(dist - 5_570_000) < 100_000

    def test_symmetry(self) -> None:
        d1 = haversine_distance_m(10, 20, 30, 40)
        d2 = haversine_distance_m(30, 40, 10, 20)
        assert abs(d1 - d2) < 1e-6


class TestInitialBearing:
    def test_due_north(self) -> None:
        bearing = initial_bearing_rad(0, 0, 10, 0)
        assert abs(bearing - 0.0) < 1e-6

    def test_due_east_at_equator(self) -> None:
        bearing = initial_bearing_rad(0, 0, 0, 10)
        assert abs(bearing - math.pi / 2) < 1e-6

    def test_due_south(self) -> None:
        bearing = initial_bearing_rad(0, 0, -10, 0)
        assert abs(bearing - math.pi) < 1e-6

    def test_due_west_at_equator(self) -> None:
        bearing = initial_bearing_rad(0, 0, 0, -10)
        assert abs(bearing - 3 * math.pi / 2) < 1e-6

    def test_result_in_0_to_2pi(self) -> None:
        bearing = initial_bearing_rad(40, -74, 51, 0)
        assert 0.0 <= bearing < 2 * math.pi

    def test_nyc_to_london_northeast(self) -> None:
        bearing = initial_bearing_rad(40.7128, -74.0060, 51.5074, -0.1278)
        bearing_deg = math.degrees(bearing)
        assert 40 < bearing_deg < 60
