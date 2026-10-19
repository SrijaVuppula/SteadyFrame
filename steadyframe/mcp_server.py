"""SteadyFrame as an MCP server: bring your own agent.

The seven tools the built-in planner calls (``steadyframe.agent.tools.Job``) are served over the
Model Context Protocol with the same guardrails, because they are the same code: the OpenCV 5
analyzer re-checks every candidate, ``accept_candidate`` refuses unverified, failing or
unapproved candidates, ``finalize`` refuses while a segment is open, the attempt budgets are
counted by the tools, and the agent is shown measurements only, never pixels.

A human decision cannot come from the agent. ``request_human_approval`` asks the person at the
client through MCP elicitation and records their answer; a client that cannot ask leaves the
segment waiting. One more tool, ``run_on_aws``, hands a whole file to the deployed pipeline.

    steadyframe mcp                  # stdio, for Kiro, Codex, VS Code or any MCP client
    steadyframe mcp --http 8765      # streamable HTTP on 127.0.0.1:8765/mcp
"""

from __future__ import annotations

import functools
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Literal

import anyio
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from .agent.loop import system_prompt
from .agent.tools import ApprovalPending, Job, ToolError
from .agent.trace import Trace
from .remediate.registry import SPECS

BY = "mcp"  # how the external agent's calls are labelled in the trace
DEFAULT_API = "https://d25yofo4x3sac8.cloudfront.net/api"
TERMINAL = {"passed", "failed_verification", "no_hazards", "error", "needs_approval"}

INSTRUCTIONS = """SteadyFrame checks a video for flashing that can trigger seizures (WCAG 2.3.1,
ITU-R BT.1702 / Ofcom), repairs only the flagged region and time, and proves the repair with the
same OpenCV 5 analyzer. Call analyze_video first; it returns a job_id. For each segment read
get_segment_detail, render a candidate with apply_remediation, check it with verify_candidate,
and accept_candidate only after a passing verify. If verify says requires_approval, call
request_human_approval: the person at this client answers, not you. finalize renders the whole
file, re-verifies it and writes a verification record. Use the prompt repair_video for the full
rules. Not a medical device: a pass means the published thresholds were met."""

# stdout is the protocol; the SDK logs every request on stderr at INFO, which is noise here
mcp = FastMCP("steadyframe", instructions=INSTRUCTIONS, log_level="WARNING")

_jobs: dict[str, Job] = {}
_started: dict[str, float] = {}


def _root() -> Path:
    base = os.environ.get("STEADYFRAME_MCP_DIR") or Path.home() / ".cache" / "steadyframe" / "mcp"
    return Path(base)


def _job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise ToolError(f"unknown job {job_id!r}; call analyze_video first")
    return job


def _plain(obj: Any) -> Any:
    """Tool results as plain JSON (numpy scalars and paths become numbers and strings)."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


async def _off(fn, *args, **kw):
    """Run analysis and rendering off the event loop, so the session keeps answering pings."""
    return _plain(await anyio.to_thread.run_sync(functools.partial(fn, *args, **kw)))


# ---------------------------------------------------------------- the seven tools


@mcp.tool()
async def analyze_video(path: str, profile: Literal["wcag", "broadcast"] = "wcag") -> dict:
    """Open a local video and run the OpenCV 5 photosensitivity analyzer on it.

    Returns a job_id for the other tools, the verdict (pass, warn or fail), the video's metadata,
    every hazard segment with its measurements (type, time range, peak flash rate, area
    fraction, luminance swing, regions, severity) and the catalogue of repair strategies.
    profile: wcag (WCAG 2.3.1, 25% of any 10-degree window) or broadcast (ITU-R BT.1702 /
    Ofcom, 25% of the screen)."""
    src = Path(path).expanduser()
    if not src.is_file():
        raise ToolError(f"no such file: {src}")
    job_id = uuid.uuid4().hex[:12]
    workdir = _root() / job_id
    job = Job(
        src.resolve(),
        workdir,
        profile=profile,
        job_id=job_id,
        trace=Trace(workdir / "trace.jsonl", job_id),
        approval_min_ssim=float(os.environ.get("STEADYFRAME_APPROVAL_MIN_SSIM", "0.75")),
    )
    _jobs[job_id] = job
    _started[job_id] = time.perf_counter()
    return await _off(job.analyze_video, by=BY)


@mcp.tool()
async def get_segment_detail(job_id: str, segment_id: str) -> dict:
    """Details for one hazard segment: its measurements, the region's luminance over time, the
    strategies that apply, parameter hints derived from the measured rate and swing, the
    attempts so far and the remaining attempt budget."""
    return await _off(_job(job_id).get_segment_detail, segment_id, by=BY)


@mcp.tool()
async def apply_remediation(
    job_id: str,
    segment_id: str,
    strategy: Literal["S1", "S2", "S3", "S4", "S5", "S6"],
    params: dict | None = None,
) -> dict:
    """Render a candidate fix for one segment with a strategy and its parameters (omit params
    for the defaults). Returns a candidate_id and quality metrics (SSIM inside and outside the
    regions, luminance change). Costs one attempt of the segment's budget of four."""
    return await _off(_job(job_id).apply_remediation, segment_id, strategy, params or {}, by=BY)


