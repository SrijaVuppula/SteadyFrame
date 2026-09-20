"""Local-mode end-to-end tests of the service layer (FastAPI TestClient + the worker run
synchronously). No AWS, no Docker."""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from service import core, worker
from service.local_api import create_app

from .conftest import square_frames


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKER_WORKDIR", str(tmp_path / "work"))
    monkeypatch.setenv("STEADYFRAME_MODE", "local")
    return core.Context.local(tmp_path / "data")


@pytest.fixture
def client(ctx):
    app = create_app(ctx, inline_worker=False)
    with TestClient(app) as c:
        yield c


def _upload_and_start(client, path, prefix="", **fields):
    data = path.read_bytes()
    body = {"filename": path.name, "content_type": "video/mp4", "size_bytes": len(data), **fields}
    r = client.post(f"{prefix}/jobs", json=body)
    assert r.status_code == 200, r.text
    job_id, up = r.json()["job_id"], r.json()["upload"]
    assert up["method"] == "PUT" and up["url"] == f"{prefix}/jobs/{job_id}/upload"
    r = client.put(up["url"], content=data, headers=up["headers"])
    assert r.status_code == 200, r.text
    assert client.get(f"{prefix}/jobs/{job_id}").json()["status"] == "uploaded"
    r = client.post(f"{prefix}/jobs/{job_id}/start")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    return job_id


def test_health_and_api_prefix(client):
    for prefix in ("", "/api"):
        r = client.get(f"{prefix}/health")
        assert r.status_code == 200
        doc = r.json()
        assert doc["ok"] is True and doc["mode"] == "local"
        assert doc["opencv"].startswith("5.")


