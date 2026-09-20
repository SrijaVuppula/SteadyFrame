"""Worker entrypoint: ``python -m service.worker``.

Loop: receive {"job_id"} (SQS long poll or the local directory queue), download the input,
validate it with ffmpeg probe, run ``steadyframe.remediate.pipeline.fix_file`` with the job's
policy, publish the outputs (safe.mp4, report.json, analysis.json, trace.jsonl, plot.png,
stills/*.png, summary.html) and update the Job object. A job that needs a human decision is
tarred (work.tar) and resumed from that tar when the approve endpoint re-queues it.

Logs are one JSON object per line on stdout. Metrics go to CloudWatch in AWS mode and are
only logged locally. The process exits on its own after WORKER_IDLE_EXIT_S seconds without a
message so the ECS service can scale to zero.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import html
import inspect
import json
import os
import shutil
import signal
import sys
import tarfile
import threading
import time
import traceback
from pathlib import Path

from . import core
from .core import ApiError, Context, output_key

STAGE_FRACTION = {"analyzing": 0.1, "remediating": 0.2, "rendering": 0.9, "done": 1.0}
REMEDIATION_TOOLS = (
    "get_segment_detail",
    "apply_remediation",
    "verify_candidate",
    "request_human_approval",
    "accept_candidate",
)
HEARTBEAT_S = 300
VISIBILITY_EXTEND_S = 900

# ---------------------------------------------------------------- logging + metrics


def log(level: str, msg: str, *, job_id: str | None = None, stage: str | None = None, **fields):
    rec = {"ts": core.now_iso(), "level": level, "msg": msg}
    if job_id:
        rec["job_id"] = job_id
    if stage:
        rec["stage"] = stage
    rec.update(fields)
    sys.stdout.write(json.dumps(rec, default=core._json_default) + "\n")
    sys.stdout.flush()


class Metrics:
    """CloudWatch custom metrics (namespace SteadyFrame). A no-op logger outside AWS."""

    NAMESPACE = "SteadyFrame"

    def __init__(self, mode: str):
        self.enabled = mode == "aws" and os.environ.get("STEADYFRAME_METRICS", "1") != "0"
        self._client = None

    def put(self, name: str, value: float, unit: str = "None", **dims: str) -> None:
        log("info", "metric", metric=name, value=value, unit=unit, **dims)
        if not self.enabled:
            return
        try:
            if self._client is None:
                import boto3

                self._client = boto3.client("cloudwatch")
            self._client.put_metric_data(
                Namespace=self.NAMESPACE,
                MetricData=[
                    {
                        "MetricName": name,
                        "Value": float(value),
                        "Unit": unit,
                        "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()],
                    }
                ],
            )
        except Exception as e:  # metrics never fail a job
            log("warn", "put_metric_data failed", metric=name, error=str(e))


# ---------------------------------------------------------------- trace sink -> progress + table


class TraceSink:
    """Receives every trace record from the pipeline. Batches them into the traces table and
    turns tool calls into progress updates on the Job object."""

    def __init__(self, ctx: Context, job_id: str, seq_base: int = 0, prev_records=None):
        self.ctx = ctx
        self.job_id = job_id
        self.seq_base = seq_base
        self.last_seq = seq_base
        self.records: list[dict] = list(prev_records or [])
        self.buf: list[dict] = []
        self.stage = "analyzing"
        self.status = "analyzing"
        self.detail = "decoding and analyzing frames with OpenCV"
        self.n_segments = 0
        self.done = 0
        self.attempts: dict[str, int] = {}
        self.approvals = 0
        self._last_flush = time.monotonic()
        self._last_progress = 0.0
        self._lock = threading.Lock()

    def __call__(self, rec: dict) -> None:
        try:
            self._handle(rec)
        except Exception as e:
            log("warn", "trace sink error", job_id=self.job_id, error=str(e))

    def _handle(self, rec: dict) -> None:
        rec = dict(rec)
        rec["job_id"] = self.job_id
        rec["seq"] = int(rec.get("seq", 0)) + self.seq_base
        self.last_seq = max(self.last_seq, rec["seq"])
        with self._lock:
            self.records.append(rec)
            self.buf.append(rec)
        kind, name, args = rec.get("kind"), rec.get("name"), rec.get("args") or {}
        status_before = self.status
        if kind == "tool_call":
            if name == "analyze_video":
                self.stage, self.detail = "analyzing", "decoding and analyzing frames with OpenCV"
            elif name in REMEDIATION_TOOLS:
                self.stage = self.status = "remediating"
                sid = args.get("segment_id") or str(args.get("candidate_id", "")).rsplit("-c", 1)[0]
                if name == "apply_remediation":
                    n = self.attempts[sid] = self.attempts.get(sid, 0) + 1
                    self.detail = f"segment {sid} attempt {n} ({args.get('strategy')})"
                elif name == "verify_candidate":
                    self.detail = f"segment {sid}: verifying {args.get('candidate_id')}"
                elif name == "request_human_approval":
                    self.detail = f"segment {sid}: asking for human approval"
                    self.approvals += 1
                elif name == "accept_candidate":
                    self.detail = f"segment {sid}: accepted {args.get('candidate_id')}"
                else:
                    self.detail = f"inspecting segment {sid}"
            elif name == "finalize":
                if self.status == "remediating":
                    self.status = "rendering"
                self.stage = "rendering"
                self.detail = "rendering the remediated video and re-verifying the whole file"
        elif kind == "tool_result" and name == "analyze_video" and not rec.get("error"):
            segs = (rec.get("result") or {}).get("segments")
            if isinstance(segs, dict):  # truncated by the trace summariser
                self.n_segments = int(segs.get("n", 0))
            elif isinstance(segs, list):
                self.n_segments = len(segs)
        elif kind == "decision" and name == "accept":
            self.done += 1
        elif kind == "model":
            self.stage = self.status = "remediating"
            self.detail = f"model turn ({name})"
        now = time.monotonic()
        if len(self.buf) >= 25 or now - self._last_flush > 2.0:
            self.flush()
        changed = self.status != status_before
        if changed or now - self._last_progress > 1.0:
            self._last_progress = now
            self.push_progress(status_change=changed)

    def fraction(self) -> float:
        if self.stage == "remediating":
            return round(0.2 + 0.65 * self.done / max(1, self.n_segments), 3)
        return STAGE_FRACTION.get(self.stage, 0.0)

    def push_progress(self, status_change: bool = False) -> None:
        fields = {
            "progress": {"stage": self.stage, "detail": self.detail, "fraction": self.fraction()}
        }
        if status_change:
            fields["status"] = self.status
            log("info", "status", job_id=self.job_id, stage=self.stage, status=self.status)
        try:
            self.ctx.jobs.update(self.job_id, fields)
        except Exception as e:
            log("warn", "progress update failed", job_id=self.job_id, error=str(e))

    def flush(self) -> None:
        with self._lock:
            batch, self.buf = self.buf, []
        self._last_flush = time.monotonic()
        if not batch:
            return
        try:
            self.ctx.jobs.append_traces(batch)
        except Exception as e:
            log("warn", "trace batch write failed", job_id=self.job_id, n=len(batch), error=str(e))


@contextlib.contextmanager
def trace_sink(sink):
    """Attach ``sink`` to the Trace that ``fix_file`` creates.

    ``fix_file`` has no trace_sink argument yet, so we substitute a Trace subclass with the sink
    pre-bound for the duration of the call (the pipeline resolves the class at call time)."""
    import steadyframe.agent.trace as tr

    original = tr.Trace

    class _SinkTrace(original):  # type: ignore[misc,valid-type]
        def __init__(self, path=None, job_id="local", sink_=None):
            super().__init__(path, job_id, sink)

    tr.Trace = _SinkTrace
    try:
        yield
    finally:
        tr.Trace = original


# ---------------------------------------------------------------- the job


class JobRunner:
    def __init__(self, ctx: Context, metrics: Metrics | None = None):
        self.ctx = ctx
        self.metrics = metrics or Metrics(ctx.mode)
        self.wd_root = Path(os.environ.get("WORKER_WORKDIR", "/tmp/jobs"))
        self.keep_workdir = os.environ.get("WORKER_KEEP_WORKDIR", "0") == "1"

    # ---- helpers
    def _update(self, job_id: str, **fields) -> dict:
        return self.ctx.jobs.update(job_id, fields)

    def _fail(self, job: dict, reason: str, t0: float) -> None:
        log("error", "job failed", job_id=job["job_id"], stage="error", error=reason)
        self._update(
            job["job_id"],
            status="error",
            error=reason,
            progress={"stage": "error", "detail": reason, "fraction": 1.0},
            _resume=None,
        )
        self.metrics.put("JobFailures", 1, "Count")
        self.metrics.put("JobDuration", time.perf_counter() - t0, "Seconds")

    # ---- entry
    def run(self, job_id: str) -> dict | None:
        t0 = time.perf_counter()
        job = self.ctx.jobs.get(job_id)
        if job is None:
            log("warn", "unknown job in queue", job_id=job_id)
            return None
        if job["status"] in ("passed", "failed_verification", "no_hazards", "error"):
            log("info", "job already finished; ignoring duplicate message", job_id=job_id)
            return job
        wd = self.wd_root / job_id
        shutil.rmtree(wd, ignore_errors=True)
        wd.mkdir(parents=True, exist_ok=True)
        try:
            return self._run(job, wd, t0)
        except Exception as e:
            log(
                "error",
                "unhandled worker error",
                job_id=job_id,
                error=str(e),
                trace=traceback.format_exc(),
            )
            self._fail(job, f"worker error: {type(e).__name__}: {e}", t0)
            return None
        finally:
            if not self.keep_workdir:
                shutil.rmtree(wd, ignore_errors=True)

    def _run(self, job: dict, wd: Path, t0: float) -> dict:
        import cv2

        from steadyframe.io.ffmpeg import probe
        from steadyframe.profiles import get_profile
        from steadyframe.remediate.pipeline import fix_file

        job_id = job["job_id"]
        store = self.ctx.store
        resume = job.get("_resume") or None
        log(
            "info",
            "job start",
            job_id=job_id,
            stage="download",
            resume=bool(resume),
            policy=job["policy"],
        )

        # 1. input
        in_key = job["_input_key"]
        input_path = wd / "input" / Path(in_key).name
        if not store.exists(in_key):
            self._fail(job, "input upload not found", t0)
            return job
        store.get_file(in_key, input_path)
        size = input_path.stat().st_size
        try:
            info = validate_input(probe, input_path, size)
        except ApiError as e:
            self._fail(job, e.message, t0)
            return job
        job["input"] = {**job["input"], **info, "size_bytes": size}
        job = self._update(
            job_id,
            status="analyzing",
            input=job["input"],
            error=None,
            progress={
                "stage": "analyzing",
                "detail": "decoding and analyzing frames with OpenCV",
                "fraction": 0.05,
            },
        )
        log("info", "status", job_id=job_id, stage="analyzing", status="analyzing", **info)

        # 2. resume state
        job_wd = wd / "job"
        out = wd / "out"
        out.mkdir(parents=True, exist_ok=True)
        decisions = None
        prev_records: list[dict] = []
        if resume:
            tar_key = output_key(job_id, "work.tar")
            if not store.exists(tar_key):
                self._fail(job, "paused job state (work.tar) is gone; start a new job", t0)
                return job
            tar_path = wd / "work.tar"
            store.get_file(tar_key, tar_path)
            restore_workdir(tar_path, job_wd)
            prev_trace = job_wd / "trace.jsonl"
            if prev_trace.exists():
                prev_records = [
                    json.loads(line) for line in prev_trace.read_text().splitlines() if line.strip()
                ]
            decisions = {sid: dict(d) for sid, d in (resume.get("decisions") or {}).items()}
            log(
                "info", "resuming from work.tar", job_id=job_id, stage="resume", decisions=decisions
            )

        # 3. pipeline
        sink = TraceSink(self.ctx, job_id, int(job.get("_trace_seq") or 0), prev_records)
        profile = get_profile(job["profile"], conservative=bool(job.get("conservative")))
        kwargs = dict(
            policy=job["policy"],
            profile=profile,
            report_path=out / "report.json",
            workdir=job_wd,
            plot_path=out / "plot.png",
            decisions=decisions,
            approval_min_ssim=self.ctx.approval_min_ssim,
            keep_workdir=True,
        )
        t_fix = time.perf_counter()
        if "trace_sink" in inspect.signature(fix_file).parameters:
            report = fix_file(input_path, out / "safe.mp4", trace_sink=sink, **kwargs)
        else:
            with trace_sink(sink):
                report = fix_file(input_path, out / "safe.mp4", **kwargs)
        sink.flush()
        fix_s = time.perf_counter() - t_fix
        status = report["status"]
        log(
            "info",
            "pipeline finished",
            job_id=job_id,
            stage="outputs",
            status=status,
            iterations=report["iterations"],
            fix_s=round(fix_s, 3),
        )

        # 4. outputs
        state = (
            json.loads((job_wd / "job.json").read_text()) if (job_wd / "job.json").exists() else {}
        )
        before = state.get("analysis") or None
        after = None
        safe = out / "safe.mp4"
        if safe.exists() and status in ("passed", "failed_verification", "no_hazards"):
            if status == "no_hazards":
                after = before
            else:
                from steadyframe.analyzer import analyze_file

                after = analyze_file(str(safe), profile=profile)
        if before is not None:
            doc = dict(before)
            if after is not None:
                doc["after"] = after
            (out / "analysis.json").write_text(json.dumps(doc, default=core._json_default))
        (out / "trace.jsonl").write_text(
            "".join(json.dumps(r, default=core._json_default) + "\n" for r in sink.records)
        )
        stills: dict[str, Path] = {}
        if before and before.get("segments"):
            try:
                stills = write_stills(input_path, before["segments"], out / "stills")
            except Exception as e:
                log("warn", "stills failed", job_id=job_id, error=str(e))
        segments_doc = build_segments(before, state, report)
        (out / "segments.json").write_text(json.dumps(segments_doc, default=core._json_default))
        (out / "summary.html").write_text(
            build_summary(job, report, before, after, stills, cv2.__version__)
        )
        if status == "needs_approval":
            pack_workdir(job_wd, out / "work.tar")

        uploads = {
            "safe.mp4": "video/mp4",
            "report.json": "application/json",
            "analysis.json": "application/json",
            "trace.jsonl": "application/x-ndjson",
            "plot.png": "image/png",
            "summary.html": "text/html; charset=utf-8",
            "segments.json": "application/json",
            "work.tar": "application/x-tar",
        }
        for name, ct in uploads.items():
            p = out / name
            if p.exists() and (
                name != "safe.mp4" or status in ("passed", "failed_verification", "no_hazards")
            ):
                store.put_file(output_key(job_id, name), p, ct)
        for sid, p in stills.items():
            store.put_file(output_key(job_id, f"stills/{sid}.png"), p, "image/png")
        downloads = {
            **{
                k: v
                for k, v in (job.get("downloads") or {}).items()
                if k not in core.DOWNLOAD_KINDS
            },
            **{
                k: (out / fname).exists()
                and (k != "video" or status in ("passed", "failed_verification", "no_hazards"))
                for k, (fname, _ct) in core.DOWNLOAD_KINDS.items()
            },
        }

        # 5. job record
        remediation = {
            "status": status,
            "policy": report.get("policy"),
            "iterations": report.get("iterations", 0),
            "runtime_s": report.get("runtime_s"),
            "quality": report.get("quality"),
            "segments": report.get("segments", []),
        }
        rt = (before or {}).get("stats", {}).get("realtime_factor")
        fields = dict(
            status=status,
            before=core.slim_analysis(before),
            after=core.slim_analysis(after)
            if after is not None
            else ({**report["after"], "timeline": {}} if report.get("after") else None),
            remediation=remediation,
            pending_approvals=report.get("pending_approvals") or [],
            downloads=downloads,
            error=report.get("error"),
            tool={
                "version": report["tool"]["version"],
                "opencv": report["tool"]["opencv"]["version"],
            },
            progress={
                "stage": "needs_approval" if status == "needs_approval" else "done",
                "detail": _final_detail(status, report),
                "fraction": 1.0,
            },
            _trace_seq=sink.last_seq,
            _resume=None,
            stats={
                "fix_s": round(fix_s, 3),
                "realtime_factor": rt,
                "worker_s": round(time.perf_counter() - t0, 3),
            },
        )
        job = self._update(job_id, **fields)
        log(
            "info",
            "job done",
            job_id=job_id,
            stage="done",
            status=status,
            duration_s=round(time.perf_counter() - t0, 3),
            realtime_factor=rt,
        )

        # 6. metrics
        self.metrics.put("JobDuration", time.perf_counter() - t0, "Seconds")
        if rt:
            self.metrics.put("RealtimeFactor", rt)
        n_seg = len(report.get("segments") or [])
        if n_seg:
            self.metrics.put("IterationsPerSegment", report.get("iterations", 0) / n_seg)
        if status in ("error", "failed_verification"):
            self.metrics.put("JobFailures", 1, "Count")
        if sink.approvals:
            self.metrics.put("ApprovalsRequested", sink.approvals, "Count")
        return job


def _final_detail(status: str, report: dict) -> str:
    return {
        "passed": "remediated output passes re-verification",
        "no_hazards": "no hazards found; output is the unchanged input",
        "failed_verification": "could not bring every segment under the thresholds",
        "needs_approval": "waiting for a human decision",
        "error": report.get("error") or "error",
    }.get(status, status)


def validate_input(probe, path: Path, size: int) -> dict:
    try:
        info = probe(path)
    except Exception as e:
        raise ApiError(415, f"not a readable video: {e}") from e
    return core.validate_probe(info, size)


# ---------------------------------------------------------------- work.tar (paused jobs)


def pack_workdir(job_wd: Path, tar_path: Path) -> None:
    with tarfile.open(tar_path, "w") as tar:
        tar.add(job_wd, arcname="job")
        manifest = json.dumps({"workdir": str(job_wd)}).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        import io

        tar.addfile(info, io.BytesIO(manifest))


def restore_workdir(tar_path: Path, job_wd: Path) -> None:
    dest = job_wd.parent
    with tarfile.open(tar_path) as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:  # python < 3.11.4
            tar.extractall(dest)
        manifest = (
            json.loads(tar.extractfile("manifest.json").read())
            if "manifest.json" in tar.getnames()
            else {}
        )
    old = manifest.get("workdir")
    state_path = job_wd / "job.json"
    if old and old != str(job_wd) and state_path.exists():
        # candidate paths inside job.json are absolute; point them at the new location
        state_path.write_text(state_path.read_text().replace(old, str(job_wd)))
    (dest / "manifest.json").unlink(missing_ok=True)


# ---------------------------------------------------------------- outputs


def write_stills(input_path: Path, segments: list[dict], out_dir: Path) -> dict[str, Path]:
    """One PNG per segment: the frame in the middle of the segment with the regions outlined.
    Still images only, never animated."""
    import cv2

    from steadyframe.io.video import open_video

    out_dir.mkdir(parents=True, exist_ok=True)
    wanted: dict[int, list[dict]] = {}
    for s in segments:
        mid = (int(s["start_frame"]) + int(s["end_frame"])) // 2
        wanted.setdefault(mid, []).append(s)
    last = max(wanted) if wanted else -1
    written: dict[str, Path] = {}
    reader = open_video(input_path)
    for idx, _t, frame in reader:
        if idx in wanted:
            h, w = frame.shape[:2]
            for s in wanted[idx]:
                img = frame.copy()
                thick = max(2, min(w, h) // 160)
                for r in s.get("regions", []):
                    x0, y0 = int(round(r["x"] * w)), int(round(r["y"] * h))
                    x1, y1 = int(round((r["x"] + r["w"]) * w)), int(round((r["y"] + r["h"]) * h))
                    cv2.rectangle(
                        img, (x0, y0), (max(x1 - 1, x0), max(y1 - 1, y0)), (0, 165, 255), thick
                    )
                label = f"{s['id']} {s['type']} {s['start_s']:.2f}-{s['end_s']:.2f}s"
                cv2.putText(
                    img,
                    label,
                    (8, max(20, h - 12)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.4, h / 720 * 0.6),
                    (0, 0, 0),
                    thick + 2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    img,
                    label,
                    (8, max(20, h - 12)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.4, h / 720 * 0.6),
                    (255, 255, 255),
                    max(1, thick - 1),
                    cv2.LINE_AA,
                )
                p = out_dir / f"{s['id']}.png"
                cv2.imwrite(str(p), img)
                written[s["id"]] = p
        if idx >= last:
            break
    with contextlib.suppress(Exception):
        reader.close()
    return written


def build_segments(before: dict | None, state: dict, report: dict) -> list[dict]:
    """GET /jobs/{id}/segments payload: analysis segments + region series + remediation."""
    rem = {s["segment_id"]: s for s in report.get("segments") or []}
    out = []
    for s in (before or {}).get("segments", []):
        st = (state.get("segments") or {}).get(s["id"]) or {}
        series = None
        if st.get("region_series"):
            series = {"t": st.get("region_series_t") or [], "L": st["region_series"]}
        out.append({**s, "region_series": series, "remediation": rem.get(s["id"])})
    return out


def _thumb_data_uri(path: Path, width: int = 360) -> str | None:
    try:
        import cv2

        img = cv2.imread(str(path))
        if img is None:
            return None
        h, w = img.shape[:2]
        if w > width:
            img = cv2.resize(img, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    except Exception:
        return None


def build_summary(
    job: dict,
    report: dict,
    before: dict | None,
    after: dict | None,
    stills: dict[str, Path],
    opencv: str,
) -> str:
    """A small self-contained HTML page. Stills only; no video, nothing moves."""
    e = html.escape
    status = report["status"]
    inp = job.get("input") or {}
    rows = []
    rem = {s["segment_id"]: s for s in report.get("segments") or []}
    for s in (before or {}).get("segments", []):
        r = rem.get(s["id"]) or {}
        q = r.get("quality") or {}
        thumb = _thumb_data_uri(stills[s["id"]]) if s["id"] in stills else None
        img = f'<img alt="still frame of {e(s["id"])}" src="{thumb}">' if thumb else "-"
        rows.append(
            "<tr>"
            f"<td>{e(s['id'])}</td><td>{e(s['type'])}</td>"
            f"<td>{s['start_s']:.2f}-{s['end_s']:.2f} s</td>"
            f"<td>{s['peak_flash_rate_hz']:.1f} Hz</td><td>{s['max_area_fraction']:.2f}</td>"
            f"<td>{s['max_delta_L']:.2f}</td>"
            f"<td>{e(str(r.get('outcome', '-')))}</td>"
            f"<td>{e(str(r.get('strategy') or '-'))} {e(json.dumps(r.get('params') or {}))}</td>"
            f"<td>{q.get('ssim_overall', float('nan')):.3f}</td>"
            f"<td>{img}</td>"
            "</tr>"
        )
    quality = report.get("quality") or {}
    qrows = "".join(
        f"<tr><td>{e(k)}</td><td>{v:.4f}</td></tr>"
        for k, v in quality.items()
        if isinstance(v, int | float)
    )
    strategies = "".join(
        f"<li><b>{e(s['segment_id'])}</b>: {e(str(s.get('strategy') or 'none'))} {e(json.dumps(s.get('params') or {}))} "
        f"after {len(s.get('attempts') or [])} attempt(s), outcome {e(str(s.get('outcome')))}</li>"
        for s in report.get("segments") or []
    )
    pend = report.get("pending_approvals") or []
    pend_html = "".join(
        f"<li><b>{e(p['segment_id'])}</b>: {e(str(p.get('reason')))} - options: "
        + ", ".join(
            e(str(o.get("candidate_id"))) + " (" + e(str(o.get("strategy"))) + ")"
            for o in p.get("options") or []
        )
        + "</li>"
        for p in pend
    )
    ocv = (report.get("tool") or {}).get("opencv") or {}
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>SteadyFrame summary {e(job["job_id"][:8])}</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222;background:#fff}}
table{{border-collapse:collapse;width:100%;margin:8px 0}} td,th{{border:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}}
th{{background:#f3f3f3}} img{{max-width:240px;height:auto;display:block}} .v{{font-weight:600}}
.pass{{color:#2b8a3e}} .fail{{color:#c92a2a}} .note{{background:#fff8e1;border:1px solid #f1d27a;padding:8px 12px;margin:16px 0}}
@media (prefers-reduced-motion: reduce){{*{{animation:none!important;transition:none!important}}}}
</style></head><body>
<h1>SteadyFrame report</h1>
<p>Job <code>{e(job["job_id"])}</code> - input <b>{e(str(inp.get("filename")))}</b>
({inp.get("width")}x{inp.get("height")} @ {inp.get("fps")} fps, {inp.get("duration_s")} s, audio: {"yes" if inp.get("has_audio") else "no"})
- profile <b>{e(job.get("profile", ""))}</b>{" (conservative)" if job.get("conservative") else ""}, policy <b>{e(str(report.get("policy")))}</b></p>
<h2>Verdicts</h2>
<p>Before: <span class="v {e((before or {}).get("verdict", ""))}">{e(str((before or {}).get("verdict")).upper())}</span>
&nbsp; After: <span class="v {e((after or {}).get("verdict", "") if after else "")}">{e(str((after or {}).get("verdict")).upper()) if after else "n/a"}</span>
&nbsp; Job status: <span class="v">{e(status)}</span>{" - " + e(str(report.get("error"))) if report.get("error") else ""}</p>
<p>{report.get("iterations", 0)} remediation iteration(s) in {report.get("runtime_s", 0):.1f} s.</p>
<h2>Hazard segments (before)</h2>
<table><thead><tr><th>id</th><th>type</th><th>time</th><th>peak rate</th><th>area</th><th>max dL</th><th>outcome</th><th>strategy</th><th>SSIM</th><th>still (middle frame)</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="10">no hazard segments</td></tr>'}</tbody></table>
<h2>Strategies applied</h2><ul>{strategies or "<li>none</li>"}</ul>
{("<h2>Pending approvals</h2><ul>" + pend_html + "</ul>") if pend_html else ""}
<h2>Quality (accepted candidates, mean)</h2>
<table><tbody>{qrows or "<tr><td>n/a</td></tr>"}</tbody></table>
<h2>Tool</h2>
<p>steadyframe {e(str((report.get("tool") or {}).get("version")))} - OpenCV {e(opencv)}
{("(" + e(str(ocv.get("parallel_framework", ""))) + " " + e(str(ocv.get("baseline", ""))) + ")") if ocv else ""}</p>
<div class="note"><b>Responsible use.</b> SteadyFrame checks video against published photosensitivity
thresholds (WCAG 2.3.1, ITU-R BT.1702 / Ofcom guidance) and reduces the measured violations. A pass
means the measurements are under those thresholds; it is not a guarantee that the content is safe
for every viewer and it is not medical advice. Hazardous content is shown here only as luminance plots
and single still frames.</div>
</body></html>
"""


