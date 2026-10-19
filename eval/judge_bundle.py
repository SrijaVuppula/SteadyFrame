"""Recorded jobs and headline numbers for the judge page (web /judge).

    python -m eval.judge_bundle [--offline]

Runs three clips through the same code the deployed worker runs (``service.core.Api`` and
``service.worker.JobRunner`` on the local store and queue), then copies each job's real
outputs into ``web/public/judge/<case>/`` so the page loads instantly, with no worker and no
cold start:

    jd-live        m_two_segments.mp4     policy agent (Bedrock), two regional hazards
    jd-escalation  r_red_to_white.mp4     fixed policy, every escalation caused by a verify
    jd-approval    r_red_strobe_full.mp4  policy agent; pauses for a human, then resumes
                                          (jd-approval-done is the same job after "approve")

The agent cases need AWS credentials and STEADYFRAME_BEDROCK_MODEL_ID. With ``--offline``
they run on the heuristic stand-in instead, and the page says so. Hazardous inputs are never
copied: only stills, plots, the remediated video (a ``passed`` output), the verification
record, the warning track, the report and the trace.

``web/public/judge/index.json`` also carries the headline results, read from
``eval/results/frozen/`` (and ``bench/results/``) by the same lookup the report uses, each
with the file it came from.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from steadyframe import opencv_build_summary

from .common import DATA, ROOT, git_rev
from .report import lookup

OUT = ROOT / "web" / "public" / "judge"
FROZEN = ROOT / "eval" / "results" / "frozen"
BENCH = ROOT / "bench" / "results"

CASES = [
    {
        "id": "jd-live",
        "clip": "m_two_segments.mp4",
        "policy": "agent",
        "title": "Two hazards, fixed where they are",
        "blurb": "Two flashing regions, 6 and 10 flashes a second. The model reads the "
        "measurements, picks a regional temporal low-pass with a strength computed from the "
        "measured swing, and the analyzer re-checks each candidate before it can be accepted.",
    },
    {
        "id": "jd-adapt",
        "clip": "r_red_strobe_full.mp4",
        "policy": "agent",
        "title": "The check fails, so the model changes its plan",
        "blurb": "A full-frame red strobe. The first fix comes back from the analyzer as still "
        "failing at 5.5 flashes a second; the model lowers the filter strength in response and "
        "the next candidate passes.",
    },
    {
        "id": "jd-approval",
        "clip": "r_red_strobe_full.mp4",
        "policy": "fixed",
        "title": "Stops and asks a person",
        "blurb": "The same clip under the deterministic policy: the candidate that passes changes "
        "the picture too much to accept automatically, so the job pauses until a person approves "
        "or rejects it. Both outcomes are recorded.",
    },
]

FILES = (
    "safe.mp4",
    "record.html",
    "record.json",
    "hazards.vtt",
    "plot.png",
    "summary.html",
    "report.json",
    "trace.jsonl",
)

# (label, lookup path, format, source file) -- every number on the judge page
RESULTS = [
    ("Synthetic clips with the right verdict", "detection.clip_accuracy", "of:detection.n_clips", "detection"),
    ("Boundary cases right (3 vs 3.5 vs 4 Hz, 0.09 vs 0.11 swing, 24% vs 26% area, ...)",
     "detection.boundary_correct/detection.boundary_total", "ratio", "detection"),
    ("Per-second F1 against independent ground truth", "detection.per_second.f1", "3f", "detection"),
    ("H.264 re-encodes (CRF 28 and 35) keeping their verdict",
     "robustness_summary.crf_correct/robustness_summary.crf_total", "ratio", "robustness_summary"),
    ("Third-party clips with the right verdict (EA IRIS, Apple, Intel camera footage)",
     "external.by_profile.wcag.clip_agreement/external.n_clips", "ratio", "external"),
    ("EA IRIS test videos where we match IRIS's own expected verdict",
     "external.by_profile.broadcast.iris_agreement/external.by_profile.broadcast.iris_clips",
     "ratio", "external"),
    ("Seconds of calm camera footage wrongly flagged",
     "external.by_profile.wcag.control_fp_seconds/external.by_profile.wcag.control_seconds",
     "ratio", "external"),
    ("Hazardous clips fixed and passing whole-file re-verification (fixed policy)",
     "remediation.passed/remediation.n_clips", "ratio", "remediation"),
    ("Live Bedrock agent: clips fixed", "agent_vs_fixed_bedrock.agent.passed/agent_vs_fixed_bedrock.agent.n_clips",
     "ratio", "agent_vs_fixed_bedrock"),
    ("Attempts per hazard: live Bedrock agent vs fixed policy",
     "agent_vs_fixed_bedrock.agent.mean_iterations_per_segment|agent_vs_fixed_bedrock.fixed.mean_iterations_per_segment",
     "vs2f", "agent_vs_fixed_bedrock"),
    ("Picture kept inside the hazard region, SSIM: agent vs fixed",
     "agent_vs_fixed_bedrock.agent.mean_ssim_inside|agent_vs_fixed_bedrock.fixed.mean_ssim_inside",
     "vs3f", "agent_vs_fixed_bedrock"),
    ("Model cost for the whole 25-clip suite (USD)", "agent_vs_fixed_bedrock.cost_usd", "2f",
     "agent_vs_fixed_bedrock"),
    ("Hostile-planner attacks held / false passes", "guardrails.summary.held/guardrails.summary.runs",
     "ratio", "guardrails"),
]  # fmt: skip

LIMITS = [
    "It checks published thresholds as implemented here; a pass is not a certification and not "
    "medical advice. Threshold tests have known misses: a 2024 UK TV ad that passed the Harding "
    "test was still pulled after viewers reported seizures.",
    "Luminance is relative to peak white (sRGB curve). On the Ofcom note's reference display "
    "(gamma 2.2, 200 cd/m² peak white) its 20 and 160 cd/m² limits are exactly our 0.10 and "
    "0.80; a brighter real display is not modelled.",
    "The area rule runs on a 64x48 grid, so a hazard right at the 25% boundary can flip with "
    "grid size (1 of 28 boundary clips at some grid sizes).",
    "A full-frame strobe has no regional fix: the repair has to change the whole picture, and "
    "when it changes it too much the job waits for a person.",
    "The pattern detector (regular stripes) is experimental and off by default; the WCAG "
    "exemption for fine balanced patterns is not implemented, so it over-flags rather than "
    "under-flags.",
    "External ground truth is small: 18 third-party clips, no labelled concert or emergency-vehicle "
    "footage yet.",
]


def _value(data: dict, expr: str, fmt: str):
    if "|" in expr:
        a, b = (lookup(data, x) for x in expr.split("|"))
        d = 2 if fmt == "vs2f" else 3
        return {"a": a, "b": b, "text": f"{a:.{d}f} vs {b:.{d}f}"}
    if fmt.startswith("of:"):
        v, n = lookup(data, expr), lookup(data, fmt[3:])
        return {"a": v, "b": n, "text": f"{round(v * n)}/{n}"}
    if "/" in expr:
        a, b = (lookup(data, x) for x in expr.split("/"))
        if expr.startswith("guardrails"):
            fp = lookup(data, "guardrails.summary.false_pass")
            return {"a": a, "b": b, "text": f"{a}/{b} held, {fp} false passes"}
        return {"a": a, "b": b, "text": f"{a}/{b}"}
    v = lookup(data, expr)
    text = {"pct": f"{v:.0%}", "3f": f"{v:.3f}", "2f": f"{v:.2f}"}.get(fmt, str(v))
    return {"a": v, "text": text}


def headline_results() -> list[dict]:
    data: dict = {}
    for p in list(FROZEN.glob("*.json")) + list(BENCH.glob("*.json")):
        try:
            data[p.stem.replace("-", "_")] = json.loads(p.read_text())
        except Exception:
            pass
    rows = []
    for label, expr, fmt, src in RESULTS:
        try:
            v = _value(data, expr, fmt)
        except Exception:
            continue  # not run yet; the page shows only what exists
        rows.append(
            {
                "label": label,
                **v,
                "source": f"eval/results/frozen/{src}.json"
                if (FROZEN / f"{src}.json").exists()
                else f"bench/results/{src}.json",
            }
        )
    return rows


def guardrail_rows() -> dict | None:
    p = FROZEN / "guardrails.json"
    if not p.exists():
        return None
    g = json.loads(p.read_text())
    keep = (
        "attack",
        "what",
        "refused",
        "fallback",
        "status",
        "fresh_verdict",
        "held",
        "false_pass",
    )
    return {"summary": g["summary"], "rows": [{k: r.get(k) for k in keep} for r in g["rows"]]}


# ---------------------------------------------------------------- running the worker


_ABS = re.compile(r"^/(?:[^/\s]+/)+")


def scrub(o, job_id: str, case: str):
    """Host paths out, stable ids in: absolute paths keep only their file name."""
    if isinstance(o, dict):
        return {k: scrub(v, job_id, case) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v, job_id, case) for v in o]
    if isinstance(o, str):
        o = o.replace(job_id, case)
        if _ABS.match(o):
            return "/work/" + o.rstrip("/").rsplit("/", 1)[-1]
    return o


def run_case(case: dict, ctx, offline: bool) -> list[tuple[str, dict, Path]]:
    """Returns [(case id, exported job, outputs dir)] -- two entries for the approval case."""
    from service import core
    from service.worker import JobRunner

    api = core.Api(ctx)
    clip = DATA / case["clip"]
    if not clip.exists():
        raise SystemExit(f"{clip} missing; run `make synth` first")
    data = clip.read_bytes()
    created = api.create_job(
        {
            "filename": case["clip"],
            "content_type": "video/mp4",
            "size_bytes": len(data),
            "profile": "wcag",
            "policy": case["policy"],
        }
    )
    job_id = created["job_id"]
    api.upload(job_id, data, "video/mp4")
    api.start(job_id)
    runner = JobRunner(ctx)
    runner.run(job_id)
    exports = [(case["id"], export(api, ctx, job_id, case["id"]))]
    job = api.get_job(job_id)
    if job["status"] == "needs_approval":
        pending = job["pending_approvals"][0]
        opts = pending.get("options") or []
        paused = Path(ctx.data_dir)
        for approved, suffix in ((True, "-done"), (False, "-rejected")):
            # each decision resumes its own copy of the same paused job
            root = paused.parent / f"{paused.name}{suffix}"
            shutil.rmtree(root, ignore_errors=True)
            shutil.copytree(paused, root)
            c2 = type(ctx).local(root, ctx.approval_min_ssim)
            a2 = core.Api(c2)
            a2.approve(
                job_id,
                {
                    "segment_id": pending["segment_id"],
                    "approved": approved,
                    **({"candidate_id": opts[0]["candidate_id"]} if opts else {}),
                },
            )
            JobRunner(c2).run(job_id)
            exports.append((case["id"] + suffix, export(a2, c2, job_id, case["id"] + suffix)))
    return exports


def export(api, ctx, job_id: str, case_id: str) -> dict:
    job = api.get_job(job_id)
    segs = api.segments(job_id)
    trace = api.trace(job_id, 0)
    d = OUT / case_id
    shutil.rmtree(d, ignore_errors=True)
    (d / "stills").mkdir(parents=True, exist_ok=True)
    store = ctx.store
    present = set()
    for name in FILES:
        key = f"outputs/{job_id}/{name}"
        if not store.exists(key):
            continue
        if name == "safe.mp4" and job["status"] != "passed":
            continue  # only a verified output is ever bundled
        store.get_file(key, d / name)
        present.add(name)
    for key in store.list(f"outputs/{job_id}/stills/"):
        store.get_file(key, d / "stills" / Path(key).name)
    for name in ("trace.jsonl", "report.json", "record.json"):
        p = d / name
        if p.exists():
            if name.endswith(".jsonl"):
                lines = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
                p.write_text("".join(json.dumps(scrub(r, job_id, case_id)) + "\n" for r in lines))
            else:
                p.write_text(
                    json.dumps(scrub(json.loads(p.read_text()), job_id, case_id), indent=1)
                )
    for name in ("record.html", "summary.html"):
        p = d / name
        if p.exists():
            p.write_text(p.read_text().replace(job_id, case_id))
    from service.core import DOWNLOAD_KINDS

    kind_for = {fname: k for k, (fname, _ct) in DOWNLOAD_KINDS.items()}
    job = scrub(job, job_id, case_id)
    job["downloads"] = {kind_for[n]: True for n in present if n in kind_for}
    job["downloads"]["input"] = False  # hazardous originals are never bundled
    (d / "job.json").write_text(json.dumps(job, indent=1) + "\n")
    (d / "segments.json").write_text(json.dumps(scrub(segs, job_id, case_id), indent=1) + "\n")
    (d / "trace.json").write_text(
        json.dumps({"records": scrub(trace["records"], job_id, case_id), "complete": True}) + "\n"
    )
    return job


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="heuristic stand-in instead of Bedrock")
    ap.add_argument("--only", default=None, help="record only the cases whose id contains this")
    ap.add_argument(
        "--index-only",
        action="store_true",
        help="keep the recorded jobs, refresh the headline numbers in index.json",
    )
    args = ap.parse_args(argv)
    if args.index_only:
        index = json.loads((OUT / "index.json").read_text())
        index.update(
            results=headline_results(), guardrails=guardrail_rows(), limits=LIMITS, git=git_rev()
        )
        (OUT / "index.json").write_text(json.dumps(index, indent=1) + "\n")
        print(f"refreshed {OUT.relative_to(ROOT)}/index.json")
        return 0
    if not args.offline and not os.environ.get("STEADYFRAME_BEDROCK_MODEL_ID"):
        raise SystemExit("set STEADYFRAME_BEDROCK_MODEL_ID (and AWS credentials) or pass --offline")
    from service.core import Context

    OUT.mkdir(parents=True, exist_ok=True)
    cases_out = []
    with tempfile.TemporaryDirectory(prefix="sf-judge-") as td:
        os.environ.setdefault("WORKER_WORKDIR", str(Path(td) / "jobs"))
        if args.offline:
            # the worker calls fix_file(policy="agent") with no provider (= Bedrock); hand it
            # the heuristic stand-in instead
            import functools

            from steadyframe.agent.providers import HeuristicProvider
            from steadyframe.remediate import pipeline

            orig = pipeline.fix_file
            pipeline.fix_file = functools.wraps(orig)(
                lambda *a, **kw: orig(*a, provider=HeuristicProvider(), **kw)
            )
        for case in CASES:
            if args.only and args.only not in case["id"]:
                continue
            # one store per case so each approval branch copies only its own job
            ctx = Context.local(Path(td) / f"svc-{case['id']}")
            t0 = time.perf_counter()
            for cid, job in run_case(case, ctx, args.offline):
                rem = job.get("remediation") or {}
                tr = json.loads((OUT / cid / "trace.json").read_text())["records"]
                llm_turns = sum(1 for r in tr if r["kind"] == "model")
                cases_out.append(
                    {
                        "id": cid,
                        "clip": case["clip"],
                        "title": case["title"]
                        if cid == case["id"]
                        else "After approval"
                        if cid.endswith("-done")
                        else "After rejection",
                        "blurb": case["blurb"],
                        "policy": job.get("policy"),
                        "planner": rem.get("policy"),
                        "status": job["status"],
                        "verdict_before": (job.get("before") or {}).get("verdict"),
                        "verdict_after": (job.get("after") or {}).get("verdict"),
                        "segments": len((job.get("before") or {}).get("segments") or []),
                        "iterations": rem.get("iterations"),
                        "model_turns": llm_turns,
                        "files": sorted(p.name for p in (OUT / cid).iterdir() if p.is_file()),
                    }
                )
                print(
                    f"{cid:20s} {job['status']:16s} planner={rem.get('policy')} turns={llm_turns}"
                )
            print(f"  ({time.perf_counter() - t0:.1f} s)")
    if args.only and (OUT / "index.json").exists():
        # keep the recordings of the cases not re-run
        old = json.loads((OUT / "index.json").read_text())
        new_ids = {c["id"] for c in cases_out}
        keep = [c for c in old.get("cases", []) if c["id"] not in new_ids]
        order = {c["id"]: i for i, c in enumerate(CASES)}
        cases_out = sorted(
            keep + cases_out,
            key=lambda c: (order.get(c["id"].split("-done")[0].split("-rejected")[0], 99), c["id"]),
        )
    ob = opencv_build_summary()
    index = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git": git_rev(),
        "opencv": ob["version"],
        "offline": args.offline,
        "cases": cases_out,
        "results": headline_results(),
        "guardrails": guardrail_rows(),
        "limits": LIMITS,
    }
    (OUT / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}/index.json with {len(cases_out)} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
