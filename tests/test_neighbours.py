"""Cases the synthetic suite did not cover and the external clips did: hazards close to each
other, and violations embedded in flashing that sits exactly at the limit."""

import json

import numpy as np

from steadyframe.agent.providers import HeuristicProvider
from steadyframe.remediate.pipeline import fix_file

from .conftest import run_analyzer, square_frames


def bursts(fps, pieces, size=(64, 48)):
    """Concatenate (seconds, freq_hz or 0 for calm) pieces of a full-frame square wave."""
    frames = []
    for dur, freq in pieces:
        n = int(round(dur * fps))
        if freq:
            frames += square_frames(n, fps, freq, size=size)
        else:
            frames += [np.full((size[1], size[0], 3), 20, np.uint8) for _ in range(n)]
    return frames


def two_bursts(fps=30):
    return bursts(fps, [(0.5, 0), (2.0, 6.0), (1.0, 0), (2.0, 6.0), (0.5, 0)])


def at_limit_with_spike(fps=30):
    # 3 Hz is exactly six transitions a second (passes, no headroom); 5 Hz in the middle fails
    return bursts(fps, [(2.5, 3.0), (1.0, 5.0), (2.5, 3.0)])


def test_segment_reports_detection_time_and_episode():
    res = run_analyzer(at_limit_with_spike(), 30)
    segs = [s for s in res["segments"] if s["verdict"] == "fail"]
    assert len(segs) == 1
    s = segs[0]
    assert s["start_s"] <= s["detected_s"] < s["end_s"]
    # the 3 Hz flashing on both sides is part of the episode, well past the 0.5 s margin
    assert s["episode_start_s"] < s["start_s"] - 0.5
    assert s["episode_end_s"] > s["end_s"] + 0.5
    assert s["episode_end_s"] <= 6.0 + 1e-6


def test_clean_burst_episode_stays_close_to_segment():
    res = run_analyzer(bursts(30, [(1.0, 0), (2.0, 6.0), (1.0, 0)]), 30)
    s = res["segments"][0]
    assert s["episode_start_s"] >= s["start_s"] - 0.5
    assert s["episode_end_s"] <= s["end_s"] + 0.5


def test_neighbour_in_padding_does_not_fail_the_candidate(tmp_clip, tmp_path):
    src = tmp_clip(two_bursts(), fps=30)
    wd = tmp_path / "wd"
    # full-swing full-frame strobes need approval (ssim < 0.75); the attribution is the point here
    rep = fix_file(src, tmp_path / "o.mp4", workdir=wd, approve_all=True)
    assert rep["status"] == "passed" and rep["after"]["verdict"] == "pass"
    assert [len(s["attempts"]) for s in rep["segments"]] == [1, 1]
    verifies = [
        json.loads(line)["result"]
        for line in (wd / "trace.jsonl").read_text().splitlines()
        if json.loads(line)["kind"] == "tool_result"
        and json.loads(line)["name"] == "verify_candidate"
    ]
    first = verifies[0]
    assert first["passes_for_type"] and not first["remaining_same_type"]
    assert {x["belongs_to"] for x in first["remaining_in_untreated_segments"]} == {"g001"}


def test_fix_covers_the_at_limit_episode(tmp_clip, tmp_path):
    src = tmp_clip(at_limit_with_spike(), fps=30)
    rep = fix_file(src, tmp_path / "o.mp4", workdir=tmp_path / "wd", approve_all=True)
    assert rep["status"] == "passed" and rep["after"]["verdict"] == "pass"
    job = json.loads((tmp_path / "wd" / "job.json").read_text())
    plan = job["segments"]["g000"]["plan"]
    seg = job["segments"]["g000"]["segment"]
    assert plan["start_s"] == seg["episode_start_s"] and plan["end_s"] == seg["episode_end_s"]


def test_heuristic_halves_alpha_after_failed_global_lowpass():
    h = HeuristicProvider()
    detail = {
        "id": "g000",
        "type": "general",
        "peak_flash_rate_hz": 12.5,
        "max_delta_L": 1.0,
        "max_area_fraction": 1.0,
        "parameter_hints": {"S1": {"alpha": 0.165}, "prefer_regional": False},
        "iterations_left_for_segment": 3,
        "attempts": [
            {
                "candidate_id": "g000-c1",
                "strategy": "S4",
                "params": {"base": "S1", "alpha": 0.165},
                "verified": {"passes_for_type": False},
            }
        ],
    }
    call = h._plan_from_detail(detail).tool_calls[0]
    assert call.name == "apply_remediation"
    assert call.input["strategy"] == "S4"
    assert call.input["params"] == {"base": "S1", "alpha": 0.083}
    # a second failure moves on to the next rung, which is S4 on an S2 base (not skipped)
    detail["attempts"].append(
        {
            "candidate_id": "g000-c2",
            "strategy": "S4",
            "params": {"base": "S1", "alpha": 0.083},
            "verified": {"passes_for_type": False},
        }
    )
    call = h._plan_from_detail(detail).tool_calls[0]
    assert call.input["strategy"] == "S4" and call.input["params"]["base"] == "S2"
