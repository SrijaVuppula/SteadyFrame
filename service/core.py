"""Shared job logic for the API (Lambda or local FastAPI) and the worker.

Three small abstractions, each with an AWS and a local backend:

    Store     S3Store / LocalStore        uploads/, outputs/, samples/ (keys as in docs/API.md)
    JobsStore DynamoJobs / LocalJobs      the Job object plus the trace records
    Queue     SqsQueue / LocalQueue       {"job_id": ...} messages

``Api`` holds the endpoint logic itself so the Lambda handler and the FastAPI app are thin
adapters. Nothing in this module imports cv2 or boto3 at import time: the Lambda must stay
light and the local mode must work without AWS.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

MAX_BYTES = 100 * 1024 * 1024
MAX_DURATION_S = 120.0
DURATION_TOLERANCE_S = 0.5  # container durations are rounded; do not reject 120.04 s
CONTAINERS = ("mp4", "mov", "webm", "mkv", "gif")
# ffmpeg demuxer names (from `ffmpeg -i`) that are acceptable for each extension
FFMPEG_FORMATS = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm", "gif"}
CONTENT_TYPES = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
    "video/matroska": "mkv",
    "image/gif": "gif",
}
GENERIC_CONTENT_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
PROFILES = ("wcag", "broadcast")
POLICIES = ("fixed", "agent")

TERMINAL = ("passed", "failed_verification", "no_hazards", "error", "needs_approval")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "created": ("uploaded", "queued", "error"),
    "uploaded": ("queued", "error"),
    "queued": ("analyzing", "error"),
    "analyzing": ("remediating", "no_hazards", "needs_approval", "error"),
    "remediating": ("rendering", "needs_approval", "error"),
    "rendering": ("passed", "failed_verification", "needs_approval", "error"),
    "needs_approval": ("queued", "error"),
    # a redelivered message may find the job mid-flight; the worker restarts it from scratch
    "passed": ("error",),
    "failed_verification": ("error",),
    "no_hazards": ("error",),
    "error": (),
}

DOWNLOAD_KINDS = {
    "video": ("safe.mp4", "video/mp4"),
    "report": ("report.json", "application/json"),
    "analysis": ("analysis.json", "application/json"),
    "trace": ("trace.jsonl", "application/x-ndjson"),
    "plot": ("plot.png", "image/png"),
    "summary": ("summary.html", "text/html"),
}
INPUT_KIND = "input"  # the original upload (uploads/<id>/input.<ext>) for the click-through preview
PRESIGN_TTL_S = 15 * 60
TTL_S = 7 * 24 * 3600  # DynamoDB TTL for job records and trace rows

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SEGMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def tool_version() -> str:
    v = os.environ.get("STEADYFRAME_VERSION")
    if v:
        return v
    try:
        from importlib.metadata import version

        return version("steadyframe")
    except Exception:
        return "0.1.0"


def opencv_version() -> str:
    """The Lambda never imports cv2; the deploy passes the pinned version through the env."""
    v = os.environ.get("STEADYFRAME_OPENCV_VERSION")
    if v:
        return ".".join(v.split(".")[:3])
    try:
        import cv2

        return cv2.__version__
    except Exception:
        return "unknown"


def input_key(job_id: str, ext: str) -> str:
    return f"uploads/{job_id}/input.{ext}"


def output_key(job_id: str, name: str) -> str:
    return f"outputs/{job_id}/{name}"


def sample_key(sample_id: str) -> str:
    return f"samples/{sample_id}.mp4"


def check_transition(old: str, new: str) -> None:
    if new == old:
        return
    if new not in TRANSITIONS.get(old, ()):
        raise ApiError(409, f"cannot move job from {old} to {new}")


# ---------------------------------------------------------------- storage


class LocalStore:
    """A directory. URLs are relative paths the local API serves (``/files/<key>``)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        ignore = self.root / ".gitignore"
        if not ignore.exists():  # the data dir lives inside the checkout by default
            ignore.write_text("*\n")

    def path(self, key: str) -> Path:
        if ".." in key.split("/") or key.startswith("/"):
            raise ApiError(400, "bad key")
        return self.root / key

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def size(self, key: str) -> int:
        return self.path(key).stat().st_size

    def put_file(self, key: str, src: str | Path, content_type: str | None = None) -> None:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, p)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def get_bytes(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def get_file(self, key: str, dst: str | Path) -> None:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.path(key), dst)

    def copy(self, src_key: str, dst_key: str) -> None:
        self.put_file(dst_key, self.path(src_key))

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        base = self.path(prefix)
        if not base.is_dir():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    def upload_target(self, job_id: str, key: str, content_type: str, prefix: str = "") -> dict:
        return {
            "method": "PUT",
            "url": f"{prefix}/jobs/{job_id}/upload",
            "headers": {"Content-Type": content_type},
        }

    def download_url(self, key: str, prefix: str = "") -> str:
        return f"{prefix}/files/{key}"


