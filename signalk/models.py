from __future__ import annotations

import json
import logging
import math
from collections import deque
from datetime import datetime, timezone
from typing import Any

from config import DEFAULT_CHART_LAT, DEFAULT_CHART_LON, DEFAULT_CHART_ZOOM

UTC = timezone.utc
_logger = logging.getLogger("polarprism")

MS_TO_KNOTS = 1.94384

HDG_ERROR_WARN_DEG = 15.0
HDG_ERROR_WARN_SPEED_KTS = 1.0
CURRENT_LEEWAY_MIN_SOG_KTS = 1.5
CURRENT_LEEWAY_MIN_STW_KTS = 0.5
DRIFT_CALC_MIN_SOG_KTS = 0.1
HEADING_OFFSET_INCREMENT_DEG = 0.5
VARIATION_DELTA_WARN_DEG = 0.5

# Signals eligible for low-pass filtering (GPS motion-artifact suppression).
# Keys match the state.values keys used throughout the app.
FILTERABLE_SIGNALS = ["cogTrue", "speedOverGround"]

PATH_MAP = {
    "headingMagnetic": "navigation.headingMagnetic",
    "headingTrue": "navigation.headingTrue",
    "cogTrue": "navigation.courseOverGroundTrue",
    "apTargetMagnetic": "steering.autopilot.target.headingMagnetic",
    "magneticVariation": "navigation.magneticVariation",
    "rateOfTurn": "navigation.rateOfTurn",
    "speedOverGround": "navigation.speedOverGround",
    "speedThroughWater": "navigation.speedThroughWater",
    "rudderAngle": "steering.rudderAngle",
    "roll": "navigation.attitude.roll",
    "pitch": "navigation.attitude.pitch",
    "yaw": "navigation.attitude.yaw",
    "windAngleApparent": "environment.wind.angleApparent",
    "windSpeedApparent": "environment.wind.speedApparent",
    "courseBearingTrue": "navigation.courseGreatCircle.bearingTrue",
    "nextPointBearingTrue": "navigation.course.nextPoint.bearingTrue",
    "nextPointBearingMagnetic": "navigation.course.nextPoint.bearingMagnetic",
    "nextPointDistance": "navigation.course.nextPoint.distance",
    "previousPointBearingTrue": "navigation.course.previousPoint.bearingTrue",
    "courseRhumblineBearingTrue": "navigation.courseRhumbline.bearingTrue",
    "calcBearingTrue": "navigation.course.calcValues.bearingTrue",
    "calcBearingMagnetic": "navigation.course.calcValues.bearingMagnetic",
    "calcVMG": "navigation.course.calcValues.velocityMadeGood",
    "calcXTE": "navigation.course.calcValues.crossTrackError",
    "calcDistance": "navigation.course.calcValues.distance",
    "gcNextPointBearingTrue": "navigation.courseGreatCircle.nextPoint.bearingTrue",
    "gcNextPointDistance": "navigation.courseGreatCircle.nextPoint.distance",
    "gcNextPointVMG": "navigation.courseGreatCircle.nextPoint.velocityMadeGood",
    "gcXTE": "navigation.courseGreatCircle.crossTrackError",
    "gcBearingTrackTrue": "navigation.courseGreatCircle.bearingTrackTrue",
}


