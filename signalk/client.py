import aiofiles
import json
import os
from datetime import datetime, timezone

from .models import State, SK_WS_URL, PATH_MAP, update_from_delta, compute_fusion_heading, rad_to_deg, rad_to_deg_signed, derive_true_heading
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