class S3Store:
    def __init__(self, bucket: str, region: str | None = None):
        self.bucket = bucket
        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3", region_name=self.region, config=Config(signature_version="s3v4")
            )
        return self._client

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def size(self, key: str) -> int:
        return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])

    def put_file(self, key: str, src: str | Path, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.upload_file(str(src), self.bucket, key, ExtraArgs=extra)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        kw = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **kw)

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def get_file(self, key: str, dst: str | Path) -> None:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(dst))

    def copy(self, src_key: str, dst_key: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket, Key=dst_key, CopySource={"Bucket": self.bucket, "Key": src_key}
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(o["Key"] for o in page.get("Contents", []))
        return keys

    def upload_target(self, job_id: str, key: str, content_type: str, prefix: str = "") -> dict:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=PRESIGN_TTL_S,
        )
        return {"method": "PUT", "url": url, "headers": {"Content-Type": content_type}}

    def download_url(self, key: str, prefix: str = "") -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=PRESIGN_TTL_S
        )


# ---------------------------------------------------------------- job metadata


class LocalJobs:
    """One JSON file per job and one JSONL file per trace, under ``root``."""

    _lock = threading.RLock()

    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "jobs").mkdir(parents=True, exist_ok=True)
        (self.root / "traces").mkdir(parents=True, exist_ok=True)

    def _p(self, job_id: str) -> Path:
        return self.root / "jobs" / f"{job_id}.json"

    def put(self, job: dict) -> None:
        with self._lock:
            _atomic_write(self._p(job["job_id"]), json.dumps(job, default=_json_default))

    def get(self, job_id: str) -> dict | None:
        p = self._p(job_id)
        with self._lock:
            if not p.exists():
                return None
            return json.loads(p.read_text())

    def update(self, job_id: str, fields: dict) -> dict:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                raise ApiError(404, "job not found")
            job.update(fields)
            job["updated_at"] = now_iso()
            self.put(job)
            return job

    def append_traces(self, records: list[dict]) -> None:
        if not records:
            return
        p = self.root / "traces" / f"{records[0]['job_id']}.jsonl"
        with self._lock, p.open("a") as f:
            for r in records:
                f.write(json.dumps(r, default=_json_default) + "\n")

    def traces(self, job_id: str, after: int = 0) -> list[dict]:
        p = self.root / "traces" / f"{job_id}.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if int(rec.get("seq", 0)) > after:
                out.append(rec)
        return out


