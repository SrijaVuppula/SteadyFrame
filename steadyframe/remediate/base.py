"""Strategy interface. A strategy is a streaming per-frame processor with state; the
renderer feeds it every frame inside the segment plus margins and blends the result in
with a feathered mask and a cross-fade weight."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class StrategySpec:
    id: str
    name: str
    invasiveness: int  # 1 (least) .. 6 (most)
    applies_to: tuple[str, ...]  # hazard types
    scope: str  # "regional" or "global"
    requires_approval: bool
    params: dict = field(default_factory=dict)  # name -> {default, min, max, doc}
    doc: str = ""

    def defaults(self) -> dict:
        return {k: v["default"] for k, v in self.params.items()}

    def clamp(self, params: dict | None) -> dict:
        out = self.defaults()
        for k, v in (params or {}).items():
            if k in self.params and v is not None:
                lo, hi = self.params[k].get("min"), self.params[k].get("max")
                if isinstance(v, (int, float)) and lo is not None:
                    v = min(hi, max(lo, v))
                out[k] = v
        return out


class Processor:
    """One instance per (strategy, segment). Called once per frame in stream order."""

    def __init__(self, spec: StrategySpec, params: dict, width: int, height: int, fps: float):
        self.spec = spec
        self.params = params
        self.width, self.height, self.fps = width, height, fps

    def process(self, frame_bgr: np.ndarray, t: float, inside: bool) -> np.ndarray:
        """Return the processed full frame (the renderer does the masking/blending).
        ``inside`` is True for frames within the segment proper (not the margin)."""
        raise NotImplementedError
