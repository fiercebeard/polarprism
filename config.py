from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

DEFAULT_SK_WS_URL = "ws://localhost:3000/signalk/v1/stream"
# Lake Erie — shipped sample location. Override [chart] in polarprism.toml.
DEFAULT_CHART_LAT = 41.49
DEFAULT_CHART_LON = -81.73
DEFAULT_CHART_ZOOM = 9
DEFAULT_FPS = 30
DEFAULT_TILE_ONLINE = True
# Opaque base map (land/water/coastline). The seamark layer is a transparent
# overlay drawn on top of it.
DEFAULT_TILE_BASE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_TILE_URL = "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"

SAIL_COLOR_PALETTE = [
    (100, 180, 255),
    (160, 230, 80),
    (255, 110, 60),
    (200, 130, 255),
    (255, 200, 60),
    (60, 220, 200),
    (255, 80, 160),
    (140, 200, 100),
]


def _find_config_path() -> str | None:
    # Prefer TOML, but also accept the JSON fallback that save_config writes
    # when tomli_w is unavailable.
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    for name in ("polarprism.toml", "polarprism.json"):
        cwd = os.path.join(os.getcwd(), name)
        if os.path.exists(cwd):
            return cwd
        xdg_path = os.path.join(xdg, "polarprism", name)
        if os.path.exists(xdg_path):
            return xdg_path
    return None


def _parse_config_file(path: str) -> dict[str, Any]:
    """Parse a config file, selecting the parser by extension.

    ``.json`` files are read as JSON; everything else is read as TOML (the
    documented default). Falls back to JSON if TOML support is unavailable
    (Python < 3.11) so the in-app JSON config still loads. Returns ``{}`` on
    any read/parse error so a bad config never blocks startup.
    """
    is_json = path.lower().endswith(".json")
    try:
        if is_json or tomllib is None:
            with open(path) as f:
                loaded = json.load(f)
        else:
            with open(path, "rb") as f:
                loaded = tomllib.load(f)
    except (OSError, ValueError):
        # ValueError covers json.JSONDecodeError and tomllib.TOMLDecodeError.
        return {}
    # A top-level non-mapping (e.g. a bare JSON list) is not a valid config.
    return loaded if isinstance(loaded, dict) else {}


def ws_url_to_rest_url(ws_url: str) -> str:
    is_secure = ws_url.startswith("wss://")
    http_url = ws_url.replace("wss://", "https://").replace("ws://", "http://")
    path = ws_url.split("://", 1)[1] if "://" in ws_url else ws_url
    host_end = path.find("/")
    if host_end == -1:
        return http_url
    host_part = path[:host_end]
    scheme = "https" if is_secure else "http"
    return f"{scheme}://{host_part}/signalk/v1/api"


@dataclass
class Config:
    signalk_url: str = DEFAULT_SK_WS_URL
    signalk_rest_url: str = ""
    chart_lat: float = DEFAULT_CHART_LAT
    chart_lon: float = DEFAULT_CHART_LON
    chart_zoom: int = DEFAULT_CHART_ZOOM
    polars_dir: str = ""
    routes_dir: str = ""
    tiles_dir: str = ""
    log_dir: str = ""
    raw_dir: str = ""
    error_log_dir: str = ""
    auto_convert_raw: bool = False
    local_tz_offset: float = 0.0
    fps: int = DEFAULT_FPS
    tile_online: bool = DEFAULT_TILE_ONLINE
    tile_base_url: str = DEFAULT_TILE_BASE_URL
    tile_url: str = DEFAULT_TILE_URL
    sail_groups: list[tuple[str, list[str]]] = field(default_factory=list)
    sail_to_polar: dict[str, str] = field(default_factory=dict)
    sail_colors: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    polar_name_prefix: str = ""
    default_polar: str = ""
    load_measured: bool = False
    measured_dir: str = ""
    # Coverage grid controls
    coverage_twa_min: int = 30
    coverage_twa_max: int = 180
    coverage_twa_bin: int = 5
    coverage_tws_min: int = 6
    coverage_tws_max: int = 30
    coverage_tws_bin: int = 2
    coverage_min_samples: int = 3
    coverage_min_stw_kts: float = 2.0
    coverage_min_aws_kts: float = 4.0
    _source_path: str | None = None

    def __post_init__(self) -> None:
        if not self.signalk_rest_url:
            self.signalk_rest_url = ws_url_to_rest_url(self.signalk_url)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if not self.polars_dir:
            self.polars_dir = os.path.join(base_dir, "polars")
        if not self.routes_dir:
            self.routes_dir = os.path.join(base_dir, "routes")
        if not self.tiles_dir:
            self.tiles_dir = os.path.join(base_dir, "tiles")
        if not self.log_dir:
            self.log_dir = os.path.join(base_dir, "sailing_logs")
        if not self.raw_dir:
            self.raw_dir = os.path.join(base_dir, "logs", "raw")
        if not self.error_log_dir:
            self.error_log_dir = os.path.join(
                os.path.expanduser("~"), ".local", "share", "polarprism"
            )
        if not self.measured_dir:
            self.measured_dir = os.path.join(self.polars_dir, "measured")


