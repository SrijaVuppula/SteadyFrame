import numpy as np
import pytest

from steadyframe.io import ffmpeg as ff
from steadyframe.io.video import VideoWriter, open_video


def frames(n=20, w=64, h=48):
    rng = np.random.default_rng(0)
    return [rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8) for _ in range(n)]


@pytest.mark.parametrize("codec", ["h264", "lossless", "mp4v"])
def test_roundtrip_frame_count_and_timestamps(tmp_path, codec):
    fr = frames()
    p = tmp_path / f"c_{codec}.mp4"
    with VideoWriter(p, 64, 48, 25, codec=codec) as w:
        for f in fr:
            w.write(f)
    r = open_video(p)
    assert r.meta.width == 64 and r.meta.height == 48 and r.meta.fps == pytest.approx(25)
    got = list(r)
    assert len(got) == 20
    ts = [t for _, t, _ in got]
    assert ts[0] == 0.0 and all(b > a for a, b in zip(ts[:-1], ts[1:], strict=True))
    assert ts[-1] == pytest.approx(19 / 25, abs=1e-3)
    if codec == "lossless":
        assert all(np.array_equal(f, g) for (_, _, f), g in zip(got, fr, strict=True))


def test_ffmpeg_pipe_backend_matches_opencv(tmp_path):
    fr = frames()
    p = tmp_path / "c.mp4"
    with VideoWriter(p, 64, 48, 30, codec="lossless") as w:
        for f in fr:
            w.write(f)
    a = [f for _, _, f in open_video(p, backend="opencv")]
    b = [f for _, _, f in open_video(p, backend="ffmpeg")]
    assert len(a) == len(b) == 20
    assert all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))


def test_probe(tmp_path):
    p = tmp_path / "c.mp4"
    with VideoWriter(p, 64, 48, 30) as w:
        for f in frames():
            w.write(f)
    info = ff.probe(p)
    assert (info.width, info.height) == (64, 48)
    assert info.fps == pytest.approx(30)
    assert info.has_audio is False
    assert info.codec == "h264"


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        open_video("/nonexistent/clip.mp4")
