"""Area condition (docs/STANDARDS.md 1.3, "Area").

The flashing mask is a bool grid of analysis cells. For the ``wcag`` profile we slide a
window sized 341/1024 x 256/768 of the frame over the grid and take the largest flashing
fraction (``cv2.boxFilter`` with normalisation is exactly that computation). For the
``broadcast`` profile the window is the whole frame.
"""

from __future__ import annotations

import cv2
import numpy as np

from .profiles import Profile


def window_cells(profile: Profile, grid_w: int, grid_h: int) -> tuple[int, int]:
    """Sliding-window size in cells (at least 1x1, at most the grid)."""
    if profile.area_mode == "screen":
        return grid_w, grid_h
    w = int(round(profile.window_frac_w * grid_w))
    h = int(round(profile.window_frac_h * grid_h))
    return max(1, min(grid_w, w)), max(1, min(grid_h, h))


class AreaChecker:
    def __init__(self, profile: Profile, grid_w: int, grid_h: int):
        self.profile = profile
        self.kw, self.kh = window_cells(profile, grid_w, grid_h)
        self.threshold = profile.area_fraction

    def fraction_map(self, mask: np.ndarray) -> np.ndarray:
        """Flashing fraction for every valid window position (shape (gh-kh+1, gw-kw+1))."""
        m = mask.astype(np.float32)
        gh, gw = m.shape
        if self.kw >= gw and self.kh >= gh:
            return np.array([[float(m.mean())]], dtype=np.float32)
        # boxFilter output is centred; slice to the valid (fully inside) positions only
        f = cv2.boxFilter(
            m, ddepth=-1, ksize=(self.kw, self.kh), normalize=True, borderType=cv2.BORDER_CONSTANT
        )
        y0, x0 = self.kh // 2, self.kw // 2
        y1, x1 = y0 + (gh - self.kh + 1), x0 + (gw - self.kw + 1)
        return f[y0:y1, x0:x1]

    def max_fraction(self, mask: np.ndarray) -> float:
        if not mask.any():
            return 0.0
        return float(self.fraction_map(mask).max())

    def exceeds(self, mask: np.ndarray) -> bool:
        return self.max_fraction(mask) > self.threshold