def load_config(override_path: str | None = None) -> Config:
    config_path = override_path or _find_config_path()
    cfg = Config()

    data: dict[str, Any] = {}
    if config_path is not None:
        data = _parse_config_file(config_path)
        if os.path.exists(config_path):
            cfg._source_path = config_path

        sk = data.get("signalk", {})
        if "url" in sk:
            cfg.signalk_url = sk["url"]
        cfg.signalk_rest_url = ws_url_to_rest_url(cfg.signalk_url)

        chart = data.get("chart", {})
        if "default_lat" in chart:
            cfg.chart_lat = float(chart["default_lat"])
        if "default_lon" in chart:
            cfg.chart_lon = float(chart["default_lon"])
        if "default_zoom" in chart:
            cfg.chart_zoom = int(chart["default_zoom"])

        paths = data.get("paths", {})
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if "polars_dir" in paths:
            p = paths["polars_dir"]
            cfg.polars_dir = p if os.path.isabs(p) else os.path.join(base_dir, p)
        if "routes_dir" in paths:
            p = paths["routes_dir"]
            cfg.routes_dir = p if os.path.isabs(p) else os.path.join(base_dir, p)
        if "tiles_dir" in paths:
            p = paths["tiles_dir"]
            cfg.tiles_dir = p if os.path.isabs(p) else os.path.join(base_dir, p)
        if "log_dir" in paths:
            p = paths["log_dir"]
            cfg.log_dir = p if os.path.isabs(p) else os.path.join(base_dir, p)
        if "raw_dir" in paths:
            p = paths["raw_dir"]
            cfg.raw_dir = p if os.path.isabs(p) else os.path.join(base_dir, p)

        display = data.get("display", {})
        if "fps" in display:
            cfg.fps = int(display["fps"])

        tile = data.get("tile", {})
        if "online" in tile:
            cfg.tile_online = bool(tile["online"])
        if "base_url" in tile:
            cfg.tile_base_url = tile["base_url"]
        if "url" in tile:
            cfg.tile_url = tile["url"]

        logging_cfg = data.get("logging", {})
        if "auto_convert_raw" in logging_cfg:
            cfg.auto_convert_raw = bool(logging_cfg["auto_convert_raw"])
        if "local_tz_offset" in logging_cfg:
            cfg.local_tz_offset = float(logging_cfg["local_tz_offset"])
        if "error_log_dir" in logging_cfg:
            cfg.error_log_dir = str(logging_cfg["error_log_dir"])

        sail_groups_raw = data.get("sail", {}).get("groups", [])
        if sail_groups_raw:
            cfg.sail_groups = []
            for g in sail_groups_raw:
                name = g.get("name", "sails")
                sails = g.get("sails", [])
                cfg.sail_groups.append((name, list(sails)))

        sail_polar_raw = data.get("sail", {}).get("polar_map", {})
        if sail_polar_raw:
            cfg.sail_to_polar = dict(sail_polar_raw)

        sail_color_raw = data.get("sail", {}).get("colors", {})
        if sail_color_raw:
            cfg.sail_colors = {k: tuple(v) for k, v in sail_color_raw.items()}

        prefix = data.get("sail", {}).get("polar_name_prefix", "")
        if prefix:
            cfg.polar_name_prefix = prefix

        polar_cfg = data.get("polar", {})
        if "default_polar" in polar_cfg:
            cfg.default_polar = str(polar_cfg["default_polar"])
        if "load_measured" in polar_cfg:
            cfg.load_measured = bool(polar_cfg["load_measured"])
        if "measured_dir" in polar_cfg:
            cfg.measured_dir = str(polar_cfg["measured_dir"])

        coverage_cfg = data.get("coverage", {})
        if "twa_min" in coverage_cfg:
            cfg.coverage_twa_min = int(coverage_cfg["twa_min"])
        if "twa_max" in coverage_cfg:
            cfg.coverage_twa_max = int(coverage_cfg["twa_max"])
        if "twa_bin" in coverage_cfg:
            cfg.coverage_twa_bin = int(coverage_cfg["twa_bin"])
        if "tws_min" in coverage_cfg:
            cfg.coverage_tws_min = int(coverage_cfg["tws_min"])
        if "tws_max" in coverage_cfg:
            cfg.coverage_tws_max = int(coverage_cfg["tws_max"])
        if "tws_bin" in coverage_cfg:
            cfg.coverage_tws_bin = int(coverage_cfg["tws_bin"])
        if "min_samples" in coverage_cfg:
            cfg.coverage_min_samples = int(coverage_cfg["min_samples"])
        if "min_stw_kts" in coverage_cfg:
            cfg.coverage_min_stw_kts = float(coverage_cfg["min_stw_kts"])
        if "min_aws_kts" in coverage_cfg:
            cfg.coverage_min_aws_kts = float(coverage_cfg["min_aws_kts"])

    cfg.__post_init__()
    return cfg