@mcp.tool()
async def verify_candidate(job_id: str, candidate_id: str) -> dict:
    """Re-run the analyzer on a candidate. Returns passes_for_type (the hazard is gone), any
    hazards that remain, quality metrics and requires_approval (true when the fix changes the
    picture too much to accept without a person)."""
    return await _off(_job(job_id).verify_candidate, candidate_id, by=BY)


class Decision(BaseModel):
    approve: bool = Field(description="Use this repair for the segment")


@mcp.tool()
async def request_human_approval(
    job_id: str, segment_id: str, candidate_id: str, reason: str, ctx: Context
) -> dict:
    """Ask the person using this client whether a verified candidate may be used. Needed for the
    warning card (S6) and for any fix that keeps less than 0.75 SSIM of the picture. The answer
    comes from the person, through the client; this tool cannot be answered by the agent. If
    the client cannot ask, the segment stays waiting and finalize reports needs_approval."""
    job = _job(job_id)
    st, rec = job._candidate(candidate_id)
    seg = st["segment"]
    q = rec.get("quality") or {}
    ssim = q.get("ssim_overall")
    name = f"{rec['strategy']} ({SPECS[rec['strategy']].name})"
    message = (
        f"SteadyFrame needs your decision on {seg['type']} flashing in {Path(job.video).name}, "
        f"{seg['start_s']:.2f}-{seg['end_s']:.2f} s. The only fix that passes is {name}"
        + (f", which keeps SSIM {ssim:.3f} of the picture (auto-accept needs 0.75)" if ssim else "")
        + f". The agent says: {reason[:300]}"
    )
    option = {"candidate_id": candidate_id, "strategy": rec["strategy"], "params": rec["params"]}
    try:
        answer = await ctx.elicit(message, Decision)
    except Exception as e:  # the client does not support elicitation
        return {
            "status": "pending_approval",
            "detail": f"this client cannot ask a person ({type(e).__name__}); the segment stays "
            "waiting and finalize will report needs_approval",
        }
    if answer.action == "cancel":
        try:
            job.request_human_approval(segment_id, reason, [option], by=BY)
        except ApprovalPending:
            pass
        return {"status": "pending_approval", "detail": "the person closed the question"}
    approved = answer.action == "accept" and bool(answer.data.approve)
    job.decisions[segment_id] = {
        "approved": approved,
        "candidate_id": candidate_id,
        "by": "person (MCP elicitation)",
    }
    return _plain(job.request_human_approval(segment_id, reason, [option], by=BY))


@mcp.tool()
async def accept_candidate(job_id: str, candidate_id: str) -> dict:
    """Accept a verified, passing candidate as the fix for its segment. Refused for a candidate
    that was not verified, did not pass, or needs a person's approval that was not given."""
    return await _off(_job(job_id).accept_candidate, candidate_id, by=BY)


@mcp.tool()
async def finalize(job_id: str, output_path: str | None = None) -> dict:
    """Render the whole video with every accepted fix, re-verify the whole file with the same
    analyzer and write the outputs: the repaired video, a verification record (JSON and a
    printable HTML: hashes, thresholds, every fix and decision) and a WebVTT warning track for
    the original. Refused while any segment is still open. output_path defaults to
    <input>.safe.mp4 next to the input."""
    job = _job(job_id)
    open_ = job.open_segments()
    if open_:
        job.trace.tool_call("finalize", {}, iteration=job.state["iterations"], by=BY)
        msg = f"segments still open: {', '.join(open_)}"
        job.trace.tool_result("finalize", {}, error=msg, iteration=job.state["iterations"])
        raise ToolError(msg)
    out = Path(output_path).expanduser() if output_path else job.video.with_suffix(".safe.mp4")
    res = await _off(job.finalize, out, by=BY)
    return await _off(_write_outputs, job, out, res)