class DynamoJobs:
    def __init__(self, jobs_table: str, traces_table: str, region: str | None = None):
        self.jobs_name = jobs_table
        self.traces_name = traces_table
        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        self._res = None

    @property
    def res(self):
        if self._res is None:
            import boto3

            self._res = boto3.resource("dynamodb", region_name=self.region)
        return self._res

    @property
    def jobs(self):
        return self.res.Table(self.jobs_name)

    @property
    def traces_table(self):
        return self.res.Table(self.traces_name)

    def put(self, job: dict) -> None:
        self.jobs.put_item(Item=to_dynamo(job))

    def get(self, job_id: str) -> dict | None:
        item = self.jobs.get_item(Key={"job_id": job_id}, ConsistentRead=True).get("Item")
        return from_dynamo(item) if item else None

    def update(self, job_id: str, fields: dict) -> dict:
        fields = {**fields, "updated_at": now_iso()}
        names = {f"#k{i}": k for i, k in enumerate(fields)}
        values = {f":v{i}": v for i, v in enumerate(to_dynamo(fields).values())}
        expr = "SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(fields)))
        out = self.jobs.update_item(
            Key={"job_id": job_id},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(job_id)",
            ReturnValues="ALL_NEW",
        )
        return from_dynamo(out["Attributes"])

    def append_traces(self, records: list[dict]) -> None:
        if not records:
            return
        ttl = int(time.time()) + TTL_S
        with self.traces_table.batch_writer(overwrite_by_pkeys=["job_id", "seq"]) as bw:
            for r in records:
                bw.put_item(Item=to_dynamo({**r, "_ttl": ttl}))

    def traces(self, job_id: str, after: int = 0) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        out: list[dict] = []
        kw: dict = {
            "KeyConditionExpression": Key("job_id").eq(job_id) & Key("seq").gt(int(after)),
        }
        while True:
            page = self.traces_table.query(**kw)
            out.extend(from_dynamo(i) for i in page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                return out
            kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def to_dynamo(obj: Any) -> Any:
    """DynamoDB wants Decimal instead of float and rejects empty strings in sets (not maps)."""
    return json.loads(json.dumps(obj, default=_json_default), parse_float=Decimal)


def from_dynamo(obj: Any) -> Any:
    if isinstance(obj, list):
        return [from_dynamo(x) for x in obj]
    if isinstance(obj, dict):
        return {k: from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def _json_default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, Path):
        return str(o)
    try:
        import numpy as np

        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    return str(o)


def _atomic_write(p: Path, text: str) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, p)


# ---------------------------------------------------------------- queue


@dataclass
class Message:
    body: dict
    handle: str


