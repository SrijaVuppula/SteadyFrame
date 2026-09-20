"""S2: regional luminance-swing compression toward the running temporal mean."""

from __future__ import annotations

import cv2
import numpy as np

from .base import Processor, StrategySpec
from .colour import luminance_of_linear, to_linear, to_srgb8

SPEC = StrategySpec(
    id="S2",
    name="luminance swing compression",
    invasiveness=2,
    applies_to=("general",),
    scope="regional",
    requires_approval=False,
    params={
        "max_swing": {
            "default": 0.05,
            "min": 0.02,
            "max": 0.2,
            "doc": "allowed peak-to-peak relative-luminance swing around the running mean (WCAG transition threshold is 0.10; the running mean itself wobbles a little on a strobe, so leave margin)",
        },
        "mean_alpha": {
            "default": 0.02,
            "min": 0.01,
            "max": 0.3,
            "doc": "EMA weight for the running mean luminance",
        },
    },
    doc="per-pixel gain in linear light so |L - mean_L| <= max_swing/2; colour is preserved",
)


class S2(Processor):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.mean: np.ndarray | None = None

    def process(self, frame_bgr: np.ndarray, t: float, inside: bool) -> np.ndarray:
        lin = to_linear(frame_bgr)
        L = luminance_of_linear(lin)
        if self.mean is None:
            self.mean = L.copy()
        else:
            cv2.accumulateWeighted(L, self.mean, float(self.params["mean_alpha"]))
        half = float(self.params["max_swing"]) / 2.0
        target = self.mean + np.clip(L - self.mean, -half, half)
        gain = np.divide(target, L, out=np.ones_like(L), where=L > 1e-4)
        out = np.clip(lin * gain[..., None], 0.0, 1.0)
        return to_srgb8(out)