def test_end_to_end_fixed_policy(client, ctx, tmp_clip):
    frames = square_frames(120, 30, 6.0, size=(96, 72), region=(24, 18, 72, 54), start=1.0)
    src = tmp_clip(frames, codec="h264")
    job_id = _upload_and_start(client, src, prefix="/api")

    assert worker.process_one(ctx) is not None  # one message, processed synchronously
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "passed", job
    assert job["before"]["verdict"] == "fail" and job["after"]["verdict"] == "pass"
    assert job["input"]["width"] == 96 and job["input"]["fps"] == 30.0
    assert job["progress"]["fraction"] == 1.0
    assert job["remediation"]["segments"][0]["outcome"] == "accepted"
    assert set(job["before"]["timeline"]) >= {"t", "mean_L", "general_rate_hz", "red_rate_hz"}
    assert all(job["downloads"].values())
    assert job["downloads"]["input"] is True
    assert "_input_key" not in job and "_resume" not in job
    # the original upload stays downloadable for the click-through preview
    r = client.get(f"/api/jobs/{job_id}/download", params={"kind": "input"})
    assert r.status_code == 200 and r.json()["url"].startswith("/api/files/uploads/")
    assert client.get(r.json()["url"]).content == src.read_bytes()

    # downloads resolve to real files under the same prefix
    for kind in core.DOWNLOAD_KINDS:
        r = client.get(f"/api/jobs/{job_id}/download", params={"kind": kind})
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        assert url.startswith("/api/files/outputs/")
        f = client.get(url)
        assert f.status_code == 200 and len(f.content) > 0
    report = client.get(client.get(f"/jobs/{job_id}/download?kind=report").json()["url"]).json()
    assert report["status"] == "passed" and report["after"]["verdict"] == "pass"
    analysis = client.get(client.get(f"/jobs/{job_id}/download?kind=analysis").json()["url"]).json()
    assert analysis["verdict"] == "fail" and len(analysis["timeline"]["t"]) == 120
    assert analysis["after"]["verdict"] == "pass"
    summary = client.get(client.get(f"/jobs/{job_id}/download?kind=summary").json()["url"]).text
    assert "<video" not in summary and "autoplay" not in summary and "OpenCV 5." in summary

    # segments, trace, frames
    segs = client.get(f"/jobs/{job_id}/segments").json()["segments"]
    assert len(segs) == 1 and segs[0]["region_series"]["L"] and segs[0]["remediation"]["strategy"]
    tr = client.get(f"/jobs/{job_id}/trace").json()
    assert tr["complete"] is True
    names = [r["name"] for r in tr["records"]]
    assert "analyze_video" in names and "finalize" in names
    assert all(r["job_id"] == job_id for r in tr["records"])
    seqs = [r["seq"] for r in tr["records"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    later = client.get(f"/jobs/{job_id}/trace", params={"after": seqs[-3]}).json()["records"]
    assert len(later) == 2
    png = client.get(f"/jobs/{job_id}/frames/{segs[0]['id']}.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/jobs/{job_id}/frames/nope.png").status_code == 404
    assert client.get(f"/jobs/{job_id}/download?kind=bogus").status_code == 400
    assert client.get("/jobs/00000000000000000000000000000000").status_code == 404


def test_no_hazards(client, ctx, tmp_clip):
    src = tmp_clip(square_frames(60, 30, 1.0))
    job_id = _upload_and_start(client, src)
    worker.process_one(ctx)
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "no_hazards"
    assert job["downloads"]["video"] and job["before"]["segments"] == []


def test_approval_flow(client, tmp_clip, tmp_path, monkeypatch):
    monkeypatch.setenv("STEADYFRAME_APPROVAL_MIN_SSIM", "1.01")  # every candidate needs a human
    monkeypatch.setenv("WORKER_WORKDIR", str(tmp_path / "work"))
    ctx = client.app.state.ctx
    ctx.approval_min_ssim = 1.01
    src = tmp_clip(square_frames(90, 30, 6.0, start=0.5), codec="h264")
    job_id = _upload_and_start(client, src)
    worker.process_one(ctx)
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "needs_approval", job
    pend = job["pending_approvals"]
    assert len(pend) == 1 and pend[0]["options"]
    sid, cid = pend[0]["segment_id"], pend[0]["options"][0]["candidate_id"]
    assert job["downloads"]["video"] is False and job["downloads"]["report"] is True
    assert ctx.store.exists(core.output_key(job_id, "work.tar"))
    n_trace = len(client.get(f"/jobs/{job_id}/trace").json()["records"])

    # bad approvals are rejected
    assert (
        client.post(
            f"/jobs/{job_id}/approve", json={"segment_id": "zzz", "approved": True}
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/jobs/{job_id}/approve", json={"segment_id": sid, "approved": "yes"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/jobs/{job_id}/approve",
            json={"segment_id": sid, "approved": True, "candidate_id": "nope"},
        ).status_code
        == 400
    )
    r = client.post(
        f"/jobs/{job_id}/approve", json={"segment_id": sid, "approved": True, "candidate_id": cid}
    )
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert (
        client.post(
            f"/jobs/{job_id}/approve", json={"segment_id": sid, "approved": True}
        ).status_code
        == 409
    )

    worker.process_one(ctx)
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "passed", job
    seg = job["remediation"]["segments"][0]
    assert (
        seg["approval"]["decision"]["approved"] is True
        and seg["approval"]["decision"]["by"] == "human"
    )
    assert job["downloads"]["video"] is True
    records = client.get(f"/jobs/{job_id}/trace").json()["records"]
    assert len(records) > n_trace
    seqs = [r["seq"] for r in records]
    assert len(set(seqs)) == len(seqs) and seqs == sorted(seqs)
    assert any(r["name"] == "resumed" for r in records)
    trace_file = client.get(client.get(f"/jobs/{job_id}/download?kind=trace").json()["url"]).text
    assert len(trace_file.strip().splitlines()) == len(records)


def test_validation_rejects_bad_uploads(client, ctx, tmp_path):
    base = {"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 1000}
    r = client.post("/jobs", json={**base, "duration_s": 130})
    assert r.status_code == 413 and "120" in r.json()["error"]
    r = client.post("/jobs", json={**base, "size_bytes": core.MAX_BYTES + 1})
    assert r.status_code == 413
    r = client.post(
        "/jobs", json={**base, "filename": "clip.avi", "content_type": "video/x-msvideo"}
    )
    assert r.status_code == 400 and "container" in r.json()["error"]
    r = client.post("/jobs", json={**base, "content_type": "text/plain"})
    assert r.status_code == 400
    r = client.post("/jobs", json={**base, "profile": "strict"})
    assert r.status_code == 400
    assert client.post("/jobs", json={**base, "policy": "yolo"}).status_code == 400
    assert (
        client.post(
            "/jobs", content=b"not json", headers={"content-type": "application/json"}
        ).status_code
        == 400
    )

    # a file that claims to be mp4 but is not a video: the worker rejects it after probing
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"\x00" * 5000)
    job_id = _upload_and_start(client, junk)
    worker.process_one(ctx)
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "error" and job["error"]
    assert client.post(f"/jobs/{job_id}/start").status_code == 409
    assert client.get(f"/jobs/{job_id}/trace").json()["complete"] is True

    # start without an upload
    r = client.post("/jobs", json=base)
    assert client.post(f"/jobs/{r.json()['job_id']}/start").status_code == 400


def test_samples_and_from_sample(client, ctx):
    samples = client.get("/api/samples").json()
    ids = {s["id"] for s in samples}
    assert {"sample_strobe_region", "sample_red_strobe", "sample_clean"} <= ids
    assert all(
        {"name", "description", "hazard_types", "duration_s", "warning"} <= set(s) for s in samples
    )
    r = client.post(
        "/api/jobs/from-sample", json={"sample_id": "sample_strobe_region", "policy": "fixed"}
    )
    assert r.status_code == 200 and r.json()["status"] == "queued"
    job_id = r.json()["job_id"]
    worker.process_one(ctx)
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "passed", job
    assert job["input"]["filename"] == "sample_strobe_region.mp4"
    assert client.post("/jobs/from-sample", json={"sample_id": "nope"}).status_code == 404


def test_lambda_handler_routes_in_local_mode(ctx, monkeypatch):
    mod = importlib.import_module("service.lambda.handler")
    monkeypatch.setattr(mod, "_api", core.Api(ctx))

    def call(method, path, body=None, query=None):
        ev = {
            "rawPath": path,
            "requestContext": {"http": {"method": method}},
            "body": json.dumps(body) if body is not None else None,
            "queryStringParameters": query,
        }
        resp = mod.handler(ev, None)
        return resp["statusCode"], json.loads(resp["body"]) if resp["body"] else None

    st, doc = call("GET", "/api/health")
    assert st == 200 and doc["ok"] is True
    st, doc = call("GET", "/jobs/00000000000000000000000000000000")
    assert st == 404 and doc == {"error": "job not found"}
    st, doc = call(
        "POST", "/jobs", {"filename": "a.mp4", "content_type": "video/mp4", "size_bytes": 10}
    )
    assert st == 200 and "job_id" in doc and doc["upload"]["method"] == "PUT"
    st, doc = call("PUT", f"/jobs/{doc['job_id']}/upload")
    assert st == 405  # uploads go to the presigned URL in AWS mode; local mode says so too
    st, doc = call("GET", "/nothing")
    assert st == 404
    st, doc = call("DELETE", "/health")
    assert st == 405
    st, doc = call("POST", "/jobs", body=None)
    assert st == 400
    resp = mod.handler(
        {"rawPath": "/jobs", "requestContext": {"http": {"method": "OPTIONS"}}}, None
    )
    assert resp["statusCode"] == 204 and "access-control-allow-origin" in resp["headers"]


def test_status_transitions():
    core.check_transition("created", "uploaded")
    core.check_transition("needs_approval", "queued")
    core.check_transition("remediating", "error")
    with pytest.raises(core.ApiError):
        core.check_transition("passed", "queued")
    with pytest.raises(core.ApiError):
        core.check_transition("error", "queued")


def test_dynamo_conversion_round_trip():
    doc = {"a": 1.5, "b": [1, 2, {"c": 0.25}], "d": "x", "e": None, "f": True}
    conv = core.to_dynamo(doc)
    assert str(conv["a"]) == "1.5" and core.from_dynamo(conv) == doc