class LocalQueue:
    """Directory-backed FIFO shared by the API and the worker (same process or docker compose).

    A message is a JSON file; receiving renames it to ``.claimed`` (atomic on one filesystem),
    deleting removes it. Claimed files older than ``stale_s`` are put back on the next receive
    so a crashed worker does not lose jobs."""

    def __init__(self, root: str | Path, stale_s: float = 1800.0):
        self.dir = Path(root) / "queue"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stale_s = stale_s
        self._cv = threading.Condition()

    def send(self, payload: dict) -> None:
        name = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}"
        tmp = self.dir / f"{name}.tmp"
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, self.dir / f"{name}.json")
        with self._cv:
            self._cv.notify_all()

    def _requeue_stale(self) -> None:
        cutoff = time.time() - self.stale_s
        for p in self.dir.glob("*.claimed"):
            try:
                if p.stat().st_mtime < cutoff:
                    os.replace(p, p.with_suffix(".json"))
            except FileNotFoundError:
                pass

    def receive(self, wait_s: float = 20.0) -> Message | None:
        deadline = time.monotonic() + wait_s
        while True:
            self._requeue_stale()
            for p in sorted(self.dir.glob("*.json")):
                claimed = p.with_suffix(".claimed")
                try:
                    os.replace(p, claimed)
                except FileNotFoundError:
                    continue  # another worker got it
                try:
                    return Message(json.loads(claimed.read_text()), str(claimed))
                except Exception:
                    claimed.unlink(missing_ok=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            with self._cv:
                self._cv.wait(timeout=min(0.5, remaining))

    def delete(self, msg: Message) -> None:
        Path(msg.handle).unlink(missing_ok=True)

    def extend(self, msg: Message, seconds: int) -> None:
        try:
            os.utime(msg.handle)  # keeps it from being treated as stale
        except FileNotFoundError:
            pass

    def approximate_depth(self) -> int:
        return len(list(self.dir.glob("*.json")))


class SqsQueue:
    def __init__(self, url: str, region: str | None = None):
        self.url = url
        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("sqs", region_name=self.region)
        return self._client

    def send(self, payload: dict) -> None:
        self.client.send_message(QueueUrl=self.url, MessageBody=json.dumps(payload))

    def receive(self, wait_s: float = 20.0) -> Message | None:
        resp = self.client.receive_message(
            QueueUrl=self.url, MaxNumberOfMessages=1, WaitTimeSeconds=int(min(20, max(0, wait_s)))
        )
        msgs = resp.get("Messages") or []
        if not msgs:
            return None
        m = msgs[0]
        try:
            body = json.loads(m["Body"])
        except Exception:
            body = {}
        return Message(body if isinstance(body, dict) else {}, m["ReceiptHandle"])

    def delete(self, msg: Message) -> None:
        self.client.delete_message(QueueUrl=self.url, ReceiptHandle=msg.handle)

    def extend(self, msg: Message, seconds: int) -> None:
        self.client.change_message_visibility(
            QueueUrl=self.url, ReceiptHandle=msg.handle, VisibilityTimeout=int(seconds)
        )


# ---------------------------------------------------------------- context


@dataclass
class Context:
    mode: str  # "aws" | "local"
    store: Any
    jobs: Any
    queue: Any
    approval_min_ssim: float = 0.75
    data_dir: Path | None = None

    @classmethod
    def from_env(cls) -> Context:
        mode = os.environ.get("STEADYFRAME_MODE") or (
            "aws" if os.environ.get("JOBS_TABLE") else "local"
        )
        ssim = float(os.environ.get("STEADYFRAME_APPROVAL_MIN_SSIM", "0.75"))
        if mode == "aws":
            return cls(
                mode="aws",
                store=S3Store(os.environ["BUCKET_NAME"]),
                jobs=DynamoJobs(os.environ["JOBS_TABLE"], os.environ["TRACES_TABLE"]),
                queue=SqsQueue(os.environ["QUEUE_URL"]),
                approval_min_ssim=ssim,
            )
        return cls.local(os.environ.get("LOCAL_DATA_DIR", "./data/service"), ssim)

    @classmethod
    def local(cls, data_dir: str | Path, approval_min_ssim: float = 0.75) -> Context:
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        if not (root / ".gitignore").exists():  # ./data/service lives inside the checkout
            (root / ".gitignore").write_text("*\n")
        return cls(
            mode="local",
            store=LocalStore(root / "files"),
            jobs=LocalJobs(root),
            queue=LocalQueue(root),
            approval_min_ssim=approval_min_ssim,
            data_dir=root,
        )


# ---------------------------------------------------------------- job records


def new_job(body: dict) -> dict:
    """Validate a POST /jobs body and build the initial Job object."""
    if not isinstance(body, dict):
        raise ApiError(400, "body must be a JSON object")
    filename = str(body.get("filename") or "").strip()
    if not filename or "/" in filename or "\\" in filename:
        raise ApiError(400, "filename is required")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in CONTAINERS:
        raise ApiError(400, f"unsupported container .{ext or '?'}; use one of {list(CONTAINERS)}")
    content_type = str(body.get("content_type") or "").strip().lower().split(";")[0]
    if content_type in CONTENT_TYPES:
        if CONTENT_TYPES[content_type] != ext and not (
            ext in ("mp4", "mov") and CONTENT_TYPES[content_type] in ("mp4", "mov")
        ):
            raise ApiError(400, f"content_type {content_type} does not match .{ext}")
    elif content_type not in GENERIC_CONTENT_TYPES:
        raise ApiError(400, f"unsupported content_type {content_type}")
    content_type = content_type or "application/octet-stream"
    try:
        size = int(body.get("size_bytes") or 0)
    except (TypeError, ValueError) as e:
        raise ApiError(400, "size_bytes must be an integer") from e
    if size <= 0:
        raise ApiError(400, "size_bytes is required")
    if size > MAX_BYTES:
        raise ApiError(413, f"file is {size} bytes; the limit is {MAX_BYTES} (100 MB)")
    duration = body.get("duration_s")
    if duration is not None:
        try:
            duration = float(duration)
        except (TypeError, ValueError) as e:
            raise ApiError(400, "duration_s must be a number") from e
        if duration > MAX_DURATION_S + DURATION_TOLERANCE_S:
            raise ApiError(413, f"clip is {duration:.1f} s; the limit is {MAX_DURATION_S:.0f} s")
    profile = str(body.get("profile") or "wcag")
    if profile not in PROFILES:
        raise ApiError(400, f"profile must be one of {list(PROFILES)}")
    policy = str(body.get("policy") or "fixed")
    if policy not in POLICIES:
        raise ApiError(400, f"policy must be one of {list(POLICIES)}")
    conservative = bool(body.get("conservative", False))
    job_id = uuid.uuid4().hex
    ts = now_iso()
    return {
        "job_id": job_id,
        "status": "created",
        "created_at": ts,
        "updated_at": ts,
        "profile": profile,
        "policy": policy,
        "conservative": conservative,
        "input": {
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size,
            "ext": ext,
            **({"duration_s": duration} if duration is not None else {}),
        },
        "progress": {"stage": "created", "detail": "waiting for the upload", "fraction": 0.0},
        "before": None,
        "after": None,
        "remediation": None,
        "pending_approvals": [],
        "downloads": {k: False for k in (*DOWNLOAD_KINDS, INPUT_KIND)},
        "error": None,
        "tool": {"version": tool_version(), "opencv": opencv_version()},
        "_input_key": input_key(job_id, ext),
        "_trace_seq": 0,
        "_resume": None,
        "_ttl": int(time.time()) + TTL_S,
    }


def public_job(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def validate_probe(info, size_bytes: int) -> dict:
    """Worker-side validation of the uploaded file (``steadyframe.io.ffmpeg.probe`` result)."""
    if size_bytes > MAX_BYTES:
        raise ApiError(413, f"file is {size_bytes} bytes; the limit is {MAX_BYTES} (100 MB)")
    fmts = {f.strip() for f in (info.container or "").split(",")}
    if not fmts & FFMPEG_FORMATS:
        raise ApiError(
            415, f"container {info.container or 'unknown'} is not one of {list(CONTAINERS)}"
        )
    if info.duration_s is None:
        raise ApiError(415, "could not determine the clip duration")
    if info.duration_s > MAX_DURATION_S + DURATION_TOLERANCE_S:
        raise ApiError(413, f"clip is {info.duration_s:.1f} s; the limit is {MAX_DURATION_S:.0f} s")
    if info.width <= 0 or info.height <= 0:
        raise ApiError(415, "no video stream")
    return {
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "duration_s": round(info.duration_s, 3),
        "has_audio": bool(info.has_audio),
        "codec": info.codec,
        "container": info.container,
    }


def downsample(xs: list, n: int = 600) -> list:
    if len(xs) <= n:
        return list(xs)
    step = (len(xs) - 1) / (n - 1)
    return [xs[round(i * step)] for i in range(n)]


def slim_analysis(analysis: dict | None, n: int = 600) -> dict | None:
    """Analysis result for the Job object: full segments, per_second and a downsampled timeline
    (the full arrays live in analysis.json)."""
    if not analysis:
        return None
    tl = analysis.get("timeline") or {}
    return {
        "verdict": analysis.get("verdict"),
        "per_second": analysis.get("per_second", []),
        "segments": analysis.get("segments", []),
        "timeline": {k: downsample(v, n) for k, v in tl.items() if isinstance(v, list)},
    }


# ---------------------------------------------------------------- endpoint logic


class Api:
    def __init__(self, ctx: Context):
        self.ctx = ctx

    # helpers
    def _job(self, job_id: str) -> dict:
        if not _JOB_ID_RE.match(job_id or ""):
            raise ApiError(404, "job not found")
        job = self.ctx.jobs.get(job_id)
        if job is None:
            raise ApiError(404, "job not found")
        return job

    def _set_status(self, job: dict, status: str, **fields) -> dict:
        check_transition(job["status"], status)
        return self.ctx.jobs.update(job["job_id"], {"status": status, **fields})

    def _enqueue(self, job: dict, detail: str) -> dict:
        job = self._set_status(
            job, "queued", progress={"stage": "queued", "detail": detail, "fraction": 0.02}
        )
        self.ctx.queue.send({"job_id": job["job_id"]})
        return {"job_id": job["job_id"], "status": "queued"}

    # endpoints
    def health(self) -> dict:
        return {
            "ok": True,
            "opencv": opencv_version(),
            "version": tool_version(),
            "mode": self.ctx.mode,
        }

    def samples(self) -> list[dict]:
        from . import samples as sm

        if self.ctx.mode == "local":
            sm.ensure_local(self.ctx.store)
        present = {k.rsplit("/", 1)[-1].rsplit(".", 1)[0] for k in self.ctx.store.list("samples/")}
        return [sm.public(s) for s in sm.SAMPLES if s["id"] in present]

    def create_job(self, body: dict, prefix: str = "") -> dict:
        job = new_job(body)
        self.ctx.jobs.put(job)
        target = self.ctx.store.upload_target(
            job["job_id"], job["_input_key"], job["input"]["content_type"], prefix
        )
        return {"job_id": job["job_id"], "upload": target}

    def upload(self, job_id: str, data: bytes, content_type: str | None = None) -> dict:
        if self.ctx.mode != "local":
            raise ApiError(405, "upload with the presigned URL returned by POST /jobs")
        job = self._job(job_id)
        if job["status"] not in ("created", "uploaded"):
            raise ApiError(409, f"job is {job['status']}")
        if len(data) == 0:
            raise ApiError(400, "empty upload")
        if len(data) > MAX_BYTES:
            self._set_status(job, "error", error=f"file is {len(data)} bytes; the limit is 100 MB")
            raise ApiError(413, "file is larger than 100 MB")
        self.ctx.store.put_bytes(job["_input_key"], data, job["input"]["content_type"])
        self._set_status(
            job,
            "uploaded",
            progress={"stage": "uploaded", "detail": "upload received", "fraction": 0.01},
            downloads={**job["downloads"], INPUT_KIND: True},
        )
        return {"ok": True}

    def start(self, job_id: str) -> dict:
        job = self._job(job_id)
        if job["status"] == "queued":
            return {"job_id": job_id, "status": "queued"}
        if job["status"] not in ("created", "uploaded"):
            raise ApiError(409, f"job is {job['status']}")
        key = job["_input_key"]
        if not self.ctx.store.exists(key):
            raise ApiError(400, "upload not found; PUT the file first")
        size = self.ctx.store.size(key)
        if size > MAX_BYTES:
            self.ctx.store.delete(key)
            self._set_status(job, "error", error=f"file is {size} bytes; the limit is 100 MB")
            raise ApiError(413, "file is larger than 100 MB")
        if job["status"] == "created":
            job = self._set_status(job, "uploaded")
        job["input"]["size_bytes"] = size
        job["downloads"] = {**job.get("downloads", {}), INPUT_KIND: True}
        self.ctx.jobs.update(job_id, {"input": job["input"], "downloads": job["downloads"]})
        return self._enqueue(job, "waiting for a worker")

    def from_sample(self, body: dict) -> dict:
        from . import samples as sm

        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        sid = str(body.get("sample_id") or "")
        meta = sm.by_id(sid)
        if meta is None or not _SAMPLE_ID_RE.match(sid):
            raise ApiError(404, "unknown sample")
        if self.ctx.mode == "local":
            sm.ensure_local(self.ctx.store)
        src = sample_key(sid)
        if not self.ctx.store.exists(src):
            raise ApiError(404, "sample clip is not in the bucket")
        job = new_job(
            {
                "filename": f"{sid}.mp4",
                "content_type": "video/mp4",
                "size_bytes": self.ctx.store.size(src),
                "duration_s": meta["duration_s"],
                "profile": body.get("profile", "wcag"),
                "policy": body.get("policy", "fixed"),
                "conservative": body.get("conservative", False),
            }
        )
        job["input"]["sample_id"] = sid
        self.ctx.jobs.put(job)
        self.ctx.store.copy(src, job["_input_key"])
        job = self._set_status(job, "uploaded", downloads={**job["downloads"], INPUT_KIND: True})
        return self._enqueue(job, "waiting for a worker")

    def get_job(self, job_id: str) -> dict:
        return public_job(self._job(job_id))

    def segments(self, job_id: str) -> dict:
        job = self._job(job_id)
        key = output_key(job_id, "segments.json")
        if self.ctx.store.exists(key):
            return {"segments": json.loads(self.ctx.store.get_bytes(key))}
        before = job.get("before") or {}
        return {
            "segments": [
                {**s, "region_series": None, "remediation": None}
                for s in before.get("segments", [])
            ]
        }

    def trace(self, job_id: str, after: int | str | None = 0) -> dict:
        job = self._job(job_id)
        try:
            after_i = int(after or 0)
        except (TypeError, ValueError) as e:
            raise ApiError(400, "after must be an integer") from e
        records = self.ctx.jobs.traces(job_id, after_i)
        return {"records": records, "complete": job["status"] in TERMINAL}

    def approve(self, job_id: str, body: dict) -> dict:
        job = self._job(job_id)
        if job["status"] != "needs_approval":
            raise ApiError(409, f"job is {job['status']}, not needs_approval")
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        sid = str(body.get("segment_id") or "")
        pending = {p["segment_id"]: p for p in job.get("pending_approvals") or []}
        if sid not in pending:
            raise ApiError(400, f"segment {sid!r} is not waiting for approval")
        approved = body.get("approved")
        if not isinstance(approved, bool):
            raise ApiError(400, "approved must be true or false")
        options = [o.get("candidate_id") for o in pending[sid].get("options") or []]
        cid = body.get("candidate_id")
        if cid is not None and options and cid not in options:
            raise ApiError(400, f"candidate {cid!r} is not one of the offered options {options}")
        if approved and cid is None and options:
            cid = options[0]
        decisions = dict((job.get("_resume") or {}).get("decisions") or {})
        decisions[sid] = {
            "approved": approved,
            "candidate_id": cid,
            "by": "human",
            "decided_at": now_iso(),
        }
        self.ctx.jobs.update(job_id, {"_resume": {"decisions": decisions}})
        job["_resume"] = {"decisions": decisions}
        return self._enqueue(job, "decision received; waiting for a worker to resume")

    def download(self, job_id: str, kind: str | None, prefix: str = "") -> dict:
        job = self._job(job_id)
        if kind == INPUT_KIND:
            key = job["_input_key"]
        elif kind in DOWNLOAD_KINDS:
            key = output_key(job_id, DOWNLOAD_KINDS[kind][0])
        else:
            raise ApiError(400, f"kind must be one of {[*DOWNLOAD_KINDS, INPUT_KIND]}")
        if not (job.get("downloads") or {}).get(kind) and not self.ctx.store.exists(key):
            raise ApiError(404, f"{kind} is not available for this job")
        return {"url": self.ctx.store.download_url(key, prefix), "kind": kind}

    def frame_key(self, job_id: str, segment_id: str) -> str:
        self._job(job_id)
        if not _SEGMENT_ID_RE.match(segment_id or ""):
            raise ApiError(404, "no still for that segment")
        key = output_key(job_id, f"stills/{segment_id}.png")
        if not self.ctx.store.exists(key):
            raise ApiError(404, "no still for that segment")
        return key
