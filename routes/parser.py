from __future__ import annotations

import glob as globmod
import logging
import math
import os
import xml.etree.ElementTree as ET

GPX_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}
_logger = logging.getLogger("polarprism")


class Waypoint:
    __slots__ = ("lat", "lon", "name")

    def __init__(self, lat: float, lon: float, name: str = "") -> None:
        self.lat = float(lat)
        self.lon = float(lon)
        self.name = name or ""


class Route:
    __slots__ = ("name", "source_path", "waypoints")

    def __init__(self, name: str, waypoints: list[Waypoint], source_path: str = "") -> None:
        self.name = name
        self.waypoints = waypoints
        self.source_path = source_path

    def __len__(self) -> int:
        return len(self.waypoints)

    def leg_count(self) -> int:
        return max(len(self.waypoints) - 1, 0)

    def leg_bearing_rad(self, leg_idx: int) -> float | None:
        a, b = self._leg_endpoints(leg_idx)
        if a is None or b is None:
            return None
        return initial_bearing_rad(a.lat, a.lon, b.lat, b.lon)

    def leg_distance_m(self, leg_idx: int) -> float:
        a, b = self._leg_endpoints(leg_idx)
        if a is None or b is None:
            return 0.0
        return haversine_distance_m(a.lat, a.lon, b.lat, b.lon)

    def total_distance_m(self) -> float:
        if len(self.waypoints) < 2:
            return 0.0
        total = 0.0
        for i in range(len(self.waypoints) - 1):
            total += self.leg_distance_m(i)
        return total

    def _leg_endpoints(self, leg_idx: int) -> tuple[Waypoint | None, Waypoint | None]:
        if leg_idx < 0 or leg_idx >= self.leg_count():
            return None, None
        return self.waypoints[leg_idx], self.waypoints[leg_idx + 1]


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def initial_bearing_rad(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return math.atan2(y, x) % (2 * math.pi)


def point_to_segment_bearing_and_distance(
    lat: float,
    lon: float,
    p1_lat: float,
    p1_lon: float,
    p2_lat: float,
    p2_lon: float,
) -> tuple[float, float, float]:
    if p1_lat == p2_lat and p1_lon == p2_lon:
        bearing = initial_bearing_rad(lat, lon, p1_lat, p1_lon)
        distance = haversine_distance_m(lat, lon, p1_lat, p1_lon)
        return bearing, distance, 0.0

    seg_dist = haversine_distance_m(p1_lat, p1_lon, p2_lat, p2_lon)
    if seg_dist <= 0.0:
        return (
            initial_bearing_rad(lat, lon, p1_lat, p1_lon),
            haversine_distance_m(lat, lon, p1_lat, p1_lon),
            0.0,
        )

    d13 = haversine_distance_m(p1_lat, p1_lon, lat, lon) / seg_dist
    b13 = initial_bearing_rad(p1_lat, p1_lon, lat, lon)
    theta13 = math.radians(b13)
    theta12 = math.radians(initial_bearing_rad(p1_lat, p1_lon, p2_lat, p2_lon))
    dxt = d13 * math.sin(theta13 - theta12)
    along = max(
        0.0, min(seg_dist, d13 * math.cos(theta13 - theta12) * seg_dist / max(seg_dist, 1e-9))
    )

    proj_lat = p1_lat + (p2_lat - p1_lat) * (along / seg_dist)
    proj_lon = p1_lon + (p2_lon - p1_lon) * (along / seg_dist)
    perp = haversine_distance_m(lat, lon, proj_lat, proj_lon)
    bearing = initial_bearing_rad(lat, lon, p2_lat, p2_lon)
    return bearing, perp, dxt


def load_gpx(filepath: str) -> Route | None:
    name = os.path.splitext(os.path.basename(filepath))[0]
    try:
        tree = ET.parse(filepath)
    except ET.ParseError as e:
        _logger.warning("routes: failed to parse %s: %s", filepath, e)
        return None

    root = tree.getroot()
    ns_tag = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""
    ns_prefix = f"{{{ns_tag}}}" if ns_tag else ""

    rte = root.find(f"{ns_prefix}route")
    if rte is None:
        rte = root.find("gpx:route", GPX_NS)
    if rte is None:
        return None

    route_name_el = rte.find(f"{ns_prefix}name")
    if route_name_el is None:
        route_name_el = rte.find("gpx:name", GPX_NS)
    if route_name_el is not None and route_name_el.text:
        route_name = route_name_el.text.strip()
    else:
        route_name = name

    waypoints = []
    for rtept in rte.findall(f"{ns_prefix}rtept"):
        lat_s = rtept.get("lat")
        lon_s = rtept.get("lon")
        if lat_s is None or lon_s is None:
            continue
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except ValueError:
            continue
        name_el = rtept.find(f"{ns_prefix}name")
        if name_el is None:
            name_el = rtept.find("gpx:name", GPX_NS)
        wp_name = name_el.text.strip() if name_el is not None and name_el.text else ""
        waypoints.append(Waypoint(lat, lon, wp_name))

    if len(waypoints) < 2:
        _logger.warning("routes: %s has fewer than 2 valid waypoints", filepath)
        return None

    return Route(name=route_name, waypoints=waypoints, source_path=filepath)


def discover_routes(directory: str) -> list[Route]:
    routes: list[Route] = []
    if not os.path.isdir(directory):
        return routes
    for gpx_path in sorted(globmod.glob(os.path.join(directory, "*.gpx"))):
        r = load_gpx(gpx_path)
        if r is not None:
            routes.append(r)
    return routes
