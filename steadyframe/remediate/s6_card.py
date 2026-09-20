"""S6: replace the segment with a static warning card (audio is kept by the renderer)."""

from __future__ import annotations

import cv2
import numpy as np

from .base import Processor, StrategySpec

SPEC = StrategySpec(
    id="S6",
    name="static warning card",
    invasiveness=6,
    applies_to=("general", "red", "pattern"),
    scope="global",
    requires_approval=True,
    params={
        "text": {"default": "Flashing sequence removed", "doc": "card text"},
        "gray": {"default": 40, "min": 0, "max": 120, "doc": "card background gray level"},
    },
    doc="last resort; the segment becomes a still card. Always needs human approval.",
)


class S6(Processor):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        g = int(self.params["gray"])
        self.card = np.full((self.height, self.width, 3), g, np.uint8)
        scale = max(0.4, min(self.width, self.height) / 400.0)
        text = str(self.params["text"])
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        org = (max(4, (self.width - tw) // 2), (self.height + th) // 2)
        cv2.putText(
            self.card, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (220, 220, 220), 1, cv2.LINE_AA
        )
        self.last: np.ndarray | None = None

    def process(self, frame_bgr: np.ndarray, t: float, inside: bool) -> np.ndarray:
        return self.card if inside else frame_bgr
