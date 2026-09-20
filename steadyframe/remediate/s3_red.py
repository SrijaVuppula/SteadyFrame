"""S3: red desaturation in the hazard region."""

from __future__ import annotations

import numpy as np

from .base import Processor, StrategySpec
from .colour import luminance_of_linear, to_linear, to_srgb8

SPEC = StrategySpec(
    id="S3",
    name="red desaturation",
    invasiveness=2,
    applies_to=("red",),
    scope="regional",
    requires_approval=False,
    params={
        "strength": {
            "default": 0.6,
            "min": 0.2,
            "max": 1.0,
            "doc": "how far saturated-red pixels are pulled toward an equal-luminance gray (1.0 = fully)",
        },
        "ratio_floor": {
            "default": 0.7,
            "min": 0.4,
            "max": 0.79,
            "doc": "pixels with R/(R+G+B) above this are treated",
        },
    },
    doc="linear-light mix toward gray of the same relative luminance; only pixels near the saturated-red criterion are touched",
)


class S3(Processor):
    def process(self, frame_bgr: np.ndarray, t: float, inside: bool) -> np.ndarray:
        lin = to_linear(frame_bgr)
        b, g, r = lin[..., 0], lin[..., 1], lin[..., 2]
        total = r + g + b
        ratio = np.divide(r, total, out=np.zeros_like(r), where=total > 1e-6)
        L = luminance_of_linear(lin)
        floor = float(self.params["ratio_floor"])
        # smooth weight from ratio_floor up to 0.9
        w = np.clip((ratio - floor) / max(1e-6, 0.9 - floor), 0.0, 1.0) * float(
            self.params["strength"]
        )
        gray = np.repeat(L[..., None], 3, axis=2)
        out = lin * (1.0 - w[..., None]) + gray * w[..., None]
        return to_srgb8(np.clip(out, 0.0, 1.0))
