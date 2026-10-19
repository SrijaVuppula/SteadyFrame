"""The Lambda worker: the same JobRunner as ECS, one SQS record per invocation."""

from __future__ import annotations

import json

import pytest

from service import core, lambda_worker

from .conftest import square_frames


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKER_WORKDIR", str(tmp_path / "work"))
    monkeypatch.setenv("STEADYFRAME_MODE", "local")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(lambda_worker, "_runner", None)
    return core.Context.local(tmp_path / "data")


def _queued_job(ctx, tmp_clip) -> str:
    src = tmp_clip(
        square_frames(120, 30, 6.0, size=(96, 72), region=(24, 18, 72, 54), start=1.0),
        codec="h264",
    )
    api = core.Api(ctx)
    data = src.read_bytes()
    job_id = api.create_job(
        {"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": len(data)}
    )["job_id"]
    api.upload(job_id, data, "video/mp4")
    api.start(job_id)
    return job_id


def _event(*bodies: str) -> dict:
    return {"Records": [{"messageId": f"m{i}", "body": b} for i, b in enumerate(bodies)]}


def test_handler_runs_the_job_to_completion(ctx, tmp_clip):
    job_id = _queued_job(ctx, tmp_clip)
    out = lambda_worker.handler(_event(json.dumps({"job_id": job_id})))
    assert out == {"batchItemFailures": []}
    job = core.Api(ctx).get_job(job_id)
    assert job["status"] == "passed"
    assert job["downloads"]["record"] and job["downloads"]["warnings"]


def test_bad_messages_are_dropped_not_retried(ctx):
    out = lambda_worker.handler(_event("not json", json.dumps({"nothing": 1}), "[]"))
    assert out == {"batchItemFailures": []}


def test_unexpected_errors_are_reported_for_retry(ctx, monkeypatch):
    class Boom:
        def run(self, job_id):
            raise RuntimeError("disk full")

    monkeypatch.setattr(lambda_worker, "_runner", Boom())
    out = lambda_worker.handler(_event(json.dumps({"job_id": "a" * 32})))
    assert out == {"batchItemFailures": [{"itemIdentifier": "m0"}]}


def test_warmup_loads_the_runner_and_touches_no_job(ctx):
    assert lambda_worker._runner is None
    assert lambda_worker.handler({"warmup": True}) == {"warm": True}
    assert lambda_worker._runner is not None
