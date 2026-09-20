"""Feathered spatial masks from normalised regions."""

from __future__ import annotations

import cv2
import numpy as np


def region_mask(
    regions: list[dict],
    width: int,
    height: int,
    *,
    feather_frac: float = 0.02,
) -> np.ndarray:
    """float32 HxW mask in [0, 1]: 1 over the regions, soft edges *outside* them.

    The box is padded by 3 sigma before the Gaussian blur so every pixel of the original
    region keeps weight >= 0.99; feathering only ever extends outward. (An inward feather
    leaves the region's edge cells half-treated and they keep failing the analyzer.)"""
    m = np.zeros((height, width), np.float32)
    sigma = max(1.0, feather_frac * max(width, height))
    pad = int(round(3.0 * sigma))
    for r in regions:
        x0 = max(0, int(round(r["x"] * width)) - pad)
        y0 = max(0, int(round(r["y"] * height)) - pad)
        x1 = min(width, int(round((r["x"] + r["w"]) * width)) + pad)
        y1 = min(height, int(round((r["y"] + r["h"]) * height)) + pad)
        m[y0:y1, x0:x1] = 1.0
    if m.min() >= 1.0:
        return m
    return cv2.GaussianBlur(m, (0, 0), sigma)


def full_mask(width: int, height: int) -> np.ndarray:
    return np.ones((height, width), np.float32)


def blend(
    original: np.ndarray, processed: np.ndarray, mask: np.ndarray, weight: float = 1.0
) -> np.ndarray:
    """original*(1-w*m) + processed*(w*m), uint8 in / uint8 out."""
    if weight <= 0.0:
        return original
    w = (mask * float(weight))[..., None]
    out = original.astype(np.float32) * (1.0 - w) + processed.astype(np.float32) * w
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
