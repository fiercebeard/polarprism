#!/usr/bin/env python3
import asyncio
import json
import math
import os
import struct
import sys
from datetime import datetime, timezone

import aiofiles
import pygame
import websockets
import traceback

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heading_log.jsonl")
ERROR_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error.log")
LOG_INTERVAL = 1.0
WINDOW_W = 1200
WINDOW_H = 700
FPS = 30

COMPASS_AREA_W = WINDOW_W // 2
COMPASS_AREA_H = WINDOW_H
COMPASS_CX = COMPASS_AREA_W // 2
COMPASS_CY = 225
COMPASS_RADIUS = 195

CHART_X = COMPASS_AREA_W
CHART_Y = 0
CHART_W = WINDOW_W - COMPASS_AREA_W
CHART_H = WINDOW_H

ZOOM_BTN_SIZE = 28
ZOOM_BTN_MARGIN = 8

SK_WS_URL = "ws://localhost:3000/signalk/v1/stream"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heading_log.jsonl")
LOG_INTERVAL = 1.0

BG_COLOR = (10, 12, 18)
GRID_COLOR = (30, 40, 55)
GRID_COLOR_MAJOR = (45, 60, 85)
TEXT_COLOR = (180, 190, 200)
VESSEL_COLOR = (200, 210, 220)
WATER_COLOR = (8, 14, 28)

COLORS = {
    "headingMagnetic": (0, 220, 60),
    "headingTrue": (255, 255, 255),
    "cogTrue": (255, 60, 60),
    "apTargetMagnetic": (255, 255, 0),
    "magneticVariation": (80, 110, 255),
    "rateOfTurn": (190, 120, 255),
    "fusionTrue": (0, 200, 255),
}

LABELS = {
    "headingMagnetic": "MAG HDG",
    "headingTrue": "TRUE HDG",
    "cogTrue": "COG TRUE",
    "apTargetMagnetic": "AP TARGET",
    "magneticVariation": "MAG VAR",
    "rateOfTurn": "ROT",
    "fusionTrue": "FUSION",
}

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
        self.show_diagnostics = True


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


def derive_true_heading(state):
    sk_ht = state.values.get("headingTrue")
    if sk_ht is not None:
        return norm_angle(sk_ht + math.radians(state.heading_offset))
    hm = state.values.get("headingMagnetic")
    mv = state.values.get("magneticVariation")
    if hm is not None and mv is not None:
        return norm_angle(hm + mv + math.radians(state.heading_offset))
    return None


def update_from_delta(state, msg):
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return

    if data.get("vessels"):
        for vessel in data["vessels"].values():
            nav = vessel.get("navigation", {})
            steering = vessel.get("steering", {})
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
                    if "value" in leaf:
                        val = leaf["value"]
                        if val is not None:
                            state.values[key] = val
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


async def ws_reader(state):
    while True:
        try:
            async with websockets.connect(SK_WS_URL) as ws:
                state.connected = True
                sub = {
                    "context": "vessels.self",
                    "subscribe": [
                        {"path": "navigation.headingMagnetic"},
                        {"path": "navigation.headingTrue"},
                        {"path": "navigation.courseOverGroundTrue"},
                        {"path": "navigation.magneticVariation"},
                        {"path": "navigation.rateOfTurn"},
                        {"path": "navigation.speedOverGround"},
                        {"path": "navigation.speedThroughWater"},
                        {"path": "navigation.attitude"},
                        {"path": "navigation.position"},
                        {"path": "steering.autopilot.target.headingMagnetic"},
                        {"path": "steering.rudderAngle"},
                        {"path": "environment.wind.angleApparent"},
                        {"path": "environment.wind.speedApparent"},
                        {"path": "name"},
                    ],
                }
                await ws.send(json.dumps(sub))
                async for msg in ws:
                    update_from_delta(state, msg)
        except (ConnectionRefusedError, OSError, websockets.InvalidURI):
            pass
        except Exception as e:
            log_error(f"ws_reader: {e}")
        state.connected = False
        await asyncio.sleep(2)


async def fetch_vessel_name(state):
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:3000/signalk/v1/api/vessels/self", timeout=5)
        data = json.loads(resp.read())
        name = data.get("name")
        if name:
            state.vessel_name = name
    except Exception:
        pass


async def fetch_device_names(state):
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:3000/signalk/v1/api/sources", timeout=5)
        data = json.loads(resp.read())
        ngt1 = data.get("NGT1", {})
        for src_id, src_data in ngt1.items():
            if not src_id.isdigit():
                continue
            n2k = src_data.get("n2k", {})
            model_id = n2k.get("modelId", "")
            model_ver = n2k.get("modelVersion", "")
            mfr = n2k.get("manufacturerCode", "")
            label = model_id
            if model_ver:
                label = f"{model_id} ({model_ver})"
            if mfr and mfr != model_id:
                label = f"{mfr} {model_id}"
            full_src = f"NGT1.{src_id}"
            state.device_names[full_src] = label
    except Exception:
        pass