# ---------------------------------------------------------------- loop


def process_message(
    ctx: Context, msg: core.Message, runner: JobRunner | None = None
) -> dict | None:
    runner = runner or JobRunner(ctx)
    job_id = str((msg.body or {}).get("job_id") or "")
    if not job_id:
        log("warn", "message without job_id", body=msg.body)
        return None
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(HEARTBEAT_S):
            try:
                ctx.queue.extend(msg, VISIBILITY_EXTEND_S)
            except Exception as e:
                log("warn", "visibility extend failed", job_id=job_id, error=str(e))

    t = threading.Thread(target=heartbeat, daemon=True)
    t.start()
    try:
        return runner.run(job_id)
    finally:
        stop.set()


def process_one(ctx: Context, wait_s: float = 0.5) -> dict | None:
    """Receive and process a single message (tests, and the ``--once`` flag)."""
    msg = ctx.queue.receive(wait_s=wait_s)
    if msg is None:
        return None
    try:
        return process_message(ctx, msg)
    finally:
        ctx.queue.delete(msg)


def run_loop(
    ctx: Context,
    *,
    stop: threading.Event | None = None,
    idle_exit_s: float | None = None,
    max_jobs: int | None = None,
    wait_s: float = 20.0,
) -> int:
    stop = stop or threading.Event()
    runner = JobRunner(ctx)
    last_activity = time.monotonic()
    n = 0
    while not stop.is_set():
        msg = ctx.queue.receive(wait_s=wait_s)
        if msg is None:
            if idle_exit_s is not None and time.monotonic() - last_activity >= idle_exit_s:
                log("info", "idle; exiting so the service can scale to zero", idle_s=idle_exit_s)
                break
            continue
        try:
            process_message(ctx, msg, runner)
        finally:
            ctx.queue.delete(msg)
        n += 1
        last_activity = time.monotonic()
        if max_jobs and n >= max_jobs:
            break
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="process one message and exit")
    ap.add_argument("--wait", type=float, default=20.0, help="long-poll seconds per receive")
    args = ap.parse_args(argv)

    import cv2

    log(
        "info",
        "worker starting",
        opencv=cv2.__version__,
        python=sys.version.split()[0],
        mode=os.environ.get("STEADYFRAME_MODE", "auto"),
    )
    print(f"OpenCV {cv2.__version__}", flush=True)
    if not cv2.__version__.startswith("5."):
        log("error", "OpenCV 5.x is required", opencv=cv2.__version__)
        return 2
    import steadyframe  # asserts the version too and prints nothing

    log(
        "info",
        "package",
        steadyframe=steadyframe.__version__,
        build=steadyframe.opencv_build_summary(),
    )
    ctx = Context.from_env()
    stop = threading.Event()

    def _term(signum, _frame):
        log("info", "signal received; finishing the current job", signal=signum)
        stop.set()

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    if args.once:
        process_one(ctx, wait_s=args.wait)
        return 0
    idle = os.environ.get("WORKER_IDLE_EXIT_S")
    run_loop(ctx, stop=stop, idle_exit_s=float(idle) if idle else None, wait_s=args.wait)
    return 0


if __name__ == "__main__":
    sys.exit(main())
