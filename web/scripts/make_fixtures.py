#!/usr/bin/env python3
"""Build web/src/fixtures/*.json from real steadyframe outputs.

    steadyframe analyze clip.mp4 --json analysis.json
    steadyframe fix clip.mp4 -o safe.mp4 --report report.json --workdir wd
    steadyframe analyze safe.mp4 --json after.json
    python3 scripts/make_fixtures.py NAME analysis.json after.json report.json wd [--approval]

Timeline and region series are downsampled (every STEP-th frame) to keep the files small.
--approval turns the run into a paused needs_approval job with a synthetic agent trace: the
first segment is kept as-is, the last segment gets two failed attempts and a pending S5
option. Shapes are copied from the real records so the UI sees the same field names.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

STEP = 3
OUT = Path(__file__).resolve().parent.parent / "src" / "fixtures"
CREATED = "2026-10-01T12:00:00Z"


def ds(xs, step=STEP):
    return xs[::step] if isinstance(xs, list) else xs


def scrub(o):
    """Replace host paths in the trace with a neutral work-dir path."""
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    if isinstance(o, str) and o.startswith("/"):
        return "/work/" + o.rsplit("/", 1)[-1]
    return o


def summary(an):
    return {
        "verdict": an["verdict"],
        "per_second": an["per_second"],
        "segments": an["segments"],
        "timeline": {k: ds(v) for k, v in an.get("timeline", {}).items()},
    }


def build(name, analysis_p, after_p, report_p, wd, approval=False):
    an = json.loads(Path(analysis_p).read_text())
    after = json.loads(Path(after_p).read_text())
    rep = json.loads(Path(report_p).read_text())
    wd = Path(wd)
    state = json.loads((wd / "job.json").read_text())
    records = [json.loads(l) for l in (wd / "trace.jsonl").read_text().splitlines() if l.strip()]
    job_id = f"fx-{name}"
    for r in records:
        r["job_id"] = job_id

    video = an["video"]
    job = {
        "job_id": job_id,
        "status": rep["status"],
        "created_at": CREATED,
        "updated_at": CREATED,
        "profile": an["profile"]["name"],
        "policy": rep["policy"],
        "conservative": bool(an["profile"].get("conservative", False)),
        "input": {
            "filename": Path(video["path"]).name,
            "width": video["width"],
            "height": video["height"],
            "fps": video["fps"],
            "duration_s": video["duration_s"],
            "has_audio": video.get("has_audio", False),
        },
        "progress": {"stage": "done", "detail": "", "fraction": 1.0},
        "before": summary(an),
        "after": summary(after),
        "remediation": {
            "status": rep["status"],
            "iterations": rep["iterations"],
            "runtime_s": rep["runtime_s"],
            "quality": rep.get("quality"),
            "segments": rep["segments"],
        },
        "pending_approvals": rep.get("pending_approvals", []),
        "downloads": {k: True for k in ("video", "report", "analysis", "trace", "plot", "summary")},
        "error": None,
        "tool": {"version": rep["tool"]["version"], "opencv": rep["tool"]["opencv"]["version"]},
    }

    rem_by_id = {s["segment_id"]: s for s in rep["segments"]}
    segments = []
    for seg in an["segments"]:
        st = state["segments"].get(seg["id"], {})
        segments.append(
            {
                **seg,
                "region_series": {
                    "t": ds(st.get("region_series_t", [])),
                    "L": ds(st.get("region_series", [])),
                },
                "remediation": rem_by_id.get(seg["id"]),
            }
        )

    if approval:
        job, segments, records = make_approval(job, segments, records)

    (OUT / f"job_{name}.json").write_text(json.dumps(job, indent=1) + "\n")
    (OUT / f"segments_{name}.json").write_text(json.dumps({"segments": segments}, indent=1) + "\n")
    (OUT / f"trace_{name}.json").write_text(
        json.dumps({"records": scrub(records), "complete": True}, indent=1) + "\n"
    )
    print(name, job["status"], len(segments), "segments", len(records), "trace records")


def make_approval(job, segments, records):
    """Turn a passed fixed-policy run into a paused agent run on its last segment."""
    job = copy.deepcopy(job)
    segments = copy.deepcopy(segments)
    job["status"] = "needs_approval"
    job["policy"] = "agent"
    job["progress"] = {
        "stage": "needs_approval",
        "detail": "waiting for a human decision on segment %s" % segments[-1]["id"],
        "fraction": 0.8,
    }
    job["after"] = None
    job["downloads"] = {k: k in ("analysis", "trace") for k in job["downloads"]}
    last = segments[-1]
    sid = last["id"]
    rem = last["remediation"]
    q1 = dict(rem["quality"])
    # attempt 1: S1 with default alpha still fails; attempt 2: S2 fails; attempt 3: S5 passes
    # but its SSIM sits below the approval threshold, so the agent asks a human.
    q_s2 = {**q1, "ssim_overall": 0.912, "ssim_inside": 0.71, "mean_abs_dL_inside": 0.16}
    q_s5 = {**q1, "ssim_overall": 0.874, "ssim_inside": 0.62, "mean_abs_dL_inside": 0.21,
            "temporal_step_after": 0.004, "temporal_smoothness_gain": 31.7}
    attempts = [
        {"candidate_id": f"{sid}-c1", "strategy": "S1", "params": {"alpha": 0.1},
         "verified": {"passes_for_type": False, "verdict": "fail", "ssim_overall": q1["ssim_overall"], "requires_approval": False}},
        {"candidate_id": f"{sid}-c2", "strategy": "S2", "params": {"max_delta": 0.08},
         "verified": {"passes_for_type": False, "verdict": "fail", "ssim_overall": q_s2["ssim_overall"], "requires_approval": False}},
        {"candidate_id": f"{sid}-c3", "strategy": "S5", "params": {"max_rate_hz": 2.0},
         "verified": {"passes_for_type": True, "verdict": "pass", "ssim_overall": q_s5["ssim_overall"], "requires_approval": True}},
    ]
    option = {"candidate_id": f"{sid}-c3", "strategy": "S5", "params": {"max_rate_hz": 2.0}, "quality": q_s5, "passes": True}
    reason = "S5: ssim 0.874 below 0.90"
    approval = {"segment_id": sid, "reason": reason, "options": [option], "last_resort": False,
                "requested_at": 1759320045.0, "decision": None}
    rem.update({"outcome": "pending_approval", "strategy": None, "params": {}, "attempts": attempts,
                "approval": approval, "quality": None})
    job["remediation"]["segments"][-1] = rem
    job["remediation"]["status"] = "needs_approval"
    job["remediation"]["iterations"] = 4
    job["remediation"]["quality"] = None
    job["pending_approvals"] = [{"segment_id": sid, "reason": reason, "options": [option], "last_resort": False}]

    # Rebuild the trace: keep everything up to the last segment's get_segment_detail result,
    # then splice in the agent's attempts.
    cut = max(i for i, r in enumerate(records)
              if r["kind"] == "tool_result" and r["name"] == "get_segment_detail"
              and r["result"].get("id") == sid)
    base = copy.deepcopy(records[: cut + 1])
    for r in base:
        if r.get("by") == "fixed":
            r["by"] = "agent"
    seq = base[-1]["seq"]
    t = base[-1]["t_rel_s"]
    ts = base[-1]["ts"]
    it = base[-1].get("iteration", 1) or 1
    out = base

    def rec(kind, name, dt, **fields):
        nonlocal seq, t
        seq += 1
        t = round(t + dt, 3)
        out.append({"seq": seq, "job_id": job["job_id"], "t_rel_s": t, "ts": ts, "kind": kind, "name": name, **fields})

    detail = records[cut]["result"]
    seg_summary = f"{detail['type']} {detail['peak_flash_rate_hz']}Hz area {detail['max_area_fraction']} dL {detail['max_delta_L']}"

    def model_turn(text, tool, args, dt=0.9):
        rec("model", "turn", dt, iteration=it, by="agent",
            model="bedrock model id from config",
            input_tokens=1840 + 210 * it, output_tokens=96,
            text=text, tool_use={"name": tool, "input": args})

    def apply_verify(cid, strategy, params, q, passes, reason, remaining, requires_approval=False, approval_reason=None):
        nonlocal it
        rec("tool_call", "apply_remediation", 0.01, args={"segment_id": sid, "strategy": strategy, "params": params}, iteration=it, by="agent")
        rec("tool_result", "apply_remediation", 1.2, result={"candidate_id": cid, "segment_id": sid, "strategy": strategy, "params": params,
            "scope": "regional", "range_s": [round(last["start_s"] - 0.5, 4), round(last["end_s"] + 0.5, 4)], "quality": q}, error=None, iteration=it)
        it += 1
        rec("tool_call", "verify_candidate", 0.01, args={"candidate_id": cid}, iteration=it, by="agent")
        rec("tool_result", "verify_candidate", 0.4, result={"candidate_id": cid, "verdict": "pass" if passes else "fail",
            "passes_for_type": passes, "remaining_same_type": remaining, "remaining_other_types": [], "quality": q,
            "requires_approval": requires_approval, "approval_reason": approval_reason, "reason": reason, "opencv": job["tool"]["opencv"]},
            error=None, iteration=it)

    remaining1 = [{"id": sid, "type": detail["type"], "verdict": "fail", "start_s": last["start_s"], "end_s": last["end_s"],
                   "peak_flash_rate_hz": 4.5, "max_area_fraction": detail["max_area_fraction"], "max_delta_L": 0.19}]
    remaining2 = [{**remaining1[0], "peak_flash_rate_hz": 3.5, "max_delta_L": 0.12}]

    model_turn(f"Segment {sid}: {seg_summary}. Region covers {detail['region_area_fraction_of_frame']:.0%} of the frame. "
               "Start with the least invasive strategy, S1 temporal low-pass at the default alpha.",
               "apply_remediation", {"segment_id": sid, "strategy": "S1", "params": {}})
    apply_verify(f"{sid}-c1", "S1", {"alpha": 0.1}, q1, False,
                 f"still failing: {detail['type']} 4.5Hz area {detail['max_area_fraction']}", remaining1)
    model_turn("verify_candidate reports the region still flashes at 4.5 Hz over the full window, so smoothing alone is "
               "not enough at this rate. Escalate to S2 luminance swing compression, clamping the per-frame delta to 0.08.",
               "apply_remediation", {"segment_id": sid, "strategy": "S2", "params": {"max_delta": 0.08}})
    apply_verify(f"{sid}-c2", "S2", {"max_delta": 0.08}, q_s2, False,
                 f"still failing: {detail['type']} 3.5Hz area {detail['max_area_fraction']}", remaining2)
    model_turn("Rate dropped to 3.5 Hz but the profile allows at most 3 flashes per second, and SSIM inside the region is "
               "already 0.71. Two iterations left. S5 frame-hold at 2 Hz will cap the rate directly; it is more visible, "
               "so expect an approval request if quality drops below the threshold.",
               "apply_remediation", {"segment_id": sid, "strategy": "S5", "params": {"max_rate_hz": 2.0}})
    apply_verify(f"{sid}-c3", "S5", {"max_rate_hz": 2.0}, q_s5, True,
                 f"no remaining {detail['type']} hazard in the re-analysed segment", [],
                 requires_approval=True, approval_reason="ssim 0.874 below 0.90")
    model_turn("Verification passes but overall SSIM is 0.874, below the 0.90 approval threshold. Pause and ask a human "
               "whether the frame-hold candidate is acceptable.",
               "request_human_approval", {"segment_id": sid, "reason": reason, "options": [option]})
    rec("tool_call", "request_human_approval", 0.01,
        args={"segment_id": sid, "reason": reason, "options": [option], "last_resort": False}, iteration=it, by="agent")
    rec("decision", "paused", 0.002, segment_id=sid, reason=reason)
    rec("job", "paused", 0.001, status="needs_approval", pending=[sid])
    return job, segments, out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 5:
        sys.exit(__doc__)
    build(*args, approval="--approval" in sys.argv)
