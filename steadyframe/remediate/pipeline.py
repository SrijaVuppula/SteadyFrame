"""`steadyframe fix`: analyze -> remediate each hazard segment -> verify -> final render ->
whole-file re-verification -> report."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from ..agent.tools import ApprovalPending, Job
from ..schema import validate_report


def fix_file(
    src: str | Path,
    dst: str | Path,
    *,
    policy: str = "fixed",
    profile: str = "wcag",
    report_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    workdir: str | Path | None = None,
    max_iterations: int = 4,
    max_iterations_total: int = 24,
    approve_all: bool = False,
    decisions: dict | None = None,
    plot_path: str | Path | None = None,
    provider=None,
    keep_workdir: bool | None = None,
    approval_min_ssim: float = 0.75,
    detect_patterns: bool = False,
) -> dict:
    t0 = time.perf_counter()
    tmp = None
    if workdir is None:
        tmp = tempfile.mkdtemp(prefix="steadyframe-")
        workdir = tmp
    workdir = Path(workdir)
    if keep_workdir is None:
        keep_workdir = tmp is None
    from ..agent.trace import Trace

    trace = Trace(trace_path or workdir / "trace.jsonl")
    job = Job(
        src,
        workdir,
        profile=profile,
        max_iterations_per_segment=max_iterations,
        max_iterations_total=max_iterations_total,
        trace=trace,
        decisions=decisions,
        approve_all=approve_all,
        approval_min_ssim=approval_min_ssim,
        detect_patterns=detect_patterns,
    )
    used_policy = policy
    error = None
    try:
        summary = job.analyze_video()
        if summary["verdict"] != "fail" and not job.open_segments():
            job.finalize(dst, plot_path=plot_path)
        else:
            if policy == "agent":
                from ..agent.loop import run_agent

                used_policy = run_agent(job, provider=provider)
            else:
                from ..agent.policy_fixed import run_fixed_policy

                run_fixed_policy(job)
            job.finalize(dst, plot_path=plot_path)
    except ApprovalPending as p:
        job.trace.decision("paused", segment_id=p.segment_id, reason=p.request["reason"])
        job.state["status"] = "needs_approval"
        job.save()
    except Exception as e:  # report it, never lose the trace
        error = f"{type(e).__name__}: {e}"
        job.trace.log("error", "pipeline", error=error)
        job.save()
    report = job.report(used_policy, time.perf_counter() - t0, error=error)
    report["workdir"] = str(workdir)
    validate_report(report)
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(json.dumps(report, indent=2, default=str))
    if tmp and not keep_workdir and report["status"] != "needs_approval":
        shutil.rmtree(tmp, ignore_errors=True)
    return report