def _write_outputs(job: Job, out: Path, res: dict) -> dict:
    from .record import build_record, hazard_vtt, write_record

    report = job.report("mcp", time.perf_counter() - _started.get(job.job_id, time.perf_counter()))
    stem = out.with_suffix("")
    record_json, record_html, vtt = (
        Path(f"{stem}.record.json"),
        Path(f"{stem}.record.html"),
        Path(f"{stem}.hazards.vtt"),
    )
    record = build_record(report, job.profile, job.video, out)
    write_record(record, record_json, record_html)
    vtt.write_text(hazard_vtt(report["before"].get("segments", [])))
    return {
        **res,
        "record": str(record_json),
        "record_html": str(record_html),
        "warnings_vtt": str(vtt),
        "record_digest": record.get("digest"),
        "trace": str(job.workdir / "trace.jsonl"),
    }


@mcp.tool()
async def verify_record(video_path: str, record_path: str) -> dict:
    """Check a verification record against a file: re-hash the file and re-run the analyzer.
    Anyone can run this; the record is a re-checkable claim, not a certificate."""
    from .record import verify_file

    record = json.loads(Path(record_path).expanduser().read_text())
    return await _off(verify_file, Path(video_path).expanduser(), record)


# ---------------------------------------------------------------- the deployed pipeline


def _http(method: str, url: str, body: Any = None, headers: dict | None = None) -> Any:
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body else None)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None and not isinstance(body, bytes):
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise ToolError(f"{method} {url.split('/api')[-1]}: HTTP {e.code} {detail}") from e
    return json.loads(raw) if raw else None


def _run_on_aws(path: Path, policy: str, profile: str, wait_s: float) -> dict:
    api = (os.environ.get("STEADYFRAME_API") or DEFAULT_API).rstrip("/")
    data = path.read_bytes()
    created = _http(
        "POST",
        f"{api}/jobs",
        {
            "filename": path.name,
            "content_type": "video/mp4" if path.suffix.lower() == ".mp4" else "",
            "size_bytes": len(data),
            "profile": profile,
            "policy": policy,
        },
    )
    up = created["upload"]
    _http(up.get("method", "PUT"), up["url"], data, up.get("headers") or {})
    job_id = created["job_id"]
    _http("POST", f"{api}/jobs/{job_id}/start")
    t0 = time.time()
    job = _http("GET", f"{api}/jobs/{job_id}")
    while job["status"] not in TERMINAL and time.time() - t0 < wait_s:
        time.sleep(2)
        job = _http("GET", f"{api}/jobs/{job_id}")
    site = api[: -len("/api")] if api.endswith("/api") else api
    return {
        "job_id": job_id,
        "status": job["status"],
        "policy": job.get("policy"),
        "notice": job.get("notice"),
        "before": (job.get("before") or {}).get("verdict"),
        "after": (job.get("after") or {}).get("verdict"),
        "segments": [
            {k: s.get(k) for k in ("id", "type", "start_s", "end_s", "peak_flash_rate_hz")}
            for s in (job.get("before") or {}).get("segments", [])
        ],
        "seconds": round(time.time() - t0, 1),
        "page": f"{site}/jobs/{job_id}",
    }


@mcp.tool()
async def run_on_aws(
    path: str,
    policy: Literal["fixed", "agent"] = "fixed",
    profile: Literal["wcag", "broadcast"] = "wcag",
    wait_s: float = 300,
) -> dict:
    """Send a whole file (up to 100 MB and 120 s) to the deployed SteadyFrame pipeline on AWS and
    wait for the result: the worker on AWS Lambda analyzes, repairs and re-verifies it, planned
    by the fixed policy or by the Amazon Bedrock model. Returns the verdicts, the segments and a
    link to the job page with its downloads. The upload is deleted after a day."""
    src = Path(path).expanduser()
    if not src.is_file():
        raise ToolError(f"no such file: {src}")
    return await _off(_run_on_aws, src, policy, profile, float(wait_s))


# ---------------------------------------------------------------- trace and instructions


@mcp.resource("steadyframe://jobs/{job_id}/trace")
def job_trace(job_id: str) -> str:
    """Every tool call, result and decision of a job, one JSON object per line."""
    p = _job(job_id).workdir / "trace.jsonl"
    return p.read_text() if p.exists() else ""


@mcp.prompt()
def repair_video(path: str, profile: str = "wcag") -> str:
    """The planner's instructions, as the built-in agent gets them, for one file."""
    return (
        system_prompt(profile)
        + "\n\nWith these MCP tools every call after analyze_video takes the job_id it returns, "
        "and request_human_approval takes one candidate_id; the person at the client answers it."
        + f"\n\nThe file: {path}"
    )


def serve(http_port: int | None = None) -> None:
    if http_port:
        mcp.settings.port = http_port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


__all__ = ["mcp", "serve"]