async def fetch_multi_values(state):
    while True:
        try:
            import urllib.request
            resp = urllib.request.urlopen("http://localhost:3000/signalk/v1/api/vessels/self", timeout=5)
            data = json.loads(resp.read())
            nav = data.get("navigation", {})
            for key in ["magneticVariation", "headingMagnetic", "courseOverGroundTrue", "headingTrue",
                         "speedOverGround", "speedThroughWater", "rateOfTurn", "attitude"]:
                val = nav.get(key, {})
                if isinstance(val, dict) and "values" in val:
                    state.multi_values[key] = {}
                    for src, sv in val["values"].items():
                        sv_val = sv.get("value")
                        if isinstance(sv_val, dict):
                            state.multi_values[key][src] = sv_val
                        elif sv_val is not None:
                            state.multi_values[key][src] = sv_val
        except Exception:
            pass
        await asyncio.sleep(5)


async def logger(state):
    while True:
        await asyncio.sleep(LOG_INTERVAL)
        now = datetime.now(timezone.utc)
        ht_val = derive_true_heading(state)
        entry = {
            "ts": now.isoformat(),
            "vessel": state.vessel_name or None,
        }
        for key in ["headingMagnetic", "cogTrue", "apTargetMagnetic", "magneticVariation", "rateOfTurn"]:
            v = state.values.get(key)
            if v is not None:
                if key == "magneticVariation":
                    deg = rad_to_deg_signed(v)
                elif key == "rateOfTurn":
                    deg = rad_to_deg_signed(v) * 1.0
                else:
                    deg = rad_to_deg(v)
                entry[key] = {"value": round(v, 6), "deg": round(deg, 1), "source": state.sources.get(key, "")}
            else:
                entry[key] = None
        if ht_val is not None:
            entry["headingTrue"] = {"value": round(ht_val, 6), "deg": round(rad_to_deg(ht_val), 1), "source": "derived"}
        else:
            entry["headingTrue"] = None
        if state.emulation_active and state.fusion_heading is not None:
            entry["fusionTrue"] = {"value": round(state.fusion_heading, 6), "deg": round(rad_to_deg(state.fusion_heading), 1), "source": "PolarPrism"}
        else:
            entry["fusionTrue"] = None
        pos = state.position
        if pos["lat"] is not None or pos["lon"] is not None:
            entry["position"] = {"lat": pos["lat"], "lon": pos["lon"]}
        try:
            async with aiofiles.open(LOG_FILE, mode="a") as f:
                await f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError:
            pass
        state.last_log_time = now.timestamp()


MIN_ANGLE_DIFF = 0.001


def angle_diff(a, b):
    d = (a - b + math.pi) % (2 * math.pi) - math.pi
    return d


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

    hdg_weight = 1.0 - cog_weight

    fused = norm_angle(heading_true_raw * hdg_weight + (cog_true * cog_weight + heading_true_raw * hdg_weight) * (1.0 - 1.0))

    fused = norm_angle(heading_true_raw + angle_diff(cog_true, heading_true_raw) * cog_weight)

    return fused


async def ws_writer(state):
    while True:
        if not state.emulation_active:
            await asyncio.sleep(0.5)
            continue
        try:
            if state.fusion_ws is None:
                state.fusion_ws = await websockets.connect(SK_WS_URL)
            fused = compute_fusion_heading(state)
            if fused is not None:
                state.fusion_heading = fused
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                delta = {
                    "context": "vessels.self",
                    "updates": [{
                        "source": {"label": "PolarPrism", "type": "fusion"},
                        "timestamp": now,
                        "values": [
                            {"path": "navigation.headingTrue", "value": round(fused, 5)}
                        ]
                    }]
                }
                try:
                    await state.fusion_ws.send(json.dumps(delta))
                except websockets.ConnectionClosed:
                    state.fusion_ws = None
        except (ConnectionRefusedError, OSError):
            state.fusion_ws = None
        await asyncio.sleep(1.0)


