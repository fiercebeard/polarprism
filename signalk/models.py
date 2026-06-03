import math

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
}

SK_WS_URL = "ws://localhost:3000/signalk/v1/stream"


class State:
    def __init__(self):
        self.values = {}
        self.sources = {}
        self.timestamps = {}
        self.position = {"lat": None, "lon": None}
        self.vessel_name = ""
        self.last_log_time = 0.0
        self.connected = False
        self.chart_center_lat = 41.49
        self.chart_center_lon = -81.73
        self.chart_zoom = 9
        self.chart_centered = False
        self.dragging = False
        self.drag_start = None
        self.device_names = {}
        self.emulation_active = False
        self.fusion_heading = None
        self.fusion_ws = None
        self.multi_values = {}
        self.heading_offset = 0.0
        self.active_nav = "heading"
        self.active_tab = 1
        self.polar_data = {}
        self.polar_names = []
        self.polar_active = ""
        self.polar_tws_index = 0
        self.saildef = {}
        self.sailselect = None
        self.active_sails = []
        self.available_sails = ["Jib", "Code0", "Asym"]
        self.sailing_log_active = False
        self.sailing_state = "idle"
        self.performance_log_file = None
        self.log_sample_count = 0
        self.log_perf_sum = 0.0


def rad_to_deg(rad):
    if rad is None:
        return None
    return math.degrees(rad) % 360


def rad_to_deg_signed(rad):
    if rad is None:
        return None
    return math.degrees(rad)


def norm_angle(rad):
    if rad is None:
        return None
    return rad % (2 * math.pi)


def angle_diff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def derive_true_heading(state):
    sk_ht = state.values.get("headingTrue")
    if sk_ht is not None:
        return norm_angle(sk_ht + math.radians(state.heading_offset))
    hm = state.values.get("headingMagnetic")
    mv = state.values.get("magneticVariation")
    if hm is not None and mv is not None:
        return norm_angle(hm + mv + math.radians(state.heading_offset))
    return None


def compute_fusion_heading(state):
    heading_mag = state.values.get("headingMagnetic")
    cog_true = state.values.get("cogTrue")
    mag_var = state.values.get("magneticVariation")
    rot = state.values.get("rateOfTurn")
    speed_sog = state.values.get("speedOverGround")
    speed_stw = state.values.get("speedThroughWater")

    if heading_mag is None:
        return None

    heading_true_raw = heading_mag + (mag_var or 0)

    if cog_true is None:
        return norm_angle(heading_true_raw)

    sog = speed_sog if speed_sog is not None else 0
    stw = speed_stw if speed_stw is not None else 0
    speed = max(sog, stw, 0.5)

    hdg_cog_diff = abs(angle_diff(heading_true_raw, cog_true))
    drift_threshold = math.radians(15)
    if hdg_cog_diff > drift_threshold and speed < 1.0:
        cog_weight = 0.0
    elif hdg_cog_diff > drift_threshold:
        cog_weight = 0.15
    else:
        cog_weight = 0.3

    if rot is not None and abs(rot) > math.radians(10):
        cog_weight *= 0.5

    return norm_angle(heading_true_raw + angle_diff(cog_true, heading_true_raw) * cog_weight)


def update_from_delta(state, msg):
    import json
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return

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
                if path == "navigation.position":
                    if isinstance(val, dict):
                        if val.get("latitude") is not None:
                            state.position["lat"] = val["latitude"]
                        if val.get("longitude") is not None:
                            state.position["lon"] = val["longitude"]
                if path == "name":
                    state.vessel_name = str(val)