from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, ClassVar

UTC = timezone.utc

_KTS_TO_MS = 1.0 / 1.94384


def _parse_ts_to_float(ts_str: str) -> float:
    """Parse an ISO-ish timestamp string into a monotonic-like float."""
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _wall_from_ts(ts_str: str) -> str:
    """Extract HH:MM:SS from an ISO timestamp for display."""
    if "T" in ts_str:
        return ts_str.split("T", 1)[-1][:8]
    return str(ts_str)


class ReplaySession:
    SPEED_STEPS: ClassVar[list[int]] = [1, 2, 5, 10, 20]
    MAX_SAMPLE_DEPTH: ClassVar[int] = 3

    def __init__(self, log_path: str, *, polar_names_map: dict[str, Any] | None = None) -> None:
        self.log_path = log_path
        self._entries: list[dict[str, Any]] = []
        self._sample_idx = 0
        self._wall_start = ""
        self._wall_end = ""
        self._wall_current = ""
        self._start_ts = 0.0
        self._current_ts = 0.0
        self._speed_index = 2
        self._paused = False
        self._done = False
        self.polar_names_map = polar_names_map or {}
        self._log_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        self._load()

    def _load(self) -> None:
        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry is None:
                    continue
                self._entries.append(entry)
        if not self._entries:
            return
        first_ts = self._entries[0].get("ts", "")
        last_ts = self._entries[-1].get("ts", "")
        self._start_ts = _parse_ts_to_float(first_ts)
        self._current_ts = self._start_ts
        self._wall_start = _wall_from_ts(first_ts)
        self._wall_end = _wall_from_ts(last_ts)
        self._wall_current = self._wall_start

    @property
    def speed(self) -> float:
        return float(self.SPEED_STEPS[self._speed_index])

    @property
    def speed_label(self) -> str:
        return f"{self.SPEED_STEPS[self._speed_index]}x"

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def is_done(self) -> bool:
        return self._done

    @property
    def wall_start(self) -> str:
        return self._wall_start

    @property
    def wall_end(self) -> str:
        return self._wall_end

    @property
    def wall_current(self) -> str:
        return self._wall_current

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def progress_ratio(self) -> float:
        if not self._entries:
            return 0.0
        return min(1.0, self._sample_idx / len(self._entries))

    @property
    def polar_name(self) -> str:
        if self._entries and "polar_name" in self._entries[0]:
            return self._entries[0].get("polar_name", "")
        return ""

    @property
    def active_log_name(self) -> str:
        return os.path.basename(self.log_path)

    def seek_to(self, idx: int) -> None:
        if not self._entries:
            return
        idx = max(0, min(idx, len(self._entries) - 1))
        self._sample_idx = idx
        entry = self._entries[idx]
        ts_str = entry.get("ts", "")
        self._current_ts = _parse_ts_to_float(ts_str)
        self._wall_current = _wall_from_ts(ts_str)

    def reset(self) -> None:
        self._sample_idx = 0
        self._current_ts = self._start_ts
        self._wall_current = self._wall_start
        self._done = False
        self._paused = False

    def toggle_pause(self) -> None:
        self._paused = not self._paused

    def speed_up(self) -> None:
        if self._speed_index < len(self.SPEED_STEPS) - 1:
            self._speed_index += 1

    def speed_down(self) -> None:
        if self._speed_index > 0:
            self._speed_index -= 1

    def advance(self, state: Any, dt_ms: float) -> bool:
        """Apply pending replay entries up to target time. Returns False if done."""
        if self._done:
            return False
        if self._paused:
            return True
        if not self._entries:
            return False

        dt_s = dt_ms / 1000.0
        step = float(self.SPEED_STEPS[self._speed_index])
        target_ts = self._current_ts + (dt_s * step)
        processed = 0

        while self._sample_idx < len(self._entries):
            entry = self._entries[self._sample_idx]
            entry_ts = _parse_ts_to_float(entry.get("ts", ""))

            if entry_ts > target_ts:
                break
            if processed >= self.MAX_SAMPLE_DEPTH:
                break

            self._apply_entry(state, entry)
            self._sample_idx += 1
            processed += 1

        if self._sample_idx >= len(self._entries):
            self._done = True
            last = self._entries[-1]
            self._wall_current = _wall_from_ts(last.get("ts", ""))
        else:
            current = self._entries[min(self._sample_idx, len(self._entries) - 1)]
            ts = current.get("ts", "")
            self._wall_current = _wall_from_ts(ts)
            self._current_ts = self._current_ts + (dt_s * step)

        return True

    def _apply_entry(self, state: Any, entry: dict[str, Any]) -> None:
        """Apply a single sailing-log entry into the State object so pages can render it."""
        # Skip event entries (log_start, log_stop, sail_change, etc.)
        if entry.get("event") is not None:
            return

        # Position
        if entry.get("position") is not None and isinstance(entry["position"], dict):
            p = entry["position"]
            lat_val = p.get("lat")
            lon_val = p.get("lon")
            if lat_val is not None:
                state.position["lat"] = lat_val
            if lon_val is not None:
                state.position["lon"] = lon_val

        # headingTrue (degrees -> radians)
        ht_deg = entry.get("headingTrue")
        if ht_deg is not None:
            state.values["headingTrue"] = math.radians(ht_deg)
            state.sources["headingTrue"] = "replay"

        # cogTrue (degrees -> radians)
        cog_deg = entry.get("cogTrue")
        if cog_deg is not None:
            state.values["cogTrue"] = math.radians(cog_deg)
            state.sources["cogTrue"] = "replay"

        # Speeds (knots -> m/s)
        sog_kts = entry.get("sog")
        if sog_kts is not None:
            state.values["speedOverGround"] = sog_kts * _KTS_TO_MS
            state.sources["speedOverGround"] = "replay"

        stw_kts = entry.get("stw")
        if stw_kts is not None:
            state.values["speedThroughWater"] = stw_kts * _KTS_TO_MS
            state.sources["speedThroughWater"] = "replay"

        # Wind angles (degrees -> radians)
        awa_deg = entry.get("awa")
        if awa_deg is not None:
            state.values["windAngleApparent"] = math.radians(awa_deg)
            state.sources["windAngleApparent"] = "replay"

        twa_deg = entry.get("twa")
        if twa_deg is not None:
            state.values["windAngleTrue"] = math.radians(twa_deg)

        # Wind speed (knots -> m/s)
        aws_kts = entry.get("aws")
        if aws_kts is not None:
            state.values["windSpeedApparent"] = aws_kts * _KTS_TO_MS
            state.sources["windSpeedApparent"] = "replay"

        tws_kts = entry.get("tws")
        if tws_kts is not None:
            state.values["windSpeedTrue"] = tws_kts * _KTS_TO_MS

        # Non-numeric values (use current entry values)
        ss = entry.get("sailing_state")
        if ss is not None:
            state.sailing_state = ss

        as_val = entry.get("active_sails")
        if as_val is not None:
            state.active_sails = list(as_val)

        pn = entry.get("polar_name")
        if pn is not None and pn:
            state.polar_active = pn

        # Timestamp metadata
        ts_str = entry.get("ts", "")
        state.last_log_time = _parse_ts_to_float(ts_str)

        # NMEA log entry for diagnostics display
        wall = _wall_from_ts(ts_str)
        state.nmea_log.append(f"replay {wall}")
        state.connected = True

        # Feed low-pass filters for COG/SOG so pages see filtered values
        # during replay too. Replay emits at ~1 Hz (PERF_LOG_INTERVAL),
        # matching the filter's sample_hz default.
        fm = getattr(state, "filter_manager", None)
        if fm is not None:
            for sig in ("cogTrue", "speedOverGround"):
                v = state.values.get(sig)
                if v is not None and isinstance(v, (int, float)):
                    fm.update(sig, float(v), dt=1.0)
