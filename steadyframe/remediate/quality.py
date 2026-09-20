"""Quality metrics between original and remediated frames.

SSIM is implemented with OpenCV Gaussian filtering (Wang et al. 2004: 11x11 window,
sigma 1.5, K1=0.01, K2=0.03) on the gray image; tested against a NumPy reference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..luminance import relative_luminance

_C1 = (0.01 * 255) ** 2
_C2 = (0.03 * 255) ** 2


def ssim_map(a_gray: np.ndarray, b_gray: np.ndarray) -> np.ndarray:
    a = a_gray.astype(np.float32)
    b = b_gray.astype(np.float32)
    mu_a = cv2.GaussianBlur(a, (11, 11), 1.5)
    mu_b = cv2.GaussianBlur(b, (11, 11), 1.5)
    s_aa = cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a * mu_a
    s_bb = cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b * mu_b
    s_ab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_a * mu_b
    num = (2 * mu_a * mu_b + _C1) * (2 * s_ab + _C2)
    den = (mu_a * mu_a + mu_b * mu_b + _C1) * (s_aa + s_bb + _C2)
    return num / den


def ssim(a_bgr: np.ndarray, b_bgr: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Mean SSIM over the frame, or over ``mask > 0.5`` if given (1.0 if the mask is empty)."""
    m = ssim_map(cv2.cvtColor(a_bgr, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b_bgr, cv2.COLOR_BGR2GRAY))
    if mask is None:
        return float(m.mean())
    sel = mask > 0.5
    return float(m[sel].mean()) if sel.any() else 1.0


def psnr(a_bgr: np.ndarray, b_bgr: np.ndarray, mask: np.ndarray | None = None) -> float:
    d = (a_bgr.astype(np.float32) - b_bgr.astype(np.float32)) ** 2
    if mask is not None:
        sel = mask > 0.5
        if not sel.any():
            return math.inf
        d = d[sel]
    mse = float(d.mean())
    return math.inf if mse <= 1e-10 else 10.0 * math.log10(255.0**2 / mse)


@dataclass
class QualityAccumulator:
    """Streams (original, candidate) frame pairs for a segment and its region mask."""

    region_mask: np.ndarray  # float32 HxW, 1 inside the hazard regions
    ssim_out: list[float] = field(default_factory=list)
    ssim_in: list[float] = field(default_factory=list)
    ssim_all: list[float] = field(default_factory=list)
    psnr_out: list[float] = field(default_factory=list)
    dL_in: list[float] = field(default_factory=list)
    _outside: np.ndarray | None = None
    _prev_L_a: np.ndarray | None = None
    _prev_L_b: np.ndarray | None = None
    temporal_a: list[float] = field(default_factory=list)
    temporal_b: list[float] = field(default_factory=list)

    def push(self, orig: np.ndarray, cand: np.ndarray) -> None:
        inside = self.region_mask
        if self._outside is None:
            # exclude a band of the SSIM window radius around the regions so "outside" is
            # not polluted by the 11x11 Gaussian smearing edits across the boundary
            dil = cv2.dilate((inside > 0.5).astype(np.uint8), np.ones((11, 11), np.uint8))
            self._outside = 1.0 - dil.astype(np.float32)
        outside = self._outside
        self.ssim_all.append(ssim(orig, cand))
        self.ssim_in.append(ssim(orig, cand, inside))
        self.ssim_out.append(ssim(orig, cand, outside))
        self.psnr_out.append(psnr(orig, cand, outside))
        La = relative_luminance(orig)
        Lb = relative_luminance(cand)
        sel = inside > 0.5
        self.dL_in.append(float(np.abs(La - Lb)[sel].mean()) if sel.any() else 0.0)
        if self._prev_L_a is not None:
            self.temporal_a.append(
                float(np.abs(La - self._prev_L_a)[sel].mean()) if sel.any() else 0.0
            )
            self.temporal_b.append(
                float(np.abs(Lb - self._prev_L_b)[sel].mean()) if sel.any() else 0.0
            )
        self._prev_L_a, self._prev_L_b = La, Lb

    def summary(self) -> dict:
        def mean(x):
            return float(np.mean(x)) if x else None

        finite = [p for p in self.psnr_out if math.isfinite(p)]
        ta, tb = mean(self.temporal_a), mean(self.temporal_b)
        return {
            "ssim_overall": mean(self.ssim_all),
            "ssim_inside": mean(self.ssim_in),
            "ssim_outside": mean(self.ssim_out),
            "psnr_outside_db": (float(np.mean(finite)) if finite else None)
            if self.psnr_out
            else None,
            "psnr_outside_is_lossless": bool(self.psnr_out) and not finite,
            "mean_abs_dL_inside": mean(self.dL_in),
            "temporal_step_before": ta,
            "temporal_step_after": tb,
            "temporal_smoothness_gain": (ta / tb) if (ta and tb and tb > 1e-9) else None,
            "frames": len(self.ssim_all),
        }
