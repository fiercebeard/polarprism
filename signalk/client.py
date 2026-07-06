import asyncio
import json
import logging
import math
import os
import urllib.request
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import aiofiles
import websockets

from boatpolars.coverage import bin_sample
from boatpolars.parser import auto_select_tws_index, compute_true_wind, lookup_speed

from .models import (
    MS_TO_KNOTS,
    derive_true_heading,
    rad_to_deg,
    rad_to_deg_signed,
    update_from_delta,
)

LOG_INTERVAL = 1.0

# Sent on every HTTP request. Tile/data servers (and OSM-family policies)
# reject the bare ``Python-urllib`` default, so identify ourselves.
USER_AGENT = "PolarPrism/0.1 (sailing navigation instrument)"

_log = logging.getLogger("polarprism")


def _http_get_json_sync(url: str, timeout: float = 5.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


async def _http_get_json(url: str, timeout: float = 5.0) -> Any:
    """Fetch + parse JSON without blocking the event loop.

    The Signal K REST endpoints are polled from the same asyncio loop that
    drives the pygame render; a synchronous ``urlopen`` here would freeze the
    UI for up to ``timeout`` seconds on a slow/unreachable server. Run it on a
    worker thread instead.
    """
    return await asyncio.to_thread(_http_get_json_sync, url, timeout)


_log_file: str = ""
_perf_log_dir: str = ""


async def ws_reader(state, ws_url: str):
    while True:
        try:
            async with websockets.connect(ws_url) as ws:
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
                        {"path": "navigation.courseGreatCircle.bearingTrue"},
                        {"path": "navigation.course.nextPoint.bearingTrue"},
                        {"path": "navigation.course.nextPoint.bearingMagnetic"},
                        {"path": "navigation.course.nextPoint.distance"},
                        {"path": "navigation.course.previousPoint.bearingTrue"},
                        {"path": "navigation.courseRhumbline.bearingTrue"},
                        {"path": "navigation.course.calcValues.bearingTrue"},
                        {"path": "navigation.course.calcValues.bearingMagnetic"},
                        {"path": "navigation.course.calcValues.velocityMadeGood"},
                        {"path": "navigation.course.calcValues.crossTrackError"},
                        {"path": "navigation.course.calcValues.distance"},
                        {"path": "navigation.courseGreatCircle.nextPoint.bearingTrue"},
                        {"path": "navigation.courseGreatCircle.nextPoint.distance"},
                        {"path": "navigation.courseGreatCircle.nextPoint.velocityMadeGood"},
                        {"path": "navigation.courseGreatCircle.crossTrackError"},
                        {"path": "navigation.courseGreatCircle.bearingTrackTrue"},
                        {"path": "name"},
                    ],
                }
                await ws.send(json.dumps(sub))
                async for msg in ws:
                    text = msg.decode() if isinstance(msg, bytes) else msg
                    update_from_delta(state, text)
        except (ConnectionRefusedError, OSError, websockets.InvalidURI):
            _log.debug("ws_reader: connection refused/invalid URL: %s", ws_url)
        except Exception as e:
            _log.error("ws_reader: %s", e, exc_info=True)
        state.connected = False
        await _sleep(2)


asyncio_sleep: Callable[[float], Awaitable[None]] | None = None


def set_asyncio_sleep(fn: Callable[[float], Awaitable[None]]) -> None:
    global asyncio_sleep
    asyncio_sleep = fn


def set_log_paths(log_file: str, perf_log_dir: str) -> None:
    global _log_file, _perf_log_dir
    _log_file = log_file
    _perf_log_dir = perf_log_dir


async def _sleep(delay: float) -> None:
    """Await the configured asyncio.sleep; set via set_asyncio_sleep in main."""
    if asyncio_sleep is None:
        return
    await asyncio_sleep(delay)


async def fetch_vessel_name(state, rest_url: str):
    try:
        data = await _http_get_json(f"{rest_url}/vessels/self")
        name = data.get("name")
        if name:
            state.vessel_name = name
    except Exception:
        _log.debug("fetch_vessel_name: failed", exc_info=True)