SETUP_CHECKLIST = [
    {
        "key": "signalk",
        "title": "Connect to Signal K",
        "status_fn": lambda state, cfg: "ok" if state.connected else "missing",
        "ok_text": "Connected",
        "missing_text": "Not connected",
        "steps": [
            "Install Signal K server (https://signalk.org)",
            "Connect instruments (wind, speed, heading, GPS) via NMEA 2000",
            "Set the WebSocket URL in Settings \u2192 SignalK tab, or via --signalk-url",
            "Click Reconnect after changing the URL",
        ],
    },
    {
        "key": "polars",
        "title": "Load Polar Data",
        "status_fn": lambda state, cfg: (
            "warn"
            if getattr(state, "polar_load_failures", [])
            else "ok"
            if state.polar_data
            else "missing"
        ),
        "ok_text": "loaded",
        "warn_text": "Some polars failed to load",
        "missing_text": "None loaded",
        "steps": [
            "Place polar CSV files in the polars/ directory",
            "Each CSV has TWA\\TWS as header, semicolon or comma separated",
            "Optionally add a .saildef file (e.g., MyBoat.saildef) with sail number and name per line: 1;Jib",
            "Optionally add a .sailselect file for recommended sail lookup",
            "Sample J/105 polars ship in polars/ (example_J105_*) — overwrite with your own",
            "Restart PolarPrism to pick up new files",
        ],
    },
    {
        "key": "routes",
        "title": "Load Course Route",
        "status_fn": lambda state, cfg: "ok" if state.routes else "missing",
        "ok_text": "loaded",
        "missing_text": "None loaded",
        "steps": [
            "Place GPX files in the routes/ directory",
            "Each GPX must contain a <route> element with <rtept> waypoints",
            "Waypoints need lat and lon attributes, and optionally a <name>",
            "The first route found is selected by default",
            "A sample Mills Trophy course (Lake Erie) ships in routes/ — overwrite with your own",
            "Press R on the Sailing \u2192 Route tab to cycle between routes",
        ],
    },
    {
        "key": "sails",
        "title": "Configure Sails",
        "status_fn": lambda state, cfg: (
            "ok" if state.sail_groups else "warn" if state.polar_data else "missing"
        ),
        "ok_text": "configured",
        "warn_text": "Polars loaded but no sail groups",
        "missing_text": "No polar data loaded yet",
        "steps": [
            "Create a .saildef file in polars/ (e.g., MyBoat.saildef) with one sail per line: 1;Jib",
            "Sail names in .saildef must match polar CSV filenames (e.g., Jib \u2192 MyBoat_Jib.csv)",
            "Or add [[sail.groups]] to polarprism.toml to define groups:",
            '  [[sail.groups]] name = "headsail" sails = ["Jib", "Code0"]',
            "Sail colors are auto-assigned from a palette, or override in polarprism.toml",
        ],
    },
    {
        "key": "config",
        "title": "Review Configuration",
        "status_fn": lambda state, cfg: "ok" if cfg._source_path else "warn",
        "ok_text": "polarprism.toml found",
        "warn_text": "Using defaults (no config file)",
        "steps": [
            "Copy polarprism.toml.example to polarprism.toml in the project directory",
            "Edit the [signalk] section to set your server URL",
            "Edit the [chart] section for your default location",
            "Optionally add [sail.groups] and [sail.colors] sections",
            "Run: python main.py --config polarprism.toml",
        ],
    },
]


STATE_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "polarprism")
STATE_FILE = os.path.join(STATE_DIR, "state.json")


