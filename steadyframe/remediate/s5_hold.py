"""S5: rate limiting by frame hold (each output frame is held for k input frames)."""

from __future__ import annotations

import math

import numpy as np

from .base import Processor, StrategySpec

SPEC = StrategySpec(
    id="S5",
    name="frame hold rate limit",
    invasiveness=4,
    applies_to=("general", "red"),
    scope="global",
    requires_approval=False,
    params={
        "target_hz": {
            "default": 2.5,
            "min": 1.0,
            "max": 3.0,
            "doc": "maximum flash rate after holding; hold = ceil(fps / (2 * target_hz)) frames",
        },
    },
    doc="frame selection: output frame changes at most 2*target_hz times per second; frame count and timing are preserved so audio stays in sync",
)


class S5(Processor):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.hold = max(1, int(math.ceil(self.fps / (2.0 * float(self.params["target_hz"])))))
        self.held: np.ndarray | None = None
        self.n = 0

    def process(self, frame_bgr: np.ndarray, t: float, inside: bool) -> np.ndarray:
        if not inside:
            # in the margin, pass frames through but keep the phase counter primed
            self.held = frame_bgr
            self.n = 0
            return frame_bgr
        if self.held is None or self.n % self.hold == 0:
            self.held = frame_bgr.copy()
        self.n += 1
        return self.held
