"""Linear-light helpers shared by the strategies."""

from __future__ import annotations

import cv2
import numpy as np

from ..luminance import LUMA_BGR, SRGB_TO_LINEAR_LUT

# inverse: linear [0,1] -> sRGB 8-bit, via a 4096-entry table (max error < 0.5 level)
_lin = np.linspace(0.0, 1.0, 4096)
_srgb = np.where(_lin <= 0.0031308, 12.92 * _lin, 1.055 * np.power(_lin, 1 / 2.4) - 0.055)
LINEAR_TO_SRGB_LUT = np.clip(np.round(_srgb * 255.0), 0, 255).astype(np.uint8)


def to_linear(frame_bgr: np.ndarray) -> np.ndarray:
    return cv2.LUT(frame_bgr, SRGB_TO_LINEAR_LUT)


def to_srgb8(lin_bgr: np.ndarray) -> np.ndarray:
    idx = np.clip(lin_bgr * 4095.0 + 0.5, 0, 4095).astype(np.uint16)
    return LINEAR_TO_SRGB_LUT[idx]


def luminance_of_linear(lin_bgr: np.ndarray) -> np.ndarray:
    return cv2.transform(lin_bgr, LUMA_BGR.reshape(1, 3))
