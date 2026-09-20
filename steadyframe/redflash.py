"""Red flash detection = the generic transition machine fed with the red metric.

Kept as its own module so the mapping to the standard is explicit:
value = max(0, R - G - B) * 320, flag = R/(R+G+B) >= 0.8 (docs/STANDARDS.md 1.3).
"""

from __future__ import annotations

import numpy as np

from .flash import TransitionTracker
from .luminance import downsample, red_metrics
from .profiles import Profile


class RedTracker:
    def __init__(self, profile: Profile):
        self.profile = profile
        shape = (profile.grid_h, profile.grid_w)
        self.tracker = TransitionTracker(shape, profile.red_delta, profile.red_reversal_eps)

    def grids(self, frame_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ratio, value = red_metrics(frame_bgr)
        p = self.profile
        return downsample(ratio, p.grid_w, p.grid_h), downsample(value, p.grid_w, p.grid_h)

    def push(self, frame_bgr: np.ndarray, t: float):
        ratio_g, value_g = self.grids(frame_bgr)
        flag = ratio_g >= self.profile.red_saturation_ratio
        return self.tracker.push(value_g, flag, t), value_g