async def fetch_device_names(state, rest_url: str):
    try:
        data = await _http_get_json(f"{rest_url}/sources")
        for source_key, source_data in data.items():
            if not isinstance(source_data, dict):
                continue
            for src_id, src_data in source_data.items():
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
                full_src = f"{source_key}.{src_id}"
                state.device_names[full_src] = label
    except Exception:
        _log.debug("fetch_device_names: failed", exc_info=True)


async def fetch_multi_values(state, rest_url: str):
    while True:
        try:
            data = await _http_get_json(f"{rest_url}/vessels/self")
            nav = data.get("navigation", {})
            for key in [
                "magneticVariation",
                "headingMagnetic",
                "courseOverGroundTrue",
                "headingTrue",
                "speedOverGround",
                "speedThroughWater",
                "rateOfTurn",
                "attitude",
            ]:
                val = nav.get(key, {})
                if isinstance(val, dict) and "values" in val:
                    state.multi_values[key] = {}
                    for src, sv in val["values"].items():
                        sv_val = sv.get("value")
                        if isinstance(sv_val, dict) or sv_val is not None:
                            state.multi_values[key][src] = sv_val
        except Exception:
            _log.debug("fetch_multi_values: failed", exc_info=True)
        await _sleep(5)


async def logger(state):
    while True:
        await _sleep(LOG_INTERVAL)
        now = datetime.now(timezone.utc)
        ht_val = derive_true_heading(state)
        entry = {
            "ts": now.isoformat(),
            "vessel": state.vessel_name or None,
        }
        for key in [
            "headingMagnetic",
            "cogTrue",
            "apTargetMagnetic",
            "magneticVariation",
            "rateOfTurn",
        ]:
            v = state.values.get(key)
            if v is not None:
                if key == "magneticVariation":
                    deg = rad_to_deg_signed(v)
                elif key == "rateOfTurn":
                    deg = rad_to_deg_signed(v) * 1.0
                else:
                    deg = rad_to_deg(v)
                entry[key] = {
                    "value": round(v, 6),
                    "deg": round(deg, 1),
                    "source": state.sources.get(key, ""),
                }
            else:
                entry[key] = None
        if ht_val is not None:
            entry["headingTrue"] = {
                "value": round(ht_val, 6),
                "deg": round(rad_to_deg(ht_val), 1),
                "source": "derived",
            }
        else:
            entry["headingTrue"] = None
        pos = state.position
        if pos["lat"] is not None or pos["lon"] is not None:
            entry["position"] = {"lat": pos["lat"], "lon": pos["lon"]}
        try:
            async with aiofiles.open(_log_file, mode="a") as f:
                await f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError:
            _log.debug("heading log write failed: %s", _log_file)
        state.last_log_time = now.timestamp()


def should_write_sailing_log(state) -> bool:
    """Whether the sailing performance log should record right now.

    Replay feeds logged values back into ``state`` (including
    ``sailing_state == "sailing"`` and ``sailing_log_active`` for the Polar
    Builder live feed), which satisfies the normal recording condition —
    without the replay guard, playing a log re-records it into a brand-new
    ``sailing_*.jsonl`` file.
    """
    if getattr(state, "replay_active", False):
        return False
    return bool(state.sailing_log_active) and state.sailing_state == "sailing"


async def performance_logger(state):
    os.makedirs(_perf_log_dir, exist_ok=True)
    PERF_LOG_INTERVAL = 1.0

    while True:
        await _sleep(PERF_LOG_INTERVAL)

        if not should_write_sailing_log(state):
            continue

        now = datetime.now(timezone.utc)
        ht_val = derive_true_heading(state)
        awa_rad = state.values.get("windAngleApparent")
        aws_ms = state.values.get("windSpeedApparent")
        stw_ms = state.values.get("speedThroughWater")
        sog_ms = state.values.get("speedOverGround")
        cog_rad = state.values.get("cogTrue")
        twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)
        twa_deg = math.degrees(twa_rad) if twa_rad is not None else None
        tws_kts = tws_ms * MS_TO_KNOTS if tws_ms is not None else None
        awa_deg = math.degrees(awa_rad) if awa_rad is not None else None
        aws_kts = aws_ms * MS_TO_KNOTS if aws_ms is not None else None
        stw_kts = stw_ms * MS_TO_KNOTS if stw_ms is not None else None
        sog_kts = sog_ms * MS_TO_KNOTS if sog_ms is not None else None

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
            state.performance_log_file = os.path.join(_perf_log_dir, fname)

        try:
            async with aiofiles.open(state.performance_log_file, mode="a") as f:
                await f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError:
            _log.debug("sailing log write failed: %s", state.performance_log_file)

        state.log_sample_count += 1
        if polar_perf is not None:
            state.log_perf_sum += polar_perf


