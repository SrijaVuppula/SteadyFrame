import hashlib
import json

import numpy as np
import yaml

from steadyframe.analyzer import analyze_file
from steadyframe.io.video import open_video
from steadyframe.profiles import get_profile
from steadyframe.schema import validate_ground_truth
from synth import generate as g
from synth import reference as r


def test_reference_square_wave_transitions():
    times = [i / 30 for i in range(90)]
    vals = [0.1 if (i // 5) % 2 else 0.6 for i in range(90)]  # 3 Hz at 30 fps
    tt = r.transitions(vals, [True] * 90, times, 0.10, 0.02)
    assert len(tt) == 17
    counts = r.window_counts(tt, times, 1.0)
    assert max(counts) == 6


def test_reference_area_fraction():
    p = get_profile("wcag")
    assert r.region_window_fraction({"x": 0, "y": 0, "w": 1, "h": 1}, p) == 1.0
    small = {"x": 0.3, "y": 0.3, "w": 341 / 1024 / 2, "h": 256 / 768 / 2}
    assert abs(r.region_window_fraction(small, p) - 0.25) < 1e-9
    assert (
        abs(r.region_window_fraction(small, get_profile("broadcast")) - small["w"] * small["h"])
        < 1e-9
    )


def test_gray_pair_lands_on_the_right_side():
    lo, hi = g.pick_gray_pair(0.30, 0.09, above_threshold=False)
    assert g._GRAY_L[hi] - g._GRAY_L[lo] < 0.10
    lo, hi = g.pick_gray_pair(0.30, 0.11, above_threshold=True)
    assert g._GRAY_L[hi] - g._GRAY_L[lo] >= 0.10


def test_generate_is_deterministic_and_ground_truth_validates(tmp_path):
    cfg = {
        "name": "t_strobe",
        "width": 64,
        "height": 48,
        "fps": 30,
        "duration_s": 2.0,
        "codec": "lossless",
        "background": {"kind": "texture"},
        "events": [
            {
                "kind": "flash",
                "freq_hz": 6.0,
                "low_L": 0.05,
                "delta_L": 0.5,
                "start_s": 0.3,
                "end_s": 1.8,
            }
        ],
    }
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    g.render_clip(dict(cfg), a, seed=7)
    g.render_clip(dict(cfg), b, seed=7)
    gt = json.loads((a / "t_strobe.gt.json").read_text())
    validate_ground_truth(gt)
    assert gt["expected_verdict"] == "fail" and gt["expected_type"] == "general"
    assert gt["per_second"] == ["fail", "fail"]

    def digest(p):
        h = hashlib.sha256()
        for _, _, f in open_video(p):
            h.update(f.tobytes())
        return h.hexdigest()

    assert digest(a / "t_strobe.mp4") == digest(b / "t_strobe.mp4")
    c = tmp_path / "c"
    c.mkdir()
    g.render_clip(dict(cfg), c, seed=8)
    assert digest(c / "t_strobe.mp4") != digest(a / "t_strobe.mp4")  # texture seed differs
    assert analyze_file(str(a / "t_strobe.mp4"))["verdict"] == "fail"


def test_suite_yaml_expands_and_asserts_expected_verdicts():
    suite = yaml.safe_load(open("synth/suite.yaml"))
    clips = g.expand_suite(suite)
    names = [c["name"] for c in clips]
    assert len(names) == len(set(names))
    assert "b_rate_3hz" in names and "a_sweep_full" in names
    for c in clips:
        c = {**g.DEFAULTS, **c}
        times = [i / c["fps"] for i in range(int(c["duration_s"] * c["fps"]))]
        evs = []
        for ev in c.get("events", []):
            ev = dict(ev)
            if ev.get("kind", "flash") == "flash":
                ev["_lo"], ev["_hi"] = g._flash_colors(ev)
            evs.append(ev)
        gt = g.ground_truth(
            c, evs, times, get_profile(c["profile"])
        )  # raises if a stated expectation disagrees
        validate_ground_truth({**gt, "clip": "x.mp4"})


def test_waveforms():
    ph = np.array([0.0, 0.25, 0.5, 0.75])
    assert list(g.waveform("square", ph)) == [1, 1, 0, 0]
    assert g.waveform("sine", ph)[2] == 1.0
    assert list(g.waveform("ramp", ph)) == [0.0, 0.25, 0.5, 0.75]
