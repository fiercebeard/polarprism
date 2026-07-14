"""Low-pass filtering for GPS-derived signals (COG, SOG).

The GPS antenna on a typical sailboat is mounted on the mast, so COG and
SOG pick up a mast-sway/roll motion artifact at the wave frequency
(~0.25 Hz, 4 s period). A one-pole IIR low-pass filter at ~0.05 Hz
(20 s period) cleanly separates the wave-motion band from real
ground-track change, while keeping group delay (~3 s) well under the
20 s decision horizon.

This module provides:
  - ``OnePoleFilter``: linear-signal EMA with time-aware alpha.
  - ``AngularOnePoleFilter``: circular-aware EMA for COG (wraps at 2*pi).
  - ``FilterConfig`` / ``FilterManager``: live filter state keyed by
    signal name, driven by the [filter] config section.
  - ``analyze_log``: spectral analysis of a sailing log file that
    suggests filter cutoffs for COG/SOG.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

DEFAULT_CUTOFF_HZ = 0.05
DEFAULT_SAMPLE_HZ = 1.0

# Signals that support filtering. Keys match state.values keys.
FILTERABLE_LINEAR = ["speedOverGround"]
FILTERABLE_ANGULAR = ["cogTrue"]
FILTERABLE_SIGNALS = FILTERABLE_LINEAR + FILTERABLE_ANGULAR


def _cutoff_to_alpha(cutoff_hz: float, sample_hz: float) -> float:
    """One-pole IIR coefficient for the given cutoff and sample rate.

    tau = 1 / (2*pi*fc); alpha = 1 - exp(-1/(tau*fs)).
    """
    if cutoff_hz <= 0 or sample_hz <= 0:
        return 1.0
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 - math.exp(-1.0 / (tau * sample_hz))


class OnePoleFilter:
    """Exponential moving average for linear (non-circular) signals.

    Time-aware: pass the elapsed time since the previous sample so the
    filter stays correct under variable sample rates and replay gaps.
    """

    def __init__(self, cutoff_hz: float, sample_hz: float = DEFAULT_SAMPLE_HZ) -> None:
        self.cutoff_hz = cutoff_hz
        self.sample_hz = sample_hz
        self.value: float | None = None
        self._alpha = _cutoff_to_alpha(cutoff_hz, sample_hz)

    def update(self, sample: float, dt: float = 1.0) -> float:
        if self.value is None:
            self.value = sample
            return self.value
        alpha = self._alpha_for_dt(dt)
        self.value += alpha * (sample - self.value)
        return self.value

    def _alpha_for_dt(self, dt: float) -> float:
        if dt <= 0 or abs(dt - 1.0 / self.sample_hz) < 1e-6:
            return self._alpha
        tau = 1.0 / (2.0 * math.pi * self.cutoff_hz)
        return 1.0 - math.exp(-dt / tau)

    def reset(self) -> None:
        self.value = None

    def set_cutoff(self, cutoff_hz: float) -> None:
        self.cutoff_hz = cutoff_hz
        self._alpha = _cutoff_to_alpha(cutoff_hz, self.sample_hz)


class AngularOnePoleFilter:
    """EMA for circular angles (radians), wrapping at 2*pi.

    Uses angle_diff for the innovation so a wrap-around at 0/2*pi does
    not corrupt the filter. Output is normalized to [0, 2*pi).
    """

    def __init__(self, cutoff_hz: float, sample_hz: float = DEFAULT_SAMPLE_HZ) -> None:
        self.cutoff_hz = cutoff_hz
        self.sample_hz = sample_hz
        self.value: float | None = None
        self._alpha = _cutoff_to_alpha(cutoff_hz, sample_hz)

    def update(self, sample: float, dt: float = 1.0) -> float:
        if self.value is None:
            self.value = sample % (2.0 * math.pi)
            return self.value
        alpha = self._alpha_for_dt(dt)
        diff = (sample - self.value + math.pi) % (2.0 * math.pi) - math.pi
        self.value = (self.value + alpha * diff) % (2.0 * math.pi)
        return self.value

    def _alpha_for_dt(self, dt: float) -> float:
        if dt <= 0 or abs(dt - 1.0 / self.sample_hz) < 1e-6:
            return self._alpha
        tau = 1.0 / (2.0 * math.pi * self.cutoff_hz)
        return 1.0 - math.exp(-dt / tau)

    def reset(self) -> None:
        self.value = None

    def set_cutoff(self, cutoff_hz: float) -> None:
        self.cutoff_hz = cutoff_hz
        self._alpha = _cutoff_to_alpha(cutoff_hz, self.sample_hz)


@dataclass
class FilterConfig:
    """Per-signal filter settings, loaded from the [filter] config section."""

    enabled: bool = False
    cutoffs: dict[str, float] = field(default_factory=dict)

    def cutoff_for(self, signal: str) -> float:
        return self.cutoffs.get(signal, DEFAULT_CUTOFF_HZ)


class FilterManager:
    """Live filter state for filterable signals.

    Holds one filter per signal, updated as new samples arrive. Callers
    read filtered values via ``get()`` (which falls back to the raw
    value when filtering is disabled or the filter has no output yet).
    """

    def __init__(self, config: FilterConfig) -> None:
        self.config = config
        self._filters: dict[str, OnePoleFilter | AngularOnePoleFilter] = {}
        self._build_filters()

    def _build_filters(self) -> None:
        for sig in FILTERABLE_LINEAR:
            self._filters[sig] = OnePoleFilter(self.config.cutoff_for(sig))
        for sig in FILTERABLE_ANGULAR:
            self._filters[sig] = AngularOnePoleFilter(self.config.cutoff_for(sig))

    def update(self, signal: str, sample: float, dt: float = 1.0) -> None:
        f = self._filters.get(signal)
        if f is not None:
            f.update(sample, dt)

    def get(self, signal: str, raw: float | None) -> float | None:
        """Return the filtered value, or fall back to raw.

        Filtering is skipped when disabled in config or the filter has
        not yet produced output (first sample).
        """
        if not self.config.enabled:
            return raw
        f = self._filters.get(signal)
        if f is None or f.value is None:
            return raw
        return f.value

    def reset(self) -> None:
        for f in self._filters.values():
            f.reset()

    def reconfigure(self, config: FilterConfig) -> None:
        self.config = config
        for sig, f in self._filters.items():
            f.set_cutoff(config.cutoff_for(sig))
            f.reset()


# --- Spectral analysis for filter suggestions ------------------------------


@dataclass
class SignalSuggestion:
    """One suggested filter for a signal, from analyzing a sailing log."""

    signal: str
    cutoff_hz: float
    artifact_hz: float | None
    artifact_power_db: float | None
    baseline_power_db: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "cutoff_hz": round(self.cutoff_hz, 4),
            "artifact_hz": round(self.artifact_hz, 4) if self.artifact_hz else None,
            "artifact_power_db": round(self.artifact_power_db, 2)
            if self.artifact_power_db is not None
            else None,
            "baseline_power_db": round(self.baseline_power_db, 2)
            if self.baseline_power_db is not None
            else None,
            "reason": self.reason,
        }


def _load_sailing_log_entries(path: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event") is not None:
                continue
            entries.append(entry)
    return entries


def _extract_series(entries: list[dict[str, Any]], key: str) -> tuple[list[float], list[float]]:
    """Return (timestamps_seconds, values) for a sailing-log field.

    Timestamps are relative seconds from the first entry. Skips entries
    where the field is None.
    """
    from datetime import datetime, timezone

    times: list[float] = []
    values: list[float] = []
    if not entries:
        return times, values
    first_ts = 0.0
    for i, e in enumerate(entries):
        v = e.get(key)
        if v is None:
            continue
        ts_str = e.get("ts", "")
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            t = dt.timestamp()
        except (ValueError, TypeError):
            continue
        if i == 0 or not times:
            first_ts = t
        times.append(t - first_ts)
        values.append(float(v))
    return times, values


def _power_spectrum(values: list[float], sample_hz: float) -> tuple[list[float], list[float]]:
    """Return (frequencies, magnitudes_db) via numpy FFT.

    Removes the DC component and applies a Hann window.
    """
    import numpy as np

    n = len(values)
    if n < 8:
        return [], []
    arr = np.array(values, dtype=float)
    arr = arr - arr.mean()
    window = np.hanning(n)
    arr = arr * window
    spectrum = np.fft.rfft(arr)
    mag = np.abs(spectrum)
    # Normalize by window sum for amplitude, then to power (dB)
    scale = np.sum(window) / 2.0
    if scale > 0:
        mag = mag / scale
    power = mag**2
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_hz)
    # Avoid log(0): floor tiny values
    eps = 1e-12
    power_db = 10.0 * np.log10(power + eps)
    return freqs.tolist(), power_db.tolist()


def _unwrap_deg(values: list[float]) -> list[float]:
    """Unwrap a degree-valued circular series for spectral analysis."""
    unwrapped: list[float] = []
    prev: float | None = None
    for v in values:
        if prev is None:
            unwrapped.append(v)
        else:
            d = (v - prev + 180.0) % 360.0 - 180.0
            unwrapped.append(unwrapped[-1] + d)
        prev = v
    return unwrapped


def _estimate_sample_hz(times: list[float]) -> float:
    if len(times) < 2:
        return DEFAULT_SAMPLE_HZ
    span = times[-1] - times[0]
    if span <= 0:
        return DEFAULT_SAMPLE_HZ
    return (len(times) - 1) / span


def _analyze_signal(
    entries: list[dict[str, Any]],
    log_key: str,
    signal_name: str,
    angular: bool,
    min_duration_s: float = 120.0,
) -> SignalSuggestion | None:
    """Analyze one signal from a sailing log and suggest a cutoff.

    Finds the dominant spectral peak above 0.02 Hz. If it's strong
    relative to the baseline (>= 6 dB), recommends a cutoff at
    half the artifact frequency (or DEFAULT_CUTOFF_HZ if lower).
    """
    _times, values = _extract_series(entries, log_key)
    if len(values) < 64:
        return None
    times_span = _times[-1] - _times[0] if len(_times) > 1 else 0.0
    if times_span < min_duration_s:
        return None
    sample_hz = _estimate_sample_hz(_times)
    if sample_hz <= 0:
        return None
    if angular:
        values = _unwrap_deg(values)
    freqs, power_db = _power_spectrum(values, sample_hz)
    if not freqs:
        return None
    # Baseline: median power above 0.02 Hz (excluding DC/near-DC)
    band_mask = [i for i, f in enumerate(freqs) if f > 0.02]
    if not band_mask:
        return None
    band_powers = [power_db[i] for i in band_mask]
    band_powers_sorted = sorted(band_powers)
    baseline = band_powers_sorted[len(band_powers_sorted) // 2]
    # Dominant peak
    peak_idx = max(band_mask, key=lambda i: power_db[i])
    peak_freq = freqs[peak_idx]
    peak_power = power_db[peak_idx]
    # Only suggest if the peak is meaningfully above the baseline
    if peak_power - baseline < 6.0:
        reason = (
            f"No strong artifact found; {log_key} spectrum is flat. Default 0.05 Hz cutoff is safe."
        )
        return SignalSuggestion(
            signal=signal_name,
            cutoff_hz=DEFAULT_CUTOFF_HZ,
            artifact_hz=peak_freq,
            artifact_power_db=peak_power,
            baseline_power_db=baseline,
            reason=reason,
        )
    # Suggested cutoff: half the artifact frequency, clamped to [0.02, 0.1]
    suggested = max(0.02, min(0.1, peak_freq / 2.0))
    reason = (
        f"{log_key} shows a {peak_freq:.3f} Hz artifact "
        f"({peak_power - baseline:.1f} dB above baseline). "
        f"Low-pass at {suggested:.3f} Hz suppresses it."
    )
    return SignalSuggestion(
        signal=signal_name,
        cutoff_hz=suggested,
        artifact_hz=peak_freq,
        artifact_power_db=peak_power,
        baseline_power_db=baseline,
        reason=reason,
    )


def analyze_log(path: str) -> list[SignalSuggestion]:
    """Analyze a sailing-log JSONL file and return filter suggestions.

    Examines COG and SOG for spectral artifacts (e.g. mast sway) and
    recommends a low-pass cutoff for each. Returns a list (one per
    analyzable signal) sorted in FILTERABLE_SIGNALS order.
    """
    entries = _load_sailing_log_entries(path)
    if not entries:
        return []
    suggestions: list[SignalSuggestion] = []
    # Sailing log stores COG/SOG in degrees/knots under cogTrue/sog.
    sig_specs = [
        ("cogTrue", "cogTrue", True),
        ("sog", "speedOverGround", False),
    ]
    for log_key, signal_name, angular in sig_specs:
        s = _analyze_signal(entries, log_key, signal_name, angular)
        if s is not None:
            suggestions.append(s)
    return suggestions