async def write_log_event(state, event_type, data=None):
    # The replay guard also protects a leftover performance_log_file from an
    # earlier real recording — replay events must never append to it.
    if getattr(state, "replay_active", False) or not state.sailing_log_active:
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
            _log.debug("sailing log event write failed: %s", state.performance_log_file)


PERF_SAMPLE_INTERVAL = 10.0


async def perf_sampler(state):
    while True:
        await _sleep(PERF_SAMPLE_INTERVAL)
        awa_rad = state.values.get("windAngleApparent")
        aws_ms = state.values.get("windSpeedApparent")
        stw_ms = state.values.get("speedThroughWater")
        twa_rad, tws_ms = compute_true_wind(awa_rad, aws_ms, stw_ms)
        if twa_rad is None or tws_ms is None or stw_ms is None:
            continue
        if state.polar_active not in state.polar_data:
            continue
        polar = state.polar_data[state.polar_active]
        twa_deg = abs(math.degrees(twa_rad))
        tws_kts = tws_ms * MS_TO_KNOTS
        stw_kts = stw_ms * MS_TO_KNOTS
        target = lookup_speed(polar, twa_deg, tws_kts)
        if target is None or target <= 0:
            continue
        pct = stw_kts / target * 100.0
        now = datetime.now(timezone.utc).timestamp()
        state.perf_samples.append((now, pct))
        cutoff = now - max(state.PERF_WINDOWS) - 60
        state.perf_samples = [(t, p) for t, p in state.perf_samples if t > cutoff]
        state.perf_averages = {}
        for window in state.PERF_WINDOWS:
            window_samples = [p for t, p in state.perf_samples if t > now - window]
            if window_samples:
                state.perf_averages[window] = sum(window_samples) / len(window_samples)
            else:
                state.perf_averages[window] = None
        # Periodically re-select the closest polar TWS band to the current
        # wind speed. Done here (every PERF_SAMPLE_INTERVAL) rather than in
        # the render path so drawing stays free of state mutation.
        idx = auto_select_tws_index(polar, tws_kts)
        if idx is not None:
            state.polar_tws_index = idx


BUILDER_SAMPLE_INTERVAL = 1.0


async def polar_builder_sampler(state):
    """Live-feed accumulator for the Polar Builder page.

    One Hz: when a sailing log is recording and the boat is sailing, bins the
    current apparent-wind sample and appends it to ``state.polar_builder_live_buffer``.
    The live buffer auto-feeds the builder group whose ``polar`` matches
    ``state.polar_active`` (see pages/polar_builder.py). Cleared when a new
    sailing-log file is opened (detected via ``state.performance_log_file``).
    """
    while True:
        await _sleep(BUILDER_SAMPLE_INTERVAL)
        if not state.sailing_log_active or state.sailing_state != "sailing":
            continue
        # Detect new-session reset
        if state.performance_log_file != state.polar_builder_live_session:
            state.polar_builder_live_session = state.performance_log_file
            state.polar_builder_live_buffer = []
        awa_rad = state.values.get("windAngleApparent")
        aws_ms = state.values.get("windSpeedApparent")
        stw_ms = state.values.get("speedThroughWater")
        if awa_rad is None or aws_ms is None or stw_ms is None:
            continue
        awa_norm = awa_rad
        awa_deg = math.degrees(awa_rad)
        if awa_deg > 180:
            awa_norm = math.radians(awa_deg - 360)
        binned = bin_sample(awa_norm, aws_ms, stw_ms)
        if binned is None:
            continue
        state.polar_builder_live_buffer.append(binned)