def save_state(state: Any, config: Config) -> None:
    import json

    os.makedirs(STATE_DIR, exist_ok=True)
    data = {
        "heading_offset": state.heading_offset,
        "polar_active": state.polar_active,
        "polar_tws_index": state.polar_tws_index,
        "active_sails": list(state.active_sails),
        "sailing_state": state.sailing_state,
        "route_active": state.route_active,
        "route_leg_index": state.route_leg_index,
        "chart_center_lat": state.chart_center_lat,
        "chart_center_lon": state.chart_center_lon,
        "chart_zoom": state.chart_zoom,
        "active_nav": state.active_nav,
        "active_tab": state.active_tab,
        "signalk_url": config.signalk_url,
        "polar_builder_groups": state.polar_builder_groups,
        "polar_builder_active_group": state.polar_builder_active_group,
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def load_state(state: Any, config: Config) -> None:
    import json

    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    if "heading_offset" in data:
        state.heading_offset = float(data["heading_offset"])
    if "polar_active" in data and data["polar_active"] in state.polar_data:
        state.polar_active = data["polar_active"]
    if "polar_tws_index" in data:
        state.polar_tws_index = int(data["polar_tws_index"])
    if "active_sails" in data:
        state.active_sails = list(data["active_sails"])
    if "sailing_state" in data and data["sailing_state"] in ("sailing", "motoring", "idle"):
        state.sailing_state = data["sailing_state"]
    if "route_active" in data and data["route_active"] in state.routes:
        state.route_active = data["route_active"]
    if "route_leg_index" in data:
        state.route_leg_index = int(data["route_leg_index"])
    if "chart_center_lat" in data:
        state.chart_center_lat = float(data["chart_center_lat"])
    if "chart_center_lon" in data:
        state.chart_center_lon = float(data["chart_center_lon"])
    if "chart_zoom" in data:
        state.chart_zoom = int(data["chart_zoom"])
    if "active_nav" in data:
        state.active_nav = data["active_nav"]
    if "active_tab" in data:
        state.active_tab = int(data["active_tab"])
    if data.get("signalk_url"):
        config.signalk_url = data["signalk_url"]
        config.signalk_rest_url = ws_url_to_rest_url(config.signalk_url)
    if "polar_builder_groups" in data:
        groups = data["polar_builder_groups"]
        if isinstance(groups, list):
            state.polar_builder_groups = [
                g
                for g in groups
                if isinstance(g, dict)
                and isinstance(g.get("name"), str)
                and isinstance(g.get("polar"), str)
                and isinstance(g.get("sessions"), list)
            ]
    if "polar_builder_active_group" in data:
        idx = int(data["polar_builder_active_group"])
        if 0 <= idx <= len(state.polar_builder_groups):
            state.polar_builder_active_group = idx


def save_config(config: Config) -> None:
    existing = {}
    path = config._source_path
    if path and os.path.exists(path):
        existing = _parse_config_file(path)

    existing.setdefault("signalk", {})["url"] = config.signalk_url

    # Persist [sail] sections
    if config.sail_groups:
        sail_section = existing.setdefault("sail", {})
        sail_section["groups"] = [{"name": g[0], "sails": g[1]} for g in config.sail_groups]
    if config.sail_to_polar:
        sail_section = existing.setdefault("sail", {})
        sail_section["polar_map"] = dict(config.sail_to_polar)
    if config.sail_colors:
        sail_section = existing.setdefault("sail", {})
        sail_section["colors"] = {k: list(v) for k, v in config.sail_colors.items()}
    if config.polar_name_prefix:
        sail_section = existing.setdefault("sail", {})
        sail_section["polar_name_prefix"] = config.polar_name_prefix

    # Persist [polar] sections
    polar_section = existing.setdefault("polar", {})
    if config.default_polar:
        polar_section["default_polar"] = config.default_polar
    if config.load_measured:
        polar_section["load_measured"] = config.load_measured
    if config.measured_dir:
        polar_section["measured_dir"] = config.measured_dir

    # Persist [coverage] sections
    coverage_section = existing.setdefault("coverage", {})
    coverage_section["twa_min"] = config.coverage_twa_min
    coverage_section["twa_max"] = config.coverage_twa_max
    coverage_section["twa_bin"] = config.coverage_twa_bin
    coverage_section["tws_min"] = config.coverage_tws_min
    coverage_section["tws_max"] = config.coverage_tws_max
    coverage_section["tws_bin"] = config.coverage_tws_bin
    coverage_section["min_samples"] = config.coverage_min_samples
    coverage_section["min_stw_kts"] = config.coverage_min_stw_kts
    coverage_section["min_aws_kts"] = config.coverage_min_aws_kts

    if not path:
        path = os.path.join(os.getcwd(), "polarprism.toml")

    try:
        import tomli_w

        with open(path, "wb") as f:
            tomli_w.dump(existing, f)
        config._source_path = path
    except ImportError:
        simple = {
            "signalk": existing.get("signalk", {}),
        }
        json_path = path
        if json_path.endswith(".toml"):
            json_path = json_path.replace(".toml", ".json")
        with open(json_path, "w") as f:
            json.dump(simple, f, indent=2)
        config._source_path = json_path