class State:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.sources: dict[str, str] = {}
        self.timestamps: dict[str, str] = {}
        self.position: dict[str, float | None] = {"lat": None, "lon": None}
        self.vessel_name = ""
        self.last_log_time: float = 0.0
        self.connected: bool = False
        self.chart_center_lat: float = DEFAULT_CHART_LAT
        self.chart_center_lon: float = DEFAULT_CHART_LON
        self.chart_zoom: int = DEFAULT_CHART_ZOOM
        self.chart_centered: bool = False
        self.dragging: bool = False
        self.drag_start: tuple[int, int] | None = None
        self.device_names: dict[str, str] = {}
        self.multi_values: dict[str, list[Any]] = {}
        self.heading_offset: float = 0.0
        self.active_nav: str = "heading"
        self.active_tab: int = 1
        self.polar_data: dict[str, Any] = {}
        self.polar_names: list[str] = []
        self.polar_active: str = ""
        self.polar_tws_index: int = 0
        self.polar_display_names: dict[str, str] = {}
        # Phase 7: polar files that failed to load (for Setup checklist feedback)
        self.polar_load_failures: list[str] = []
        # Phase 8: measured-polar overlay toggle on the polar rose
        self.polar_show_measured: bool = False
        self.polar_measured_overlay: str = ""
        self.saildef: dict[str, Any] = {}
        self.sailselect: str | None = None
        self.active_sails: list[str] = []
        self.available_sails: list[str] = []
        self.sail_groups: list[tuple[str, list[str]]] = []
        self.sail_to_polar: dict[str, str] = {}
        self.sail_colors: dict[str, tuple[int, int, int]] = {}
        self.sailing_log_active: bool = False
        self.sailing_state: str = "idle"
        self.performance_log_file: Any | None = None
        self.log_sample_count: int = 0
        self.log_perf_sum: float = 0.0
        self.perf_samples: list[tuple[float, float]] = []
        self.perf_averages: dict[int, float] = {}
        self.PERF_WINDOWS: list[int] = [60, 300, 600, 1800]
        self.nmea_log: deque[str] = deque(maxlen=500)
        # Rolling history for the Trends page: one dict per second, one hour
        # deep (see signalk.client.trend_sampler).
        self.trend_samples: deque[dict[str, Any]] = deque(maxlen=3600)

        # Replay state (mutually exclusive with live)
        self.replay_active: bool = False
        self.replay_log_path: str = ""
        self._replay_speed_index: int = 2
        self._replay_session: Any | None = None

        # Runtime cache for the polar-page recommendation box. Throttles the
        # recomputation of the TACK/HEAD UP/HOLD prose so it stays readable.
        # Not persisted by save_state.
        self._polar_rec_cache: dict[str, Any] = {}
        self._polar_rec_ts: float = 0.0
        self._polar_rec_computed: bool = False

        self.routes: dict[str, Any] = {}
        self.route_names: list[str] = []
        self.route_active: str = ""
        self.route_leg_index: int = 0
        self.route_next_wp_bearing_rad: float | None = None
        self.route_next_wp_distance_m: float | None = None
        self.route_next_wp_name: str = ""
        self.route_total_nm: float = 0.0
        self.route_remaining_nm: float = 0.0
        self.route_eta_s: float | None = None
        # Phase 9: scratch waypoints for in-app route creation
        self.route_scratch_waypoints: list[Any] = []

        # Polar Builder workspace: named session groups that accumulate a
        # measured polar. `polar_builder_groups` is a list of dicts:
        #   {"name": str, "polar": str, "sessions": list[str]}
        # `sessions` holds absolute or config-relative paths to sailing log
        # JSONL files. Persisted across restarts (see config.save_state).
        self.polar_builder_groups: list[dict[str, Any]] = []
        self.polar_builder_active_group: int = 0
        # Live-feed buffer for the current sailing session, in coverage-bin
        # units: (twa_bin_deg, tws_bin_kts, stw_kts). Cleared when a new
        # sailing-log file is opened. Not persisted.
        self.polar_builder_live_buffer: list[tuple[int, int, float]] = []
        self.polar_builder_live_session: str | None = None
        # Coverage cache keyed by group name, with a version tag (hash of the
        # session list) so the page only rebuilds when sessions change. Not
        # persisted.
        self.polar_builder_coverage: dict[str, dict[tuple[int, int], list[float]]] = {}
        self.polar_builder_coverage_version: dict[str, int] = {}
        # Hit-test rects populated by the builder page renderer for click
        # handling. Not persisted.
        self._pb_group_rects: list[tuple[int, int, int, int, int]] = []
        self._pb_session_rects: list[tuple[int, int, int, int, int, bool]] = []
        self._pb_new_rect: tuple[int, int, int, int] | None = None
        self._pb_del_rect: tuple[int, int, int, int] | None = None
        self._pb_name_rect: tuple[int, int, int, int] | None = None
        self._pb_polar_rects: list[tuple[int, int, int, int, int]] = []
        self._pb_build_rect: tuple[int, int, int, int] | None = None
        self._pb_combine_rect: tuple[int, int, int, int] | None = None
        self._pb_build_status: str = ""

        # GPS motion-artifact filtering. ``filter_manager`` is created in
        # main._init_state from the [filter] config; ``filtered`` is a
        # convenience accessor dict updated alongside state.values.
        self.filter_manager: Any | None = None


def rad_to_deg(rad: float | None) -> float | None:
    if rad is None:
        return None
    return math.degrees(rad) % 360


def rad_to_deg_signed(rad: float | None) -> float | None:
    if rad is None:
        return None
    return math.degrees(rad)


