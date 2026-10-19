"""Worker on AWS Lambda (arm64): the same JobRunner as the ECS worker, fed by the SQS queue.

The ECS service scales from zero, and a cold Fargate task took 505 s to pick up the first job
on the deployed stack. A Lambda container starts in seconds and costs nothing while idle, so
it takes the jobs first; the Fargate service stays as the fallback for anything left waiting in
the queue. One message per invocation (batch size 1); a message whose job raises outside the
runner's own error handling is reported back as a batch item failure and retried, then lands in
the dead-letter queue like an ECS failure would.

A schedule invokes it every five minutes with ``{"warmup": true}`` so an execution environment
with OpenCV already loaded is waiting when a judge presses "run"; that costs a few thousand
short invocations a month, inside the Lambda free tier.

Handler: ``service.lambda_worker.handler`` (see the ``lambda`` target in the Dockerfile).
"""

from __future__ import annotations

import json
import os

from . import core
from .worker import JobRunner, Metrics, log

_runner: JobRunner | None = None


def _get_runner() -> JobRunner:
    """One runner per execution environment, created on the first message."""
    global _runner
    if _runner is None:
        import cv2

        import steadyframe  # asserts OpenCV 5

        if not cv2.__version__.startswith("5."):
            raise RuntimeError(f"OpenCV 5.x is required, found {cv2.__version__}")
        ctx = core.Context.from_env()
        log(
            "info",
            "lambda worker starting",
            opencv=cv2.__version__,
            steadyframe=steadyframe.__version__,
            build=steadyframe.opencv_build_summary(),
            engine=os.environ.get("STEADYFRAME_OPENCV_ENGINE", "stock"),
            mode=ctx.mode,
        )
        _runner = JobRunner(ctx, Metrics(ctx.mode))
    return _runner


def handler(event: dict, context=None) -> dict:
    if isinstance(event, dict) and event.get("warmup"):
        # the five-minute schedule: load OpenCV, the runner and matplotlib (its font cache goes
        # to /tmp on first import) so the next job starts at once
        _get_runner()
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot  # noqa: F401

        return {"warm": True}
    failures = []
    for rec in event.get("Records") or []:
        msg_id = rec.get("messageId", "")
        try:
            body = json.loads(rec.get("body") or "{}")
        except json.JSONDecodeError:
            log("warn", "dropping a message that is not JSON", message_id=msg_id)
            continue  # retrying cannot fix it
        job_id = body.get("job_id") if isinstance(body, dict) else None
        if not job_id:
            log("warn", "dropping a message without job_id", message_id=msg_id)
            continue
        try:
            _get_runner().run(job_id)  # marks the job as error itself on pipeline failures
        except Exception as e:  # anything the runner did not handle: let SQS retry it
            log("error", "lambda worker failed", job_id=job_id, error=f"{type(e).__name__}: {e}")
            failures.append({"itemIdentifier": msg_id})
    return {"batchItemFailures": failures}
