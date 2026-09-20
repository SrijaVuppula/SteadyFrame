import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from steadyframe.analyzer import analyze_file
from steadyframe.schema import validate_analysis

from .conftest import run_analyzer, square_frames


def test_full_frame_6hz_fails_and_localises_in_time():
    frames = square_frames(120, 30, 6.0, start=1.0)
    res = run_analyzer(frames, 30)
    validate_analysis(res)
    assert res["verdict"] == "fail"
    assert len(res["segments"]) == 1
    seg = res["segments"][0]
    assert seg["type"] == "general"
    assert seg["start_s"] == pytest.approx(1.0, abs=0.1)
    assert seg["peak_flash_rate_hz"] >= 6.0
    assert seg["max_area_fraction"] == 1.0
    assert seg["regions"][0] == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    assert [s["verdict"] for s in res["per_second"]] == ["pass", "fail", "fail", "fail"]


def test_two_hz_passes():
    res = run_analyzer(square_frames(120, 30, 2.0), 30)
    assert res["verdict"] == "pass" and res["segments"] == []


def test_three_hz_passes_but_warns_when_conservative():
    frames = square_frames(150, 30, 3.0)
    assert run_analyzer(frames, 30)["verdict"] == "pass"
    res = run_analyzer(frames, 30, conservative=True)
    assert res["verdict"] == "warn"
    assert res["segments"][0]["verdict"] == "warn"


def test_small_region_passes_and_larger_region_localises():
    # 64x48 frame with 64x48 grid: 1 cell = 1 px; window = 21x16 cells
    small = square_frames(120, 30, 8.0, region=(20, 10, 28, 18))  # 8x8 = 64/336 = 19%
    assert run_analyzer(small, 30)["verdict"] == "pass"
    big = square_frames(120, 30, 8.0, region=(20, 10, 32, 22))  # 12x12 = 144/336 = 43%
    res = run_analyzer(big, 30)
    assert res["verdict"] == "fail"
    r = res["segments"][0]["regions"][0]
    assert r["x"] == pytest.approx(20 / 64, abs=0.02) and r["y"] == pytest.approx(10 / 48, abs=0.03)
    assert r["w"] == pytest.approx(12 / 64, abs=0.02) and r["h"] == pytest.approx(12 / 48, abs=0.03)


def test_broadcast_profile_uses_whole_screen():
    big = square_frames(120, 30, 8.0, region=(20, 10, 32, 22))  # 4.7% of the screen
    assert run_analyzer(big, 30, profile="broadcast")["verdict"] == "pass"
    huge = square_frames(120, 30, 8.0, region=(0, 0, 40, 40))  # 52% of the screen
    assert run_analyzer(huge, 30, profile="broadcast")["verdict"] == "fail"


def test_red_strobe_gives_red_segment():
    frames = square_frames(120, 30, 5.0, lo=(0, 0, 60), hi=(0, 0, 255))
    res = run_analyzer(frames, 30)
    assert res["verdict"] == "fail"
    assert {s["type"] for s in res["segments"]} == {"general", "red"}


def test_near_red_not_saturated_is_not_red():
    frames = square_frames(120, 30, 6.0, lo=(72, 72, 180), hi=(90, 90, 220))
    res = run_analyzer(frames, 30)
    assert res["verdict"] == "pass"


def test_one_frame_flash_passes():
    frames = square_frames(90, 30, 0.0)
    frames[45][:] = 255
    assert run_analyzer(frames, 30)["verdict"] == "pass"


def test_variable_frame_rate_uses_timestamps():
    from steadyframe.analyzer import FlashAnalyzer
    from steadyframe.profiles import get_profile

    # 6 Hz strobe delivered at 30 fps but with timestamps stretched 2x -> effectively 3 Hz
    frames = square_frames(150, 30, 6.0)
    an = FlashAnalyzer(get_profile("wcag"), 64, 48, 30)
    for i, f in enumerate(frames):
        an.push(f, 2 * i / 30)
    assert an.finish()["verdict"] == "pass"


@settings(max_examples=12, deadline=None)
@given(freq=st.sampled_from([2.0, 5.0, 8.0]), scale=st.sampled_from([1, 2, 3]))
def test_scaling_resolution_does_not_flip_verdict(freq, scale):
    base = square_frames(60, 30, freq, size=(64, 48), region=(16, 12, 48, 36))
    scaled = [np.repeat(np.repeat(f, scale, axis=0), scale, axis=1) for f in base]
    assert run_analyzer(base, 30)["verdict"] == run_analyzer(scaled, 30)["verdict"]


@settings(max_examples=8, deadline=None)
@given(border=st.integers(min_value=2, max_value=12), freq=st.sampled_from([1.0, 6.0]))
def test_static_border_does_not_create_or_remove_hazards(border, freq):
    base = square_frames(60, 30, freq, size=(64, 48))
    padded = [
        np.pad(f, ((border, border), (border, border), (0, 0)), constant_values=40) for f in base
    ]
    assert run_analyzer(base, 30)["verdict"] == run_analyzer(padded, 30)["verdict"]


def test_analyze_file_with_range(tmp_clip):
    frames = square_frames(150, 30, 6.0, start=2.0)
    p = tmp_clip(frames)
    full = analyze_file(str(p))
    assert full["verdict"] == "fail"
    head = analyze_file(str(p), end_s=1.5)
    assert head["verdict"] == "pass" and head["video"]["frames_analyzed"] == 45
