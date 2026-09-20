import numpy as np
import pytest

from steadyframe.analyzer import FlashAnalyzer
from steadyframe.profiles import get_profile


def square_frames(
    n, fps, freq_hz, lo=(20, 20, 20), hi=(230, 230, 230), size=(64, 48), region=None, start=0.0
):
    """Frames of a square-wave strobe (BGR uint8). region = (x0, y0, x1, y1) in pixels or None for full frame."""
    w, h = size
    frames = []
    for i in range(n):
        t = i / fps
        phase = round((t - start) * freq_hz, 9)
        on = (phase - np.floor(phase)) < 0.5 and t >= start
        f = np.full((h, w, 3), lo, np.uint8)
        col = hi if on else lo
        if region is None:
            f[:] = col
        else:
            x0, y0, x1, y1 = region
            f[y0:y1, x0:x1] = col
        frames.append(f)
    return frames


def run_analyzer(frames, fps, profile="wcag", **kw):
    prof = get_profile(profile, **{k: v for k, v in kw.items() if k in ("conservative", "grid")})
    h, w = frames[0].shape[:2]
    an = FlashAnalyzer(prof, w, h, fps, detect_patterns=kw.get("patterns", False))
    for i, f in enumerate(frames):
        an.push(f, i / fps)
    return an.finish({"path": "mem"})


@pytest.fixture
def tmp_clip(tmp_path):
    from steadyframe.io.video import VideoWriter

    def _make(frames, fps=30, name="clip.mp4", codec="lossless"):
        p = tmp_path / name
        with VideoWriter(p, frames[0].shape[1], frames[0].shape[0], fps, codec=codec) as w:
            for f in frames:
                w.write(f)
        return p

    return _make
