import json

import pytest

from steadyframe.agent.tools import Job, ToolError
from steadyframe.remediate.pipeline import fix_file
from steadyframe.schema import validate_report

from .conftest import square_frames


def test_fix_passes_and_writes_report_and_trace(tmp_clip, tmp_path):
    # hi=200 keeps the swing at ~0.56 so S1's default alpha lands well under the 0.10
    # threshold on every platform (with hi=230 the residual is exactly 0.10 and the arm64
    # ffmpeg build tipped it over, sending the policy to S2)
    frames = square_frames(
        120, 30, 6.0, hi=(200, 200, 200), size=(96, 72), region=(24, 18, 72, 54), start=1.0
    )
    src = tmp_clip(frames, codec="h264")
    out = tmp_path / "safe.mp4"
    rep = fix_file(
        src,
        out,
        report_path=tmp_path / "r.json",
        workdir=tmp_path / "wd",
        plot_path=tmp_path / "p.png",
    )
    validate_report(rep)
    assert rep["status"] == "passed" and rep["after"]["verdict"] == "pass"
    assert rep["segments"][0]["outcome"] == "accepted" and rep["segments"][0]["strategy"] == "S1"
    assert rep["quality"]["ssim_outside"] > 0.99
    lines = (tmp_path / "wd" / "trace.jsonl").read_text().splitlines()
    kinds = [json.loads(line)["name"] for line in lines]
    assert kinds[:2] == ["analyze_video", "analyze_video"]
    assert "verify_candidate" in kinds and "accept_candidate" in kinds and "finalize" in kinds
    assert (tmp_path / "p.png").exists()


def test_no_hazards_copies_input(tmp_clip, tmp_path):
    src = tmp_clip(square_frames(60, 30, 1.0))
    rep = fix_file(src, tmp_path / "o.mp4", workdir=tmp_path / "wd")
    assert rep["status"] == "no_hazards" and rep["iterations"] == 0
    assert (tmp_path / "o.mp4").stat().st_size == src.stat().st_size


def test_approval_pause_and_resume(tmp_clip, tmp_path):
    src = tmp_clip(square_frames(90, 30, 6.0, start=0.5), codec="h264")
    wd = tmp_path / "wd"
    # every candidate needs approval when the ssim bar is impossible
    rep = fix_file(src, tmp_path / "o.mp4", workdir=wd, approval_min_ssim=1.01)
    assert rep["status"] == "needs_approval"
    pend = rep["pending_approvals"]
    assert len(pend) == 1 and len(pend[0]["options"]) == 1
    sid = pend[0]["segment_id"]
    first = pend[0]["options"][0]
    assert (wd / "job.json").exists()
    # resume with a rejection: the policy moves on to the next strategy and asks again
    rep2 = fix_file(
        src,
        tmp_path / "o.mp4",
        workdir=wd,
        approval_min_ssim=1.01,
        decisions={sid: {"approved": False}},
    )
    assert rep2["status"] == "needs_approval"
    second = rep2["pending_approvals"][0]["options"][0]
    assert second["candidate_id"] != first["candidate_id"]
    assert second["strategy"] != first["strategy"]
    # resume with approval of the offered candidate
    rep3 = fix_file(
        src,
        tmp_path / "o.mp4",
        workdir=wd,
        approval_min_ssim=1.01,
        decisions={sid: {"approved": True, "candidate_id": second["candidate_id"]}},
    )
    assert rep3["status"] == "passed"
    assert rep3["segments"][0]["strategy"] == second["strategy"]
    assert rep3["segments"][0]["approval"]["decision"]["approved"] is True


def test_approve_all_flag(tmp_clip, tmp_path):
    src = tmp_clip(square_frames(90, 30, 6.0, start=0.5), codec="h264")
    rep = fix_file(
        src, tmp_path / "o.mp4", workdir=tmp_path / "wd", approval_min_ssim=1.01, approve_all=True
    )
    assert rep["status"] == "passed"
    assert rep["segments"][0]["approval"]["decision"]["by"] == "approve_all"


def test_tool_errors_are_reported_not_raised_as_crashes(tmp_clip, tmp_path):
    src = tmp_clip(square_frames(90, 30, 6.0, start=0.5), codec="h264")
    job = Job(src, tmp_path / "wd", max_iterations_per_segment=1)
    job.analyze_video()
    sid = job.open_segments()[0]
    with pytest.raises(ToolError):
        job.get_segment_detail("nope")
    with pytest.raises(ToolError):
        job.apply_remediation(sid, "S9")
    with pytest.raises(ToolError):
        job.apply_remediation(sid, "S3")  # red-only strategy on a general hazard
    c = job.apply_remediation(sid, "S1", {"alpha": 0.5})  # too weak on purpose
    with pytest.raises(ToolError):
        job.accept_candidate(c["candidate_id"])  # not verified yet
    v = job.verify_candidate(c["candidate_id"])
    assert v["passes_for_type"] is False
    with pytest.raises(ToolError):
        job.accept_candidate(c["candidate_id"])
    with pytest.raises(ToolError):  # budget of 1 attempt is spent
        job.apply_remediation(sid, "S1", {"alpha": 0.05})
    errors = [r for r in job.trace.records if r.get("error")]
    assert len(errors) >= 5


def test_parameter_hints_scale_with_measurements():
    from steadyframe.agent.tools import parameter_hints
    from steadyframe.profiles import get_profile

    p = get_profile("wcag")
    mild = parameter_hints(
        {
            "max_delta_L": 0.15,
            "peak_flash_rate_hz": 4.0,
            "max_area_fraction": 0.5,
            "regions": [{"x": 0, "y": 0, "w": 0.3, "h": 0.3}],
        },
        p,
        30,
    )
    harsh = parameter_hints(
        {
            "max_delta_L": 0.9,
            "peak_flash_rate_hz": 12.0,
            "max_area_fraction": 1.0,
            "regions": [{"x": 0, "y": 0, "w": 1, "h": 1}],
        },
        p,
        30,
    )
    assert mild["S1"]["alpha"] > harsh["S1"]["alpha"]
    assert mild["prefer_regional"] and not harsh["prefer_regional"]
