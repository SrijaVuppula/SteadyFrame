#!/usr/bin/env python
"""CDK app: `cd infra && cdk synth --no-lookups` / `cdk deploy --all`.

Context (cdk.json or `-c key=value`):
  alert_email        e-mail for the CloudWatch alarms (empty: topic without subscription)
  bedrock_model_id   inference profile id the worker may call (empty: fixed policy only)
  skip_docker_build  "true" substitutes a public placeholder image for the worker so the
                     app synthesises without Docker (CI and tests); never deploy with it
  web_origin         CORS origin for browser PUTs to the bucket (default "*")
  web_dist           frontend build directory (default web/dist; a placeholder page is
                     deployed when it does not exist yet)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from aws_cdk import App, Tags  # noqa: E402
from stacks.api import ApiStack  # noqa: E402
from stacks.data import DataStack  # noqa: E402
from stacks.observability import ObservabilityStack  # noqa: E402
from stacks.queue import QueueStack  # noqa: E402
from stacks.storage import StorageStack  # noqa: E402
from stacks.web import WebStack  # noqa: E402
from stacks.worker import WorkerStack  # noqa: E402


def _flag(app: App, key: str) -> bool:
    v = app.node.try_get_context(key)
    return str(v).lower() in ("1", "true", "yes") if v is not None else False


def pinned_versions() -> tuple[str, str]:
    """(package version, opencv wheel version) read from pyproject.toml / requirements.lock so
    the Lambda can report them without importing the package."""
    py = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', py, re.M)
    version = m.group(1) if m else "0.1.0"
    lock = (ROOT / "requirements.lock").read_text()
    m = re.search(r"^opencv-python-headless==([\d.]+)", lock, re.M)
    return version, (m.group(1) if m else "5.0.0")


def samples_dir(skip: bool) -> Path:
    """Render the sample clips for the bucket deployment (gitignored: they flash)."""
    d = HERE / ".samples"
    expected = [d / "sample_strobe_region.mp4", d / "sample_red_strobe.mp4", d / "sample_clean.mp4"]
    if all(p.exists() for p in expected):
        return d
    try:
        from service.samples import generate

        generate(d)
    except Exception as e:  # no cv2 here (or synth on a box without the venv)
        if not skip:
            raise
        d.mkdir(parents=True, exist_ok=True)
        (d / "README.txt").write_text(f"placeholder; samples were not generated: {e}\n")
    return d


def web_dist(app: App) -> Path:
    d = Path(app.node.try_get_context("web_dist") or ROOT / "web" / "dist")
    if (d / "index.html").exists():
        return d
    return HERE / "web_placeholder"


def build(app: App) -> dict:
    skip = _flag(app, "skip_docker_build")
    alert_email = app.node.try_get_context("alert_email") or ""
    model_id = app.node.try_get_context("bedrock_model_id") or ""
    web_origin = app.node.try_get_context("web_origin") or "*"
    version, opencv = pinned_versions()

    storage = StorageStack(
        app, "SteadyFrame-Storage", samples_dir=samples_dir(skip), web_origin=web_origin
    )
    data = DataStack(app, "SteadyFrame-Data")
    queue = QueueStack(app, "SteadyFrame-Queue")
    api = ApiStack(
        app,
        "SteadyFrame-Api",
        bucket=storage.bucket,
        jobs=data.jobs,
        traces=data.traces,
        queue=queue.queue,
        version=version,
        opencv_version=opencv,
    )
    worker = WorkerStack(
        app,
        "SteadyFrame-Worker",
        bucket=storage.bucket,
        jobs=data.jobs,
        traces=data.traces,
        queue=queue.queue,
        bedrock_model_id=model_id,
        skip_docker_build=skip,
    )
    web = WebStack(app, "SteadyFrame-Web", api_endpoint=api.api_url, dist_dir=web_dist(app))
    obs = ObservabilityStack(
        app,
        "SteadyFrame-Observability",
        queue=queue.queue,
        dlq=queue.dlq,
        service=worker.service,
        api_function=api.function,
        alert_email=alert_email,
    )
    stacks = {
        "storage": storage,
        "data": data,
        "queue": queue,
        "api": api,
        "worker": worker,
        "web": web,
        "observability": obs,
    }
    for s in stacks.values():
        Tags.of(s).add("project", "steadyframe")
    return stacks


if __name__ == "__main__":
    cdk_app = App()
    build(cdk_app)
    cdk_app.synth()
