"""Relative luminance and red metrics per WCAG 2.2 (docs/STANDARDS.md 1.2).

Frames are BGR uint8 as OpenCV loads them. Outputs are float32 maps.
"""

from __future__ import annotations

import cv2
import numpy as np

# sRGB -> linear lookup table, 256 entries, float32.
_c = np.arange(256, dtype=np.float64) / 255.0
_LIN = np.where(_c <= 0.04045, _c / 12.92, ((_c + 0.055) / 1.055) ** 2.4).astype(np.float32)
SRGB_TO_LINEAR_LUT: np.ndarray = _LIN.copy()

# Rec. 709 / sRGB luminance coefficients in OpenCV's BGR channel order.
LUMA_BGR = np.array([0.0722, 0.7152, 0.2126], dtype=np.float32)

RED_SCALE = 320.0


def linearize(frame_bgr: np.ndarray) -> np.ndarray:
    """uint8 BGR frame -> float32 linear BGR in [0, 1] via cv2.LUT."""
    if frame_bgr.dtype != np.uint8:
        raise TypeError("expected uint8 frame")
    # cv2.LUT with a float LUT returns float32 with the same channel layout.
    return cv2.LUT(frame_bgr, SRGB_TO_LINEAR_LUT)


def relative_luminance(frame_bgr: np.ndarray) -> np.ndarray:
    """Per-pixel relative luminance L in [0, 1], float32, from a uint8 BGR frame."""
    lin = linearize(frame_bgr)
    # cv2.transform does the weighted channel sum in one call.
    return cv2.transform(lin, LUMA_BGR.reshape(1, 3))


def red_metrics(frame_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (red_ratio, red_value) maps.

    red_ratio = R / (R + G + B) in linear space (0 where the pixel is black);
    red_value = max(0, R - G - B) * 320  (PEAT / IRIS working rule, docs/STANDARDS.md 1.3).
    """
    lin = linearize(frame_bgr)
    b, g, r = cv2.split(lin)
    total = r + g + b
    ratio = np.divide(r, total, out=np.zeros_like(r), where=total > 1e-6)
    value = cv2.max(r - g - b, 0.0) * RED_SCALE
    return ratio, value


def uv_chromaticity(frame_bgr: np.ndarray) -> np.ndarray:
    """CIE 1976 UCS (u', v') per pixel, float32 HxWx2. Used only for the WCAG 2.2 red note."""
    lin = linearize(frame_bgr)
    b, g, r = cv2.split(lin)
    # sRGB (D65) -> XYZ
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    denom = x + 15.0 * y + 3.0 * z
    u = np.divide(4.0 * x, denom, out=np.zeros_like(x), where=denom > 1e-9)
    v = np.divide(9.0 * y, denom, out=np.zeros_like(y), where=denom > 1e-9)
    return np.dstack([u, v]).astype(np.float32)


def downsample(map_: np.ndarray, grid_w: int, grid_h: int) -> np.ndarray:
    """Box-average a per-pixel map onto the analysis grid (INTER_AREA)."""
    if map_.shape[1] == grid_w and map_.shape[0] == grid_h:
        return map_
    return cv2.resize(map_, (grid_w, grid_h), interpolation=cv2.INTER_AREA)


def relative_luminance_scalar(r8: int, g8: int, b8: int) -> float:
    """Reference implementation for one colour, used by tests and the synth ground truth."""

    def lin(c8: int) -> float:
        c = c8 / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r8) + 0.7152 * lin(g8) + 0.0722 * lin(b8)


def red_value_scalar(r8: int, g8: int, b8: int) -> tuple[float, float]:
    """Reference (ratio, value) for one colour."""

    def lin(c8: int) -> float:
        c = c8 / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r8), lin(g8), lin(b8)
    total = r + g + b
    ratio = r / total if total > 1e-6 else 0.0
    return ratio, max(0.0, r - g - b) * RED_SCALE