def norm_angle(rad: float | None) -> float | None:
    if rad is None:
        return None
    return rad % (2 * math.pi)


def angle_diff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def derive_true_heading(state: State) -> float | None:
    return derive_true_heading_from_values(state.values, state.heading_offset)


def waypoint_bearing_rad(state: State) -> float | None:
    """Bearing to the next waypoint (radians true), route first, Signal K second.

    Prefers the active route's cached leg bearing, then falls back through
    the server-computed course paths in the same priority order the polar
    page uses.
    """
    if state.route_active and state.route_next_wp_bearing_rad is not None:
        return state.route_next_wp_bearing_rad
    for key in (
        "calcBearingTrue",
        "nextPointBearingTrue",
        "gcNextPointBearingTrue",
        "courseBearingTrue",
        "courseRhumblineBearingTrue",
    ):
        v = state.values.get(key)
        if v is not None:
            return float(v)
    return None


def derive_true_heading_from_values(values: dict[str, Any], heading_offset: float) -> float | None:
    """True-heading computation from a values dict + heading offset.

    This is the canonical implementation; ``derive_true_heading`` delegates
    here so callers without a full ``State`` (e.g. the raw-log converter) can
    share the same logic.
    """
    sk_ht = values.get("headingTrue")
    if sk_ht is not None:
        return norm_angle(sk_ht + math.radians(heading_offset))
    hm = values.get("headingMagnetic")
    mv = values.get("magneticVariation")
    if hm is not None and mv is not None:
        return norm_angle(hm + mv + math.radians(heading_offset))
    return None


def update_from_delta(state: State, msg: str) -> None:
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return

    ts = datetime.now(UTC).strftime("%H:%M:%S")
    state.nmea_log.append(f"{ts} {msg.strip()[:200]}")

    # Low-pass filter manager (GPS motion-artifact suppression).
    fm = getattr(state, "filter_manager", None)

    if data.get("vessels"):
        for vessel in data["vessels"].values():
            nav = vessel.get("navigation", {})
            for key, path in PATH_MAP.items():
                parts = path.split(".")
                obj = vessel
                for p in parts[:-1]:
                    obj = obj.get(p, {}) if isinstance(obj, dict) else {}
                    if obj is None:
                        obj = {}
                        break
                if not isinstance(obj, dict):
                    continue
                leaf_key = parts[-1]
                if leaf_key in obj and isinstance(obj[leaf_key], dict):
                    leaf = obj[leaf_key]
                    if "value" in leaf and leaf["value"] is not None:
                        state.values[key] = leaf["value"]
                        src = leaf.get("$source")
                        if src:
                            state.sources[key] = src
                        ts = leaf.get("timestamp")
                        if ts:
                            state.timestamps[key] = ts

            pos = nav.get("position", {})
            if isinstance(pos, dict):
                pos_val = pos.get("value", pos)
                if isinstance(pos_val, dict):
                    lat = pos_val.get("latitude")
                    lon = pos_val.get("longitude")
                    if lat is not None:
                        state.position["lat"] = lat
                    if lon is not None:
                        state.position["lon"] = lon

            name = vessel.get("name")
            if name:
                state.vessel_name = name

    if data.get("updates"):
        for update in data["updates"]:
            values_list = update.get("values", [])
            source_label = update.get("$source", "")
            timestamp = update.get("timestamp", "")
            for item in values_list:
                path = item.get("path", "")
                val = item.get("value")
                if val is None:
                    continue
                for key, sk_path in PATH_MAP.items():
                    if path == sk_path:
                        state.values[key] = val
                        state.sources[key] = source_label
                        state.timestamps[key] = timestamp
                        break
                if path == "navigation.position" and isinstance(val, dict):
                    if val.get("latitude") is not None:
                        state.position["lat"] = val["latitude"]
                    if val.get("longitude") is not None:
                        state.position["lon"] = val["longitude"]
                if path == "name":
                    state.vessel_name = str(val)
                if (
                    path.startswith("navigation.course")
                    and not any(path == sk_path for sk_path in PATH_MAP.values())
                    and path not in _logged_unknown_paths
                ):
                    _logged_unknown_paths.add(path)
                    _log_unknown_path(path, val)

    # Update low-pass filters for COG/SOG if filtering is configured.
    if fm is not None:
        dt = 1.0  # Signal K stream is ~1 Hz; time-aware filter handles it
        for sig in FILTERABLE_SIGNALS:
            v = state.values.get(sig)
            if v is not None and isinstance(v, (int, float)):
                fm.update(sig, float(v), dt)


