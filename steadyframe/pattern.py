"""Experimental spatial pattern detector (Ofcom: > 5 light-dark pairs, high contrast,
> 25% of the screen, sustained > 0.5 s). Reported as "pattern risk (experimental)".

Method: 2-D DFT of the luminance map (cv2.dft). The dominant non-DC peak gives the stripe
frequency in cycles per frame; the peak amplitude relative to the mean gives a Michelson-like
contrast; a local-standard-deviation mask at the stripe scale estimates the area covered.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .profiles import Profile


@dataclass
class PatternFrame:
    t: float
    cycles: float
    contrast: float
    area: float
    hit: bool


class PatternDetector:
    def __init__(self, profile: Profile, size: tuple[int, int] = (256, 192)):
        self.p = profile
        self.w, self.h = size
        self.frames: list[PatternFrame] = []

    def analyze(self, lum_map: np.ndarray, t: float) -> PatternFrame:
        p = self.p
        small = cv2.resize(lum_map, (self.w, self.h), interpolation=cv2.INTER_AREA).astype(
            np.float32
        )
        mean = float(small.mean())
        if mean < 1e-4:
            pf = PatternFrame(t, 0.0, 0.0, 0.0, False)
            self.frames.append(pf)
            return pf
        centered = small - mean
        spec = cv2.dft(centered, flags=cv2.DFT_COMPLEX_OUTPUT)
        mag = cv2.magnitude(spec[..., 0], spec[..., 1])
        # frequency grid in cycles per frame (along the frame's diagonal-normalised axes)
        fy = np.fft.fftfreq(self.h) * self.h
        fx = np.fft.fftfreq(self.w) * self.w
        FY, FX = np.meshgrid(fy, fx, indexing="ij")
        cycles = np.sqrt(FX**2 + FY**2)
        # ignore frequencies below the min-pairs rule and the very highest (noise)
        valid = (cycles > p.pattern_min_pairs) & (cycles < min(self.w, self.h) / 3)
        m = np.where(valid, mag, 0.0)
        idx = np.unravel_index(int(np.argmax(m)), m.shape)
        peak = float(m[idx])
        # amplitude of a pure sinusoid a*cos -> DFT magnitude a*N/2 ; contrast ~ a / mean
        amp = 2.0 * peak / (self.w * self.h)
        contrast = min(1.0, amp / mean) if mean > 0 else 0.0
        cyc = float(cycles[idx])
        # area: cells whose local std at the stripe scale is high
        period = max(3, int(round(max(self.w, self.h) / max(cyc, 1.0))))
        k = (period | 1, period | 1)
        mu = cv2.blur(small, k)
        var = cv2.blur(small * small, k) - mu * mu
        std = np.sqrt(np.clip(var, 0, None))
        area = float((std > (p.pattern_min_contrast * mean) / 2.0).mean())
        hit = (
            contrast >= p.pattern_min_contrast
            and area > p.pattern_area_fraction
            and cyc > p.pattern_min_pairs
        )
        pf = PatternFrame(t, cyc, contrast, area, hit)
        self.frames.append(pf)
        return pf

    def segments(self) -> list[dict]:
        """Runs of hits lasting at least pattern_min_duration_s."""
        out: list[dict] = []
        start = None
        for i, f in enumerate(self.frames):
            if f.hit and start is None:
                start = i
            if (not f.hit or i == len(self.frames) - 1) and start is not None:
                end = i if f.hit else i - 1
                dur = self.frames[end].t - self.frames[start].t
                if dur >= self.p.pattern_min_duration_s:
                    out.append(
                        {
                            "start_frame": start,
                            "end_frame": end,
                            "max_contrast": max(x.contrast for x in self.frames[start : end + 1]),
                            "max_area_fraction": max(x.area for x in self.frames[start : end + 1]),
                            "cycles": float(
                                np.median([x.cycles for x in self.frames[start : end + 1]])
                            ),
                        }
                    )
                start = None
        return out
