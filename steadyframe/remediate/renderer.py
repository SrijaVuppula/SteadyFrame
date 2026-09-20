"""Streaming renderer: applies a list of plans (segment + strategy + params) to a video.

Each plan is active on [start_s - margin, end_s + margin]; inside the margins the
processed frame is cross-faded with the original (weight ramps 0 -> 1), and spatially the
processed frame is blended through the feathered region mask (or a full-frame mask for
global strategies). Frame count, timing and resolution are preserved, so audio can be
remuxed 1:1 afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..io import ffmpeg as ff
from ..io.video import VideoWriter, open_video
from .mask import blend, full_mask, region_mask
from .quality import QualityAccumulator
from .registry import make_processor


@dataclass
class Plan:
    segment_id: str
    type: str
    start_s: float
    end_s: float
    regions: list[dict]
    strategy: str
    params: dict = field(default_factory=dict)
    margin_s: float = 0.5
    fade_s: float = 0.25

    @property
    def active_start(self) -> float:
        return max(0.0, self.start_s - self.margin_s)

    @property
    def active_end(self) -> float:
        return self.end_s + self.margin_s

    def weight(self, t: float) -> float:
        if t < self.active_start or t > self.active_end:
            return 0.0
        fade = max(1e-6, min(self.fade_s, self.margin_s))
        w_in = min(1.0, (t - self.active_start) / fade)
        w_out = min(1.0, (self.active_end - t) / fade)
        return max(0.0, min(w_in, w_out))

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "type": self.type,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "regions": self.regions,
            "strategy": self.strategy,
            "params": self.params,
            "margin_s": self.margin_s,
            "fade_s": self.fade_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Plan:
        return cls(
            **{
                k: d[k]
                for k in (
                    "segment_id",
                    "type",
                    "start_s",
                    "end_s",
                    "regions",
                    "strategy",
                    "params",
                    "margin_s",
                    "fade_s",
                )
                if k in d
            }
        )


class _Active:
    def __init__(self, plan: Plan, width: int, height: int, fps: float):
        self.plan = plan
        proc, spec, params = make_processor(plan.strategy, plan.params, width, height, fps)
        self.proc = proc
        self.spec = spec
        self.params = params
        self.mask = (
            full_mask(width, height)
            if spec.scope == "global"
            else region_mask(plan.regions, width, height)
        )


def render(
    src: str | Path,
    dst: str | Path,
    plans: list[Plan],
    *,
    range_s: tuple[float, float] | None = None,
    quality_for: str | None = None,
    crf: int = 18,
    keep_audio: bool = True,
) -> dict:
    """Render ``src`` to ``dst`` with the plans applied.

    ``range_s`` restricts output to frames with start <= t < end (candidate clips).
    ``quality_for`` names a plan's segment_id; quality metrics are accumulated for the
    frames of that plan's segment (with its region mask) and returned.
    """
    reader = open_video(src)
    m = reader.meta
    active = [_Active(p, m.width, m.height, m.fps) for p in plans]
    q: QualityAccumulator | None = None
    q_plan: Plan | None = None
    if quality_for:
        q_plan = next((p for p in plans if p.segment_id == quality_for), None)
        if q_plan is not None:
            qa = next(a for a in active if a.plan is q_plan)
            q = QualityAccumulator(region_mask=(qa.mask > 0.5).astype(np.float32))
    dst = Path(dst)
    tmp_video = dst.with_suffix(".video.mp4")
    written = 0
    first_t = None
    with VideoWriter(tmp_video, m.width, m.height, m.fps, codec="h264", crf=crf) as w:
        for _idx, t, frame in reader:
            if range_s is not None and t < range_s[0] - 1e-6:
                # let processors see nothing before the range; they only need their own margins
                continue
            if range_s is not None and t >= range_s[1] - 1e-6:
                break
            if first_t is None:
                first_t = t
            out = frame
            for a in active:
                wt = a.plan.weight(t)
                if wt <= 0.0:
                    continue
                inside = a.plan.start_s <= t < a.plan.end_s
                processed = a.proc.process(out, t, inside)
                out = blend(out, processed, a.mask, wt)
            if q is not None and q_plan is not None and q_plan.start_s <= t < q_plan.end_s:
                q.push(frame, out)
            w.write(out)
            written += 1
    audio = False
    if keep_audio and range_s is None and m.has_audio:
        audio = ff.remux_audio(tmp_video, src, dst)
        tmp_video.unlink(missing_ok=True)
    else:
        tmp_video.replace(dst)
    return {
        "path": str(dst),
        "frames": written,
        "fps": m.fps,
        "width": m.width,
        "height": m.height,
        "t0": first_t or 0.0,
        "audio_remuxed": audio,
        "quality": q.summary() if q is not None else None,
        "plans": [{**a.plan.to_dict(), "params": a.params, "scope": a.spec.scope} for a in active],
    }
