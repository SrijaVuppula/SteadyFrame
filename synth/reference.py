"""Independent 1-D reference implementation of the flash rules, used to write ground truth.

This deliberately does *not* import the analyzer's transition machine. It is a plain scalar
loop over an ideal signal (the luminance or red metric of the flashing region over time),
plus the analytic area condition. Agreement between this and the video analyzer is what
`eval/detection.py` measures.
"""

from __future__ import annotations

from dataclasses import dataclass

from steadyframe.profiles import Profile


@dataclass
class RefResult:
    transition_times: list[float]
    fail_frames: list[bool]  # per sample: > max flashes in the trailing window
    warn_frames: list[bool]  # per sample: exactly max flashes in the trailing window


def transitions(
    values: list[float], flags: list[bool], times: list[float], delta: float, eps: float
) -> list[float]:
    """Times at which a transition completes (accumulated swing >= delta, either extremum flagged)."""
    out: list[float] = []
    if not values:
        return out
    direction = 0
    start_v, start_f = values[0], flags[0]
    run_v, run_f = values[0], flags[0]
    counted = False
    for v, f, t in zip(values[1:], flags[1:], times[1:], strict=True):
        d = v - run_v
        if (direction <= 0 and d > eps) or (direction >= 0 and d < -eps):
            new_dir = 1 if d > 0 else -1
            if direction != new_dir:
                start_v, start_f = run_v, run_f
                run_v, run_f = v, f
                counted = False
                direction = new_dir
        if (direction == 1 and v > run_v) or (direction == -1 and v < run_v):
            run_v, run_f = v, f
        if not counted and direction != 0 and abs(run_v - start_v) >= delta and (start_f or run_f):
            counted = True
            out.append(t)
    return out


def window_counts(
    trans_times: list[float], sample_times: list[float], window_s: float
) -> list[int]:
    counts = []
    j0 = 0
    for t in sample_times:
        # transitions in (t - window, t]
        # 1e-6 s tolerance: frame times are quantised and t - 1.0 must exclude the edge exactly one window ago
        while j0 < len(trans_times) and trans_times[j0] <= t - window_s + 1e-6:
            j0 += 1
        j1 = j0
        while j1 < len(trans_times) and trans_times[j1] <= t + 1e-9:
            j1 += 1
        counts.append(j1 - j0)
    return counts


def region_window_fraction(region: dict, profile: Profile) -> float:
    """Largest fraction of a 10-degree window (or of the screen) the region can cover."""
    w, h = region["w"], region["h"]
    if profile.area_mode == "screen":
        return w * h
    ww, wh = profile.window_frac_w, profile.window_frac_h
    return (min(w, ww) * min(h, wh)) / (ww * wh)


def evaluate(
    values: list[float],
    flags: list[bool],
    times: list[float],
    area_fraction: float,
    profile: Profile,
    *,
    red: bool = False,
) -> RefResult:
    delta = profile.red_delta if red else profile.luminance_delta
    eps = profile.red_reversal_eps if red else profile.reversal_eps
    tt = transitions(values, flags, times, delta, eps)
    counts = window_counts(tt, times, profile.window_s)
    limit = profile.max_transitions_per_window
    area_ok = area_fraction > profile.area_fraction
    fail = [c > limit and area_ok for c in counts]
    warn = [profile.conservative and c == limit and area_ok for c in counts]
    return RefResult(tt, fail, warn)


def per_second(times: list[float], fail: list[bool], warn: list[bool]) -> list[str]:
    if not times:
        return []
    n = int(times[-1]) + 1
    out = ["pass"] * n
    for t, f, w in zip(times, fail, warn, strict=True):
        s = int(t)
        if f:
            out[s] = "fail"
        elif w and out[s] == "pass":
            out[s] = "warn"
    return out
