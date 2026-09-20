"""S1: regional temporal low-pass (exponential frame blending in linear light).

Blending is done on linearised values: averaging sRGB code values instead would leave a
larger *luminance* swing than the EMA maths predicts (measured 24% vs 13% residual on a
6 Hz square wave with alpha 0.1), because relative luminance is convex in code value."""

from __future__ import annotations

import cv2
import numpy as np

from .base import Processor, StrategySpec
from .colour import to_linear, to_srgb8

SPEC = StrategySpec(
    id="S1",
    name="temporal low-pass",
    invasiveness=1,
    applies_to=("general", "red"),
    scope="regional",
    requires_approval=False,
    params={
        "alpha": {
            "default": 0.1,
            "min": 0.02,
            "max": 0.6,
            "doc": "EMA weight of the new frame; lower = stronger smoothing. A square wave with half-period N frames keeps (1-r^N)/(1+r^N) of its swing, r = 1 - alpha; 0.1 leaves ~13% at 6 Hz / 30 fps",
        },
    },
    doc="cv2.accumulateWeighted running average in linear light inside the hazard region, feathered mask",
)


class S1(Processor):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.acc: np.ndarray | None = None

    def process(self, frame_bgr: np.ndarray, t: float, inside: bool) -> np.ndarray:
        lin = to_linear(frame_bgr)
        if self.acc is None:
            self.acc = lin.copy()
        else:
            cv2.accumulateWeighted(lin, self.acc, float(self.params["alpha"]))
        return to_srgb8(self.acc)