def draw_compass(surface, font, font_sm, state):
    cx, cy, r = COMPASS_CX, COMPASS_CY, COMPASS_RADIUS

    pygame.draw.circle(surface, (20, 25, 35), (cx, cy), r + 6)
    pygame.draw.circle(surface, (40, 50, 70), (cx, cy), r + 6, 2)
    pygame.draw.circle(surface, (15, 18, 28), (cx, cy), r)

    for deg in range(0, 360, 1):
        a_rad = math.radians(deg) - math.pi / 2
        if deg % 30 == 0:
            inner = r - 22
            w = 2
            lbl = f"{deg}"
            if deg == 0:
                lbl = "N"
            elif deg == 90:
                lbl = "E"
            elif deg == 180:
                lbl = "S"
            elif deg == 270:
                lbl = "W"
            lx = cx + math.cos(a_rad) * (r - 38)
            ly = cy + math.sin(a_rad) * (r - 38)
            ts = font.render(lbl, True, TEXT_COLOR)
            surface.blit(ts, (lx - ts.get_width() // 2, ly - ts.get_height() // 2))
        elif deg % 10 == 0:
            inner = r - 14
            w = 1
        elif deg % 5 == 0:
            inner = r - 9
            w = 1
        else:
            continue
        outer = r - 2
        x1 = cx + math.cos(a_rad) * inner
        y1 = cy + math.sin(a_rad) * inner
        x2 = cx + math.cos(a_rad) * outer
        y2 = cy + math.sin(a_rad) * outer
        pygame.draw.line(surface, (60, 70, 90), (x1, y1), (x2, y2), w)

    angle_keys = ["headingMagnetic", "headingTrue", "cogTrue", "apTargetMagnetic"]
    if state.emulation_active and state.fusion_heading is not None:
        angle_keys.append("fusionTrue")

    for key in angle_keys:
        if key == "headingTrue":
            val = derive_true_heading(state)
        elif key == "fusionTrue":
            val = state.fusion_heading
        else:
            val = state.values.get(key)
        if val is None:
            continue
        color = COLORS[key]
        a = val - math.pi / 2
        tip_x = cx + math.cos(a) * (r - 5)
        tip_y = cy + math.sin(a) * (r - 5)
        tail_len = r * 0.15
        tail_x = cx - math.cos(a) * tail_len
        tail_y = cy - math.sin(a) * tail_len
        mid_x = cx + math.cos(a) * (r * 0.7)
        mid_y = cy + math.sin(a) * (r * 0.7)
        perp_a = a + math.pi / 2
        hw = 10
        p1 = (mid_x + math.cos(perp_a) * hw, mid_y + math.sin(perp_a) * hw)
        p2 = (mid_x - math.cos(perp_a) * hw, mid_y - math.sin(perp_a) * hw)
        pygame.draw.polygon(surface, color, [(tip_x, tip_y), p1, p2])
        pygame.draw.line(surface, color, (tail_x, tail_y), (cx, cy), 2)
        pygame.draw.circle(surface, color, (int(cx + math.cos(a) * (r + 16)), int(cy + math.sin(a) * (r + 16))), 4)

    mv = state.values.get("magneticVariation")
    if mv is not None:
        color = COLORS["magneticVariation"]
        start_a = -math.pi / 2
        end_a = mv - math.pi / 2
        if abs(mv) > 0.001:
            arc_r = r + 16
            n_pts = max(10, int(abs(math.degrees(mv)) * 2))
            pts = []
            for i in range(n_pts + 1):
                t = start_a + (end_a - start_a) * i / n_pts
                pts.append((cx + math.cos(t) * arc_r, cy + math.sin(t) * arc_r))
            if len(pts) >= 2:
                pygame.draw.lines(surface, color, False, pts, 2)
                label_a = (start_a + end_a) / 2
                lx2 = cx + math.cos(label_a) * (arc_r + 14)
                ly2 = cy + math.sin(label_a) * (arc_r + 14)
                deg_lbl = f"{rad_to_deg_signed(mv):.1f}\u00b0"
                ts2 = font_sm.render(deg_lbl, True, color)
                surface.blit(ts2, (lx2 - ts2.get_width() // 2, ly2 - ts2.get_height() // 2))

    pygame.draw.circle(surface, (50, 60, 80), (cx, cy), 6)
    pygame.draw.circle(surface, (30, 35, 50), (cx, cy), 4)


def draw_legend(surface, font, font_sm, state):
    x0 = 20
    y0 = COMPASS_CY + COMPASS_RADIUS + 20
    items = []
    legend_keys = ["headingMagnetic", "headingTrue", "cogTrue", "apTargetMagnetic", "magneticVariation", "rateOfTurn"]
    if state.emulation_active:
        legend_keys.append("fusionTrue")
    for key in legend_keys:
        label = LABELS[key]
        color = COLORS[key]
        if key == "headingTrue":
            val = derive_true_heading(state)
            deg_str = f"{rad_to_deg(val):06.1f}\u00b0" if val is not None else "---\u00b0"
            src = state.sources.get("headingTrue", "")
            if src:
                device = f"CALC: {state.device_names.get(src, src)}"
            else:
                mv_src = state.sources.get("magneticVariation", "")
                hm_src = state.sources.get("headingMagnetic", "")
                hm_dev = state.device_names.get(hm_src, hm_src)
                mv_dev = state.device_names.get(mv_src, mv_src)
                if hm_dev and mv_dev and hm_dev != mv_dev:
                    device = f"CALC: {hm_dev}+{mv_dev}"
                elif hm_dev:
                    device = f"CALC: {hm_dev}"
                else:
                    device = "CALC"
        elif key == "fusionTrue":
            val = state.fusion_heading
            deg_str = f"{rad_to_deg(val):06.1f}\u00b0" if val is not None else "---\u00b0"
            src = "PolarPrism"
            device = "Fusion Engine"
        elif key == "magneticVariation":
            v = state.values.get(key)
            deg_str = f"{rad_to_deg_signed(v):+.1f}\u00b0" if v is not None else "---\u00b0"
            src = state.sources.get(key, "")
            device = state.device_names.get(src, src)
        elif key == "rateOfTurn":
            v = state.values.get(key)
            deg_str = f"{rad_to_deg_signed(v):+.3f}\u00b0/s" if v is not None else "---\u00b0/s"
            src = state.sources.get(key, "")
            device = state.device_names.get(src, src)
        else:
            v = state.values.get(key)
            deg_str = f"{rad_to_deg(v):06.1f}\u00b0" if v is not None else "---\u00b0"
            src = state.sources.get(key, "")
            device = state.device_names.get(src, src)
        items.append((label, color, deg_str, src, device))

    row_h = 28
    for i, (label, color, deg_str, src, device) in enumerate(items):
        yy = y0 + i * row_h
        pygame.draw.rect(surface, color, (x0, yy + 2, 16, 12))
        ts = font_sm.render(f" {label}", True, color)
        surface.blit(ts, (x0 + 20, yy))
        ts2 = font.render(deg_str, True, TEXT_COLOR)
        surface.blit(ts2, (x0 + 130, yy))
        src_text = f"[{src}]"
        if device and device != src:
            src_text = f"{device}"
        if len(src_text) > 28:
            src_text = src_text[:27] + "\u2026"
        ts3 = font_sm.render(src_text, True, (80, 90, 100))
        surface.blit(ts3, (x0 + 270, yy + 2))

    conn_color = (0, 200, 80) if state.connected else (200, 50, 50)
    conn_text = "WS: CONNECTED" if state.connected else "WS: DISCONNECTED"
    ts4 = font_sm.render(conn_text, True, conn_color)
    surface.blit(ts4, (x0, y0 + len(items) * row_h + 6))

    emu_y = y0 + len(items) * row_h + 24
    emu_color = (0, 200, 255) if state.emulation_active else (80, 80, 80)
    emu_text = "FUSION: ON [F]" if state.emulation_active else "FUSION: OFF [F]"
    ts5 = font_sm.render(emu_text, True, emu_color)
    surface.blit(ts5, (x0, emu_y))


def draw_diagnostics(surface, font, font_sm, state):
    x0 = 8
    y0 = COMPASS_CY + COMPASS_RADIUS + 16 
    surface.fill(BG_COLOR, (0, y0 - 12, COMPASS_AREA_W, WINDOW_H - y0 + 12))

    warn_color = (255, 80, 80)
    dim_color = (80, 90, 100)
    label_color = (150, 160, 180)
    val_color = (220, 230, 240)
    src_color = (90, 100, 115)
    section_color = (100, 120, 150)
    row_h = 17

    hm = state.values.get("headingMagnetic")
    mv = state.values.get("magneticVariation")
    cog = state.values.get("cogTrue")
    sog = state.values.get("speedOverGround")
    stw = state.values.get("speedThroughWater")
    rot = state.values.get("rateOfTurn")
    rudder = state.values.get("rudderAngle")
    roll = state.values.get("roll")
    pitch = state.values.get("pitch")
    yaw = state.values.get("yaw")
    sk_ht = state.values.get("headingTrue")
    waa = state.values.get("windAngleApparent")
    was = state.values.get("windSpeedApparent")
    ap_target = state.values.get("apTargetMagnetic")

    derived_ht = None
    if hm is not None and mv is not None:
        derived_ht = norm_angle(hm + mv + math.radians(state.heading_offset))

    y = y0 - 8

    def section(title):
        nonlocal y
        y += 4
        ts = font_sm.render(title, True, section_color)
        surface.blit(ts, (x0, y))
        y += row_h - 2

    def row(label, value_str, detail="", color=val_color, warn=False):
        nonlocal y
        ts_l = font_sm.render(label, True, label_color)
        surface.blit(ts_l, (x0, y))
        ts_v = font_sm.render(value_str, True, warn_color if warn else color)
        surface.blit(ts_v, (x0 + 140, y))
        if detail:
            ts_d = font_sm.render(detail, True, dim_color)
            surface.blit(ts_d, (x0 + 260, y))
        y += row_h

    def dev_row(label, value_str, src_key, color=val_color, warn=False):
        nonlocal y
        ts_l = font_sm.render(label, True, label_color)
        surface.blit(ts_l, (x0, y))
        ts_v = font_sm.render(value_str, True, warn_color if warn else color)
        surface.blit(ts_v, (x0 + 140, y))
        src = state.sources.get(src_key, "")
        dev = state.device_names.get(src, src) if src else ""
        if dev:
            ts_d = font_sm.render(dev, True, src_color)
            surface.blit(ts_d, (x0 + 260, y))
        y += row_h

    section("--- EV-1 Course Computer [204] ---")
    dev_row("Mag Heading:", f"{rad_to_deg(hm):06.1f}\u00b0" if hm is not None else "---\u00b0", "headingMagnetic")
    dev_row("Rate of Turn:", f"{math.degrees(rot):+.2f}\u00b0/s" if rot is not None else "---\u00b0/s", "rateOfTurn")
    if yaw is not None:
        row("  Yaw:", f"{math.degrees(yaw):06.1f}\u00b0")
    if roll is not None:
        row("  Roll:", f"{math.degrees(roll):+.1f}\u00b0")
    if pitch is not None:
        row("  Pitch:", f"{math.degrees(pitch):+.2f}\u00b0")
    dev_row("AP Target:", f"{rad_to_deg(ap_target):06.1f}\u00b0" if ap_target is not None else "---\u00b0", "apTargetMagnetic")

    section("--- AXIOM 9 [11] ---")
    dev_row("Mag Variation:", f"{rad_to_deg_signed(mv):+.2f}\u00b0" if mv is not None else "---\u00b0", "magneticVariation")

    section("--- Vesper CORTEX [22] ---")
    dev_row("COG True:", f"{rad_to_deg(cog):06.1f}\u00b0" if cog is not None else "---\u00b0", "cogTrue")
    dev_row("SOG:", f"{(sog or 0)*1.94384:.2f} kts" if sog is not None else "--- kts", "speedOverGround")

    section("--- DST810 [35] ---")
    dev_row("STW:", f"{(stw or 0)*1.94384:.2f} kts" if stw is not None else "--- kts", "speedThroughWater")

    section("--- ACU400 Rudder [172] ---")
    dev_row("Rudder:", f"{math.degrees(rudder):+.1f}\u00b0" if rudder is not None else "---\u00b0", "rudderAngle")

    section("--- iTC5 Wind [105] ---")
    if was is not None:
        row("App Wind:", f"{math.degrees(waa):+.0f}\u00b0 at {was*1.94384:.1f} kts" if waa is not None else "--- kts")

    section("--- CALC: Heading Error ---")
    calc_color = (100, 220, 180)
    if derived_ht is not None:
        calc_label = "TRUE HDG"
        calc_src = "(CALC: Mag+Var)"
    elif hm is not None:
        calc_label = "MAG HDG"
        calc_src = "(no variation)"
        derived_ht = hm
    else:
        calc_label = None

    if derived_ht is not None and cog is not None:
        hdg_err = angle_diff(cog, derived_ht)
        hdg_err_deg = math.degrees(hdg_err)
        sog_kts = (sog or 0) * 1.94384
        stw_kts = (stw or 0) * 1.94384
        row(f"{calc_label}:", f"{rad_to_deg(derived_ht):06.1f}\u00b0", calc_src, color=calc_color)
        row("COG TRUE:", f"{rad_to_deg(cog):06.1f}\u00b0", "(measured)")
        row("HDG ERROR:", f"{hdg_err_deg:+.1f}\u00b0",
            "COG-Heading" if abs(hdg_err_deg) < 180 else "wrap?",
            warn=abs(hdg_err_deg) > 15 and sog_kts > 1.0)
        if abs(hdg_err_deg) > 180:
            hdg_err_deg = ((hdg_err_deg + 180) % 360) - 180

        if sog_kts > 1.5 and stw_kts > 0.5:
            current_speed = sog_kts - stw_kts * math.cos(hdg_err * stw_kts / max(sog_kts, 0.1))
            current_drift = stw_kts * abs(math.sin(hdg_err)) / max(sog_kts, 0.1)
            leeway_est = math.degrees(math.asin(min(1, max(-1, math.sin(hdg_err) * sog_kts / max(stw_kts, 0.1)))))
            row("CALC: Current:", f"{abs(current_speed):.1f} kts",
                "set" if abs(current_speed) > 1 else "light")
            row("CALC: Drift:", f"{current_drift:.1f} kts",
                f"{math.degrees(hdg_err):+.0f}\u00b0 set")
            row("CALC: Leeway:", f"{leeway_est:+.1f}\u00b0", "(est from hdg-COG)")
        elif sog_kts > 1.5:
            row("CALC: Leeway:", f"{hdg_err_deg:+.1f}\u00b0 (incl. current)", "(no STW)")
        else:
            row("SOG:", f"{sog_kts:.1f} kts", "too slow for calc")

    if hm is not None and cog is not None:
        mag_cog = math.degrees(angle_diff(hm, cog))
        row("CALC: Mag-COG:", f"{mag_cog:+.1f}\u00b0",
            "(includes variation+leeway+current)")

    if hm is not None and mv is not None and ap_target is not None:
        ap_true = norm_angle(ap_target + mv)
        if derived_ht is not None:
            ap_off = math.degrees(angle_diff(ap_true, derived_ht))
            row("CALC: AP off hdg:", f"{ap_off:+.1f}\u00b0",
                "to port" if ap_off > 0 else "to stbd")

    section("--- Variation Sources ---")
    mv_multi = state.multi_values.get("magneticVariation", {})
    if mv_multi and len(mv_multi) >= 2:
        vals = []
        for src, v in mv_multi.items():
            dev_name = state.device_names.get(src, src)
            vals.append((dev_name, math.degrees(v), src))
        vals.sort(key=lambda x: x[1])
        delta = vals[-1][1] - vals[0][1]
        for dev_name, v_deg, src in vals:
            row(f"  {dev_name}:", f"{v_deg:+.4f}\u00b0", f"({src})")
        row("CALC: Delta:", f"{delta:+.4f}\u00b0", "EXCESSIVE" if abs(delta) > 0.5 else "OK",
            warn=abs(delta) > 0.5)

    section("--- Hdg Offset ---")
    row("Offset:", f"{state.heading_offset:+.1f}\u00b0", "[\u200b]/] to adjust")


TILE_SIZE = 256
TILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiles")
TILE_CACHE = {}
MAX_TILE_ZOOM = 13
MIN_TILE_ZOOM = 7


def latlon_to_tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def tile_xy_to_latlon(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def get_tile(z, tx, ty):
    key = (z, tx, ty)
    if key in TILE_CACHE:
        return TILE_CACHE[key]
    path = os.path.join(TILE_DIR, str(z), str(tx), f"{ty}.png")
    if os.path.exists(path):
        try:
            surf = pygame.image.load(path)
            TILE_CACHE[key] = surf
            return surf
        except Exception:
            pass
    return None


MAX_TILE_ZOOM = 13
MIN_TILE_ZOOM = 7


def choose_zoom(scale):
    z = MIN_TILE_ZOOM + int(math.log2(max(scale, 1.0)))
    return max(MIN_TILE_ZOOM, min(MAX_TILE_ZOOM, z))


def draw_chart(surface, font, font_sm, state):
    chart_rect = pygame.Rect(CHART_X, CHART_Y, CHART_W, CHART_H)
    pygame.draw.rect(surface, WATER_COLOR, chart_rect)

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

    half_w = CHART_W // 2
    half_h = CHART_H // 2

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
            px = CHART_X + pixel_offset_x + (tx - int(center_tile_x)) * TILE_SIZE
            py = CHART_Y + pixel_offset_y + (ty - int(center_tile_y)) * TILE_SIZE
            surface.blit(tile_surf, (int(px), int(py)))

    surface.set_clip(None)

    def ll_to_px(lat, lon):
        fx, fy = latlon_to_tile_xy(lat, lon, z)
        px = CHART_X + half_w + (fx - center_tile_x) * TILE_SIZE
        py = CHART_Y + half_h + (fy - center_tile_y) * TILE_SIZE
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
        if CHART_Y <= py <= CHART_Y + CHART_H:
            is_major = abs(lat_g - round(lat_g / (grid_step * 2)) * (grid_step * 2)) < grid_step * 0.01
            c = GRID_COLOR_MAJOR if is_major else GRID_COLOR
            pygame.draw.line(surface, c, (CHART_X, int(py)), (CHART_X + CHART_W, int(py)), 1)
            if grid_step < 0.01:
                lbl = f"{lat_g:.4f}\u00b0"
            elif grid_step < 0.1:
                lbl = f"{lat_g:.3f}\u00b0"
            else:
                lbl = f"{lat_g:.1f}\u00b0"
            ts = font_sm.render(lbl, True, (60, 80, 110))
            surface.blit(ts, (CHART_X + 4, int(py) + 2))
        lat_g += grid_step

    lon_g = math.floor(lon_left / grid_step) * grid_step
    while lon_g <= lon_right + grid_step:
        px, py = ll_to_px(center_lat, lon_g)
        if CHART_X <= px <= CHART_X + CHART_W:
            is_major = abs(lon_g - round(lon_g / (grid_step * 2)) * (grid_step * 2)) < grid_step * 0.01
            c = GRID_COLOR_MAJOR if is_major else GRID_COLOR
            pygame.draw.line(surface, c, (int(px), CHART_Y), (int(px), CHART_Y + CHART_H), 1)
            if grid_step < 0.01:
                lbl = f"{lon_g:.4f}\u00b0"
            elif grid_step < 0.1:
                lbl = f"{lon_g:.3f}\u00b0"
            else:
                lbl = f"{lon_g:.1f}\u00b0"
            ts = font_sm.render(lbl, True, (60, 80, 110))
            surface.blit(ts, (int(px) + 4, CHART_Y + CHART_H - 18))
        lon_g += grid_step

    vessel_px, vessel_py = ll_to_px(
        state.position.get("lat") or center_lat,
        state.position.get("lon") or center_lon,
    )

    heading_for_rotation = state.values.get("headingMagnetic")
    if heading_for_rotation is None:
        heading_for_rotation = state.values.get("cogTrue") or 0.0

    line_len = max(CHART_W, CHART_H) * 0.8
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
        color = COLORS[key]
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
    pygame.draw.polygon(surface, VESSEL_COLOR, [bow, port, stern, starboard])
    pygame.draw.polygon(surface, (100, 110, 130), [bow, port, stern, starboard], 1)

    lat_v = state.position.get("lat")
    lon_v = state.position.get("lon")
    lat_s = f"{lat_v:.5f}" if lat_v is not None else "---.-----"
    lon_s = f"{lon_v:.5f}" if lon_v is not None else "---.-----"
    pos_text = f"{lat_s}N  {lon_s}W"
    ts = font_sm.render(pos_text, True, TEXT_COLOR)
    pos_bg = pygame.Surface((ts.get_width() + 8, ts.get_height() + 4), pygame.SRCALPHA)
    pos_bg.fill((0, 0, 0, 150))
    surface.blit(pos_bg, (CHART_X + 4, CHART_Y + 4))
    surface.blit(ts, (CHART_X + 8, CHART_Y + 6))

    zoom_text = f"z{z}"
    zt = font_sm.render(zoom_text, True, TEXT_COLOR)
    surface.blit(zt, (CHART_X + CHART_W - zt.get_width() - 8, CHART_Y + 6))

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
    bar_y = CHART_Y + CHART_H - 25
    bar_x = CHART_X + CHART_W - 20 - int(scale_px)
    pygame.draw.line(surface, TEXT_COLOR, (bar_x, bar_y), (bar_x + int(scale_px), bar_y), 2)
    pygame.draw.line(surface, TEXT_COLOR, (bar_x, bar_y - 5), (bar_x, bar_y + 5), 2)
    pygame.draw.line(surface, TEXT_COLOR, (bar_x + int(scale_px), bar_y - 5), (bar_x + int(scale_px), bar_y + 5), 2)
    if scale_nm >= 1:
        scale_lbl = f"{scale_nm:.0f} nm"
    elif scale_nm >= 0.1:
        scale_lbl = f"{scale_nm:.1f} nm"
    else:
        scale_lbl = f"{scale_nm:.2f} nm"
    ts2 = font_sm.render(scale_lbl, True, TEXT_COLOR)
    surface.blit(ts2, (bar_x + int(scale_px) // 2 - ts2.get_width() // 2, bar_y + 4))

    pygame.draw.rect(surface, (50, 60, 80), chart_rect, 1)

    btn_x = CHART_X + CHART_W - ZOOM_BTN_MARGIN - ZOOM_BTN_SIZE
    btn_y_plus = CHART_Y + ZOOM_BTN_MARGIN
    btn_y_minus = btn_y_plus + ZOOM_BTN_SIZE + 4

    for i, (by, sym) in enumerate([(btn_y_plus, "+"), (btn_y_minus, "\u2013")]):
        btn_rect = pygame.Rect(btn_x, by, ZOOM_BTN_SIZE, ZOOM_BTN_SIZE)
        btn_inner = pygame.Rect(btn_x + 2, by + 2, ZOOM_BTN_SIZE - 4, ZOOM_BTN_SIZE - 4)
        pygame.draw.rect(surface, (30, 40, 55), btn_rect)
        pygame.draw.rect(surface, (80, 100, 130), btn_rect, 1)
        ts = font.render(sym, True, TEXT_COLOR)
        surface.blit(ts, (btn_x + ZOOM_BTN_SIZE // 2 - ts.get_width() // 2,
                          by + ZOOM_BTN_SIZE // 2 - ts.get_height() // 2))

    return btn_x, btn_y_plus, btn_y_minus


async def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("PolarPrism - Heading Monitor")
    clock = pygame.time.Clock()

    try:
        font = pygame.font.SysFont("monospace", 20, bold=True)
    except Exception:
        font = pygame.font.Font(None, 22)
    try:
        font_sm = pygame.font.SysFont("monospace", 14)
    except Exception:
        font_sm = pygame.font.Font(None, 16)
    try:
        font_title = pygame.font.SysFont("monospace", 24, bold=True)
    except Exception:
        font_title = pygame.font.Font(None, 26)

    state = State()
    asyncio.ensure_future(fetch_vessel_name(state))
    asyncio.ensure_future(fetch_device_names(state))
    asyncio.ensure_future(fetch_multi_values(state))
    asyncio.ensure_future(ws_reader(state))
    asyncio.ensure_future(logger(state))
    asyncio.ensure_future(ws_writer(state))

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_PLUS or event.key == pygame.K_EQUALS:
                    if state.chart_zoom < MAX_TILE_ZOOM:
                        state.chart_zoom += 1
                elif event.key == pygame.K_MINUS:
                    if state.chart_zoom > MIN_TILE_ZOOM:
                        state.chart_zoom -= 1
                elif event.key == pygame.K_c:
                    lat = state.position.get("lat")
                    lon = state.position.get("lon")
                    if lat is not None and lon is not None:
                        state.chart_center_lat = lat
                        state.chart_center_lon = lon
                elif event.key == pygame.K_f:
                    state.emulation_active = not state.emulation_active
                    if not state.emulation_active:
                        state.fusion_heading = None
                elif event.key == pygame.K_d:
                    state.show_diagnostics = not state.show_diagnostics
                    if state.show_diagnostics:
                        asyncio.ensure_future(fetch_multi_values(state))
                elif event.key == pygame.K_RIGHTBRACKET:
                    state.heading_offset += 0.5
                elif event.key == pygame.K_LEFTBRACKET:
                    state.heading_offset -= 0.5
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                btn_x = CHART_X + CHART_W - ZOOM_BTN_MARGIN - ZOOM_BTN_SIZE
                btn_y_plus = CHART_Y + ZOOM_BTN_MARGIN
                btn_y_minus = btn_y_plus + ZOOM_BTN_SIZE + 4
                clicked_zoom_plus = (btn_x <= mx <= btn_x + ZOOM_BTN_SIZE and
                                     btn_y_plus <= my <= btn_y_plus + ZOOM_BTN_SIZE)
                clicked_zoom_minus = (btn_x <= mx <= btn_x + ZOOM_BTN_SIZE and
                                       btn_y_minus <= my <= btn_y_minus + ZOOM_BTN_SIZE)
                if event.button == 1 and clicked_zoom_plus:
                    if state.chart_zoom < MAX_TILE_ZOOM:
                        state.chart_zoom += 1
                elif event.button == 1 and clicked_zoom_minus:
                    if state.chart_zoom > MIN_TILE_ZOOM:
                        state.chart_zoom -= 1
                elif event.button == 1:
                    if mx >= CHART_X:
                        state.dragging = True
                        state.drag_start = (mx, my)
                elif event.button == 4:
                    if mx >= CHART_X:
                        chart_mx = mx - CHART_X - CHART_W // 2
                        chart_my = my - CHART_Y - CHART_H // 2
                        n = 2 ** state.chart_zoom
                        deg_per_px = 360.0 / (n * TILE_SIZE)
                        cos_lat = math.cos(math.radians(state.chart_center_lat))
                        state.chart_center_lon -= chart_mx * deg_per_px / cos_lat
                        state.chart_center_lat += chart_my * deg_per_px
                    if state.chart_zoom < MAX_TILE_ZOOM:
                        state.chart_zoom += 1
                elif event.button == 5:
                    if state.chart_zoom > MIN_TILE_ZOOM:
                        state.chart_zoom -= 1
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    state.dragging = False
            elif event.type == pygame.MOUSEMOTION:
                if state.dragging and state.drag_start:
                    mx, my = event.pos
                    sx, sy = state.drag_start
                    dx = mx - sx
                    dy = my - sy
                    n = 2 ** state.chart_zoom
                    deg_per_px = 360.0 / (n * TILE_SIZE)
                    cos_lat = math.cos(math.radians(state.chart_center_lat))
                    state.chart_center_lon -= dx * deg_per_px / cos_lat
                    state.chart_center_lat += dy * deg_per_px
                    if state.chart_center_lat > 85:
                        state.chart_center_lat = 85
                    elif state.chart_center_lat < -85:
                        state.chart_center_lat = -85
                    state.drag_start = (mx, my)

        screen.fill(BG_COLOR)

        ts = font_title.render("POLARPRISM", True, (60, 80, 120))
        screen.blit(ts, (COMPASS_CX - ts.get_width() // 2, 8))

        pygame.draw.line(screen, (40, 50, 70), (COMPASS_AREA_W, 0), (COMPASS_AREA_W, WINDOW_H), 2)

        try:
            draw_compass(screen, font, font_sm, state)
        except Exception as e:
            log_error(f"draw_compass: {e}")
        if state.show_diagnostics:
            try:
                draw_diagnostics(screen, font, font_sm, state)
            except Exception as e:
                log_error(f"draw_diagnostics: {e}")
        else:
            try:
                draw_legend(screen, font, font_sm, state)
            except Exception as e:
                log_error(f"draw_legend: {e}")
        try:
            draw_chart(screen, font, font_sm, state)
        except Exception as e:
            log_error(f"draw_chart: {e}")

        pygame.display.flip()
        clock.tick(FPS)
        await asyncio.sleep(0)

    pygame.quit()


def log_error(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    line = f"{ts} {msg}\n"
    try:
        with open(ERROR_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)
    except Exception as e:
        tb = traceback.format_exc()
        log_error(f"FATAL: {e}\n{tb}")
        try:
            pygame.quit()
        except Exception:
            pass
        sys.exit(1)