_logged_unknown_paths: set[str] = set()


def toggle_sail(state: State, sail: str) -> None:
    group_for_sail: str | None = None
    for group_name, group_sails in state.sail_groups:
        if sail in group_sails:
            group_for_sail = group_name
            break

    if sail in state.active_sails:
        state.active_sails.remove(sail)
    else:
        if group_for_sail is not None:
            for group_name, group_sails in state.sail_groups:
                if group_name == group_for_sail:
                    for s in group_sails:
                        if s in state.active_sails:
                            state.active_sails.remove(s)
        state.active_sails.append(sail)


def polar_sail_mismatch(state: State) -> str | None:
    """Return a description of a polar/active-sail mismatch, or None if matched.

    A mismatch occurs when the active polar is the mapped polar for one or
    more sails in ``sail_to_polar``, but none of those sails are currently
    active. This warns the sailor that the polar shown does not correspond
    to the sail they've set.

    Returns a short string like "polar Jib != sail Asym" for display, or
    None when there is no mismatch (or no sails/polars to compare).
    """
    if not state.active_sails or not state.sail_to_polar or not state.polar_active:
        return None
    # Sails that map to the currently active polar
    polar_sails = [s for s, p in state.sail_to_polar.items() if p == state.polar_active]
    if not polar_sails:
        # Active polar isn't mapped to any sail; nothing to warn about.
        return None
    # If any active sail maps to this polar, we're consistent.
    for sail in state.active_sails:
        if sail in polar_sails:
            return None
    # Mismatch: active polar maps to sails that aren't set.
    active_desc = ", ".join(state.active_sails)
    polar_desc = ", ".join(polar_sails)
    return f"polar [{polar_desc}] != sail [{active_desc}]"


def filtered_value(state: State, signal: str) -> float | None:
    """Return the filtered value for a filterable signal, else the raw value.

    Pages and computations call this instead of ``state.values.get(signal)``
    for COG/SOG so they automatically use the low-pass-filtered value when
    filtering is enabled and fall back to raw otherwise.
    """
    raw = state.values.get(signal)
    fm = getattr(state, "filter_manager", None)
    if fm is None:
        return raw
    result: float | None = fm.get(signal, raw)
    return result


def _refresh_route_cache(state: State, vmc_kts: float | None = None) -> None:
    route = state.routes.get(state.route_active)
    if route is None or len(route.waypoints) < 2:
        state.route_next_wp_bearing_rad = None
        state.route_next_wp_distance_m = None
        state.route_next_wp_name = ""
        state.route_total_nm = 0.0
        state.route_remaining_nm = 0.0
        state.route_eta_s = None
        return

    if state.route_leg_index < 0:
        state.route_leg_index = 0
    if state.route_leg_index >= route.leg_count():
        state.route_leg_index = route.leg_count() - 1

    state.route_total_nm = route.total_distance_m() / 1852.0

    next_wp = route.waypoints[state.route_leg_index + 1]
    state.route_next_wp_name = next_wp.name

    lat = state.position.get("lat")
    lon = state.position.get("lon")
    if lat is None or lon is None:
        state.route_next_wp_bearing_rad = route.leg_bearing_rad(state.route_leg_index)
        state.route_next_wp_distance_m = route.leg_distance_m(state.route_leg_index)
    else:
        from routes.parser import haversine_distance_m, initial_bearing_rad

        state.route_next_wp_bearing_rad = initial_bearing_rad(lat, lon, next_wp.lat, next_wp.lon)
        state.route_next_wp_distance_m = haversine_distance_m(lat, lon, next_wp.lat, next_wp.lon)

    remaining_m = state.route_next_wp_distance_m or 0.0
    for i in range(state.route_leg_index + 1, route.leg_count()):
        remaining_m += route.leg_distance_m(i)
    state.route_remaining_nm = remaining_m / 1852.0

    if vmc_kts is not None and vmc_kts > 0.1:
        state.route_eta_s = (remaining_m / 1852.0) / vmc_kts * 3600.0
    else:
        state.route_eta_s = None


def _log_unknown_path(path: str, val: Any) -> None:
    """Log an unrecognized Signal K course path (deduped by the caller)."""
    _logger.warning("unrecognized course path: %s = %s", path, val)
