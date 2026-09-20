"""Streaming hazard analyzer.

    an = FlashAnalyzer(profile, width, height, fps)
    for idx, t, frame in reader: an.push(frame, t)
    result = an.finish()          # dict per schema.ANALYSIS_SCHEMA

Per frame: relative luminance and red metric maps (cv2.LUT + cv2.transform), INTER_AREA
downsample to the analysis grid, one TransitionTracker per hazard type, trailing-window
transition counts per cell, area condition via cv2.boxFilter, then a frame verdict. Frames
with a hazard are grouped into segments; regions come from cv2.connectedComponentsWithStats
on the accumulated flashing mask of each segment.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import __version__, opencv_build_summary
from .area import AreaChecker
from .flash import TransitionTracker, WindowCounter
from .io.video import VideoMeta, open_video
from .luminance import downsample, relative_luminance
from .pattern import PatternDetector
from .profiles import Profile, get_profile
from .redflash import RedTracker
from .schema import SCHEMA_VERSION

HAZARD_TYPES = ("general", "red")
GAP_TOLERANCE_S = 0.5


@dataclass
class _OpenSegment:
    type: str
    start_idx: int
    start_t: float
    end_idx: int
    end_t: float
    verdict: str
    mask: np.ndarray
    peak_rate: float = 0.0
    max_area: float = 0.0
    max_delta: float = 0.0
    frames_since_hit: int = 0


@dataclass
class _Frame:
    idx: int
    t: float
    mean_L: float
    rate: dict = field(default_factory=dict)  # type -> max cell flash rate (Hz)
    area: dict = field(default_factory=dict)  # type -> max window fraction
    verdict: dict = field(default_factory=dict)  # type -> pass/warn/fail


def severity(peak_rate_hz: float, max_area: float, max_delta: float, limit_hz: float) -> float:
    r = min(1.0, max(0.0, (peak_rate_hz - limit_hz) / 7.0))
    a = min(1.0, max(0.0, (max_area - 0.25) / 0.75))
    d = min(1.0, max_delta / 0.5)
    return round(0.5 * r + 0.3 * a + 0.2 * d, 3)


class FlashAnalyzer:
    def __init__(
        self,
        profile: Profile,
        width: int,
        height: int,
        fps: float,
        *,
        detect_patterns: bool = False,
        keep_grid_history: bool = True,
        max_history_frames: int = 60 * 130,
    ):
        self.p = profile
        self.width, self.height, self.fps = int(width), int(height), float(fps)
        self.gw, self.gh = profile.grid_w, profile.grid_h
        shape = (self.gh, self.gw)
        self.lum_tracker = TransitionTracker(shape, profile.luminance_delta, profile.reversal_eps)
        self.red = RedTracker(profile)
        self.counters = {
            "general": WindowCounter(shape, profile.window_s),
            "red": WindowCounter(shape, profile.window_s),
        }
        self.area = AreaChecker(profile, self.gw, self.gh)
        self.pattern = PatternDetector(profile) if detect_patterns else None
        self.frames: list[_Frame] = []
        self.open: dict[str, _OpenSegment | None] = {t: None for t in HAZARD_TYPES}
        self.segments: list[dict] = []
        self.keep_history = keep_grid_history
        self.max_history = max_history_frames
        self.lum_history: list[np.ndarray] = []
        self.t0 = time.perf_counter()
        self.n_frames = 0
        self.last_t = 0.0

    # ------------------------------------------------------------------ per frame
    def push(self, frame_bgr: np.ndarray, t: float) -> _Frame:
        p = self.p
        lum = relative_luminance(frame_bgr)
        lum_g = downsample(lum, self.gw, self.gh)
        if self.keep_history and len(self.lum_history) < self.max_history:
            self.lum_history.append(lum_g.astype(np.float16))
        ev_l = self.lum_tracker.push(lum_g, lum_g < p.dark_state_max, t)
        ev_r, _ = self.red.push(frame_bgr, t)
        rec = _Frame(self.n_frames, t, float(lum_g.mean()))
        limit = p.max_transitions_per_window
        for typ, ev in (("general", ev_l), ("red", ev_r)):
            count = self.counters[typ].push(ev)
            fail_cells = count > limit
            rec.rate[typ] = float(count.max()) / 2.0 / p.window_s
            frac = self.area.max_fraction(fail_cells)
            verdict = "pass"
            hit_mask = fail_cells
            if frac > p.area_fraction:
                verdict = "fail"
            elif p.conservative:
                warn_cells = count >= limit
                wfrac = self.area.max_fraction(warn_cells)
                if wfrac > p.area_fraction:
                    verdict, frac, hit_mask = "warn", wfrac, warn_cells
            rec.area[typ] = frac
            rec.verdict[typ] = verdict
            self._update_segment(typ, rec, verdict, hit_mask, ev.magnitude)
        if self.pattern is not None:
            self.pattern.analyze(lum, t)
        self.frames.append(rec)
        self.n_frames += 1
        self.last_t = t
        return rec

    def _update_segment(
        self, typ: str, rec: _Frame, verdict: str, mask: np.ndarray, magnitude: np.ndarray
    ) -> None:
        seg = self.open[typ]
        if verdict != "pass":
            if seg is None:
                # the violation is detected at the *end* of a one-second window; date the
                # segment from the first transition that window contains
                t0 = self.counters[typ].oldest_time(mask, rec.t)
                idx0 = rec.idx - int(round((rec.t - t0) * self.fps))
                seg = _OpenSegment(typ, max(0, idx0), t0, rec.idx, rec.t, verdict, mask.copy())
                self.open[typ] = seg
            seg.end_idx, seg.end_t = rec.idx, rec.t
            seg.mask |= mask
            seg.frames_since_hit = 0
            if verdict == "fail":
                seg.verdict = "fail"
            seg.peak_rate = max(seg.peak_rate, rec.rate[typ])
            seg.max_area = max(seg.max_area, rec.area[typ])
            if mask.any():
                seg.max_delta = max(
                    seg.max_delta, float(magnitude[mask].max()) if magnitude[mask].size else 0.0
                )
        elif seg is not None:
            seg.frames_since_hit += 1
            if rec.t - seg.end_t > GAP_TOLERANCE_S:
                self._close_segment(typ)

    def _close_segment(self, typ: str) -> None:
        seg = self.open[typ]
        if seg is None:
            return
        self.open[typ] = None
        regions = self._regions(seg.mask)
        max_delta = seg.max_delta
        if typ == "red":
            max_delta = seg.max_delta / 320.0  # report in the same 0..1 scale as luminance
        self.segments.append(
            {
                "id": f"{typ[0]}{len(self.segments):03d}",
                "type": typ,
                "verdict": seg.verdict,
                "start_frame": seg.start_idx,
                "end_frame": seg.end_idx,
                "start_s": round(seg.start_t, 4),
                "end_s": round(seg.end_t + 1.0 / self.fps, 4),
                "peak_flash_rate_hz": round(seg.peak_rate, 3),
                "max_area_fraction": round(float(seg.max_area), 4),
                "max_delta_L": round(float(max_delta), 4),
                "regions": regions,
                "severity_score": severity(
                    seg.peak_rate, seg.max_area, max_delta, self.p.max_flashes_per_window
                ),
            }
        )

    def _regions(self, mask: np.ndarray) -> list[dict]:
        if not mask.any():
            return [{"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}]
        n, _labels, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), connectivity=8
        )
        out = []
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            if a < 2 and n > 2:
                continue  # drop 1-cell specks when there is a real region
            out.append(
                {
                    "x": round(float(x) / self.gw, 4),
                    "y": round(float(y) / self.gh, 4),
                    "w": round(float(w) / self.gw, 4),
                    "h": round(float(h) / self.gh, 4),
                }
            )
        out.sort(key=lambda r: -(r["w"] * r["h"]))
        return out or [{"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}]

    # ------------------------------------------------------------------ finish
    def finish(self, meta: VideoMeta | dict | None = None) -> dict:
        for typ in HAZARD_TYPES:
            self._close_segment(typ)
        pattern_segments = []
        if self.pattern is not None:
            for ps in self.pattern.segments():
                s, e = ps["start_frame"], ps["end_frame"]
                pattern_segments.append(
                    {
                        "id": f"p{len(self.segments) + len(pattern_segments):03d}",
                        "type": "pattern",
                        "verdict": "warn",
                        "start_frame": s,
                        "end_frame": e,
                        "start_s": round(self.frames[s].t, 4),
                        "end_s": round(self.frames[e].t + 1.0 / self.fps, 4),
                        "peak_flash_rate_hz": 0.0,
                        "max_area_fraction": round(ps["max_area_fraction"], 4),
                        "max_delta_L": round(ps["max_contrast"], 4),
                        "regions": [{"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}],
                        "severity_score": round(
                            min(1.0, 0.5 * ps["max_contrast"] + 0.5 * ps["max_area_fraction"]), 3
                        ),
                        "experimental": True,
                        "cycles": round(ps["cycles"], 2),
                    }
                )
        all_segments = sorted(self.segments + pattern_segments, key=lambda s: s["start_s"])

        per_second = self._per_second(all_segments)
        overall = "pass"
        if any(s["verdict"] == "fail" for s in all_segments):
            overall = "fail"
        elif any(s["verdict"] == "warn" for s in all_segments):
            overall = "warn"

        elapsed = time.perf_counter() - self.t0
        duration = (self.last_t + 1.0 / self.fps) if self.frames else 0.0
        vid = meta.to_dict() if isinstance(meta, VideoMeta) else dict(meta or {})
        vid.setdefault("width", self.width)
        vid.setdefault("height", self.height)
        vid.setdefault("fps", self.fps)
        vid["frames_analyzed"] = self.n_frames
        vid["duration_analyzed_s"] = round(duration, 4)
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": {
                "name": "steadyframe",
                "version": __version__,
                "opencv": opencv_build_summary(),
            },
            "video": vid,
            "profile": {k: v for k, v in self.p.__dict__.items()},
            "verdict": overall,
            "per_second": per_second,
            "segments": all_segments,
            "timeline": {
                "t": [round(f.t, 4) for f in self.frames],
                "mean_L": [round(f.mean_L, 4) for f in self.frames],
                "general_rate_hz": [round(f.rate["general"], 3) for f in self.frames],
                "red_rate_hz": [round(f.rate["red"], 3) for f in self.frames],
                "general_area": [round(f.area["general"], 4) for f in self.frames],
                "red_area": [round(f.area["red"], 4) for f in self.frames],
            },
            "stats": {
                "analysis_time_s": round(elapsed, 4),
                "realtime_factor": round(duration / elapsed, 3) if elapsed > 0 else None,
                "grid": [self.gw, self.gh],
                "window_cells": [self.area.kw, self.area.kh],
            },
        }

    def _per_second(self, segments: list[dict]) -> list[dict]:
        if not self.frames:
            return []
        n_sec = int(np.floor(self.last_t)) + 1
        out = []
        for s in range(n_sec):
            fr = [f for f in self.frames if s <= f.t < s + 1]
            if not fr:
                continue
            rec = {"second": s}
            for typ in HAZARD_TYPES:
                vs = {f.verdict[typ] for f in fr}
                rec[typ] = "fail" if "fail" in vs else ("warn" if "warn" in vs else "pass")
            pat = "pass"
            for seg in segments:
                if seg["type"] == "pattern" and seg["start_s"] < s + 1 and seg["end_s"] > s:
                    pat = "warn"
            rec["pattern"] = pat
            vs = {rec["general"], rec["red"], rec["pattern"]}
            rec["verdict"] = "fail" if "fail" in vs else ("warn" if "warn" in vs else "pass")
            rec["max_flash_rate_hz"] = round(max(max(f.rate.values()) for f in fr), 3)
            rec["max_area_fraction"] = round(max(max(f.area.values()) for f in fr), 4)
            out.append(rec)
        return out

    # ------------------------------------------------------------------ helpers
    def region_series(self, region: dict) -> list[float]:
        """Mean luminance over time inside a normalised bbox (needs grid history)."""
        if not self.lum_history:
            return []
        x0 = int(np.floor(region["x"] * self.gw))
        y0 = int(np.floor(region["y"] * self.gh))
        x1 = max(x0 + 1, int(np.ceil((region["x"] + region["w"]) * self.gw)))
        y1 = max(y0 + 1, int(np.ceil((region["y"] + region["h"]) * self.gh)))
        return [
            round(float(g[y0:y1, x0:x1].astype(np.float32).mean()), 4) for g in self.lum_history
        ]


def analyze_file(
    path: str,
    *,
    profile: str | Profile = "wcag",
    conservative: bool = False,
    grid: tuple[int, int] | None = None,
    detect_patterns: bool = False,
    start_s: float | None = None,
    end_s: float | None = None,
    keep_grid_history: bool = False,
    return_analyzer: bool = False,
    backend: str = "auto",
):
    """Analyze a whole file (or the [start_s, end_s) part of it)."""
    prof = (
        profile
        if isinstance(profile, Profile)
        else get_profile(profile, conservative=conservative, grid=grid)
    )
    reader = open_video(path, backend=backend)
    m = reader.meta
    an = FlashAnalyzer(
        prof,
        m.width,
        m.height,
        m.fps,
        detect_patterns=detect_patterns,
        keep_grid_history=keep_grid_history,
    )
    for _idx, t, frame in reader:
        if start_s is not None and t < start_s - 1e-6:
            continue
        if end_s is not None and t >= end_s - 1e-6:
            break
        an.push(frame, t)
    result = an.finish(m)
    if start_s is not None or end_s is not None:
        result["video"]["analyzed_range_s"] = [start_s, end_s]
    return (result, an) if return_analyzer else result
