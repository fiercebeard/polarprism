import aiofiles
import json
import math
import os
from datetime import datetime, timezone

from .models import State, SK_WS_URL, PATH_MAP, update_from_delta, compute_fusion_heading, rad_to_deg, rad_to_deg_signed, derive_true_heading
from polars.parser import lookup_speed, compute_true_wind, lookup_recommended_sail
import websockets

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "heading_log.jsonl")
ERROR_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "error.log")
LOG_INTERVAL = 1.0


def log_error(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    line = f"{ts} {msg}\n"
    try:
        with open(ERROR_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


async def ws_reader(state):
    import urllib.request
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
        await asyncio_sleep(2)


asyncio_sleep = None


def set_asyncio_sleep(fn):
    global asyncio_sleep
    asyncio_sleep = fn


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
        await asyncio_sleep(5)


async def logger(state):
    while True:
        await asyncio_sleep(LOG_INTERVAL)
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


async def performance_logger(state):
    PERF_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sailing_logs")
    os.makedirs(PERF_LOG_DIR, exist_ok=True)
    PERF_LOG_INTERVAL = 1.0

    while True:
        await asyncio_sleep(PERF_LOG_INTERVAL)

        if not state.sailing_log_active or state.sailing_state != "sailing":
            continue

        now = datetime.now(timezone.utc)
        ht_val = derive_true_heading(state)
        awa_rad = state.values.get("windAngleApparent")
        aws_ms = state.values.get("windSpeedApparent")
        stw_ms = state.values.get("speedThroughWater")
        sog_ms = state.values.get("speedOverGround")
        cog_rad = state.values.get("cogTrue")
        hm_rad = state.values.get("headingMagnetic")
        mv_rad = state.values.get("magneticVariation")
        rot_rad = state.values.get("rateOfTurn")

        twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)
        twa_deg = math.degrees(twa_rad) if twa_rad is not None else None
        tws_kts = tws_ms * 1.94384 if tws_ms is not None else None
        awa_deg = math.degrees(awa_rad) if awa_rad is not None else None
        aws_kts = aws_ms * 1.94384 if aws_ms is not None else None
        stw_kts = stw_ms * 1.94384 if stw_ms is not None else None
        sog_kts = sog_ms * 1.94384 if sog_ms is not None else None

        ht_deg = rad_to_deg(ht_val) if ht_val is not None else None
        cog_deg = rad_to_deg(cog_rad) if cog_rad is not None else None

        twd_deg = None
        if ht_deg is not None and twa_deg is not None:
            twd_deg = (ht_deg + twa_deg) % 360

        polar_target = None
        polar_perf = None
        if twa_deg is not None and tws_kts is not None and state.polar_active in state.polar_data:
            polar = state.polar_data[state.polar_active]
            polar_target = lookup_speed(polar, abs(twa_deg), tws_kts)
            if polar_target is not None and polar_target > 0 and stw_kts is not None:
                polar_perf = stw_kts / polar_target * 100.0

        entry = {
            "ts": now.isoformat(),
            "position": {"lat": state.position.get("lat"), "lon": state.position.get("lon")},
            "headingTrue": ht_deg,
            "cogTrue": cog_deg,
            "sog": round(sog_kts, 2) if sog_kts is not None else None,
            "stw": round(stw_kts, 2) if stw_kts is not None else None,
            "twa": round(twa_deg, 1) if twa_deg is not None else None,
            "tws": round(tws_kts, 1) if tws_kts is not None else None,
            "twd": round(twd_deg, 1) if twd_deg is not None else None,
            "awa": round(awa_deg, 1) if awa_deg is not None else None,
            "aws": round(aws_kts, 1) if aws_kts is not None else None,
            "sailing_state": state.sailing_state,
            "active_sails": list(state.active_sails),
            "polar_name": state.polar_active,
            "polar_target_speed": round(polar_target, 2) if polar_target is not None else None,
            "polar_performance_pct": round(polar_perf, 1) if polar_perf is not None else None,
        }

        if state.performance_log_file is None:
            fname = now.strftime("sailing_%Y%m%d_%H%M%S.jsonl")
            state.performance_log_file = os.path.join(PERF_LOG_DIR, fname)

        try:
            async with aiofiles.open(state.performance_log_file, mode="a") as f:
                await f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError:
            pass

        state.log_sample_count += 1
        if polar_perf is not None:
            state.log_perf_sum += polar_perf


async def write_log_event(state, event_type, data=None):
    if not state.sailing_log_active:
        return
    now = datetime.now(timezone.utc)
    entry = {"ts": now.isoformat(), "event": event_type}
    if data:
        entry.update(data)
    if state.performance_log_file:
        try:
            async with aiofiles.open(state.performance_log_file, mode="a") as f:
                await f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError:
            pass


async def ws_writer(state):
    while True:
        if not state.emulation_active:
            await asyncio_sleep(0.5)
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
        await asyncio_sleep(1.0)