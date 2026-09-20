"""End-to-end smoke test against a deployed stack or the local compose API.

    python service/smoke.py --outputs infra/cdk-outputs.json
    python service/smoke.py --base-url http://localhost:8000

Creates a job from the region-strobe sample, polls until the job is terminal (15 min limit),
asserts it passed, downloads the report and checks report['after']['verdict'] == 'pass'.
Exit code 0 on success. Only the standard library is needed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TERMINAL = ("passed", "failed_verification", "no_hazards", "error", "needs_approval")


def _request(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _json(url: str, method: str = "GET", body: dict | None = None) -> dict:
    status, raw = _request(url, method, body)
    try:
        doc = json.loads(raw or b"{}")
    except ValueError:
        doc = {"raw": raw[:200].decode(errors="replace")}
    if status >= 400:
        raise SystemExit(f"{method} {url} -> {status}: {doc}")
    return doc


def base_from_outputs(path: str) -> str:
    outputs = json.load(open(path))
    for stack in outputs.values():
        for k, v in stack.items():
            if k == "ApiUrl":
                return v
    raise SystemExit(f"no ApiUrl output in {path}")


def run(
    base: str, *, sample: str, policy: str, profile: str, timeout_s: float, poll_s: float
) -> int:
    base = base.rstrip("/")
    t0 = time.time()
    health = _json(f"{base}/health")
    print(f"health: {health}")
    if not health.get("ok"):
        raise SystemExit("health check failed")
    samples = _json(f"{base}/samples")
    ids = [s["id"] for s in samples]
    print(f"samples: {ids}")
    if sample not in ids:
        raise SystemExit(f"sample {sample} not offered")
    job = _json(
        f"{base}/jobs/from-sample",
        "POST",
        {"sample_id": sample, "profile": profile, "policy": policy},
    )
    job_id = job["job_id"]
    t_created = time.time()
    print(f"job {job_id}: {job['status']}")
    last = None
    while True:
        j = _json(f"{base}/jobs/{job_id}")
        line = (j["status"], (j.get("progress") or {}).get("detail"))
        if line != last:
            print(f"  {time.time() - t_created:6.1f}s  {j['status']:20s} {line[1] or ''}")
            last = line
        if j["status"] in TERMINAL:
            break
        if time.time() - t_created > timeout_s:
            raise SystemExit(f"timed out after {timeout_s}s in status {j['status']}")
        time.sleep(poll_s)
    t_done = time.time()
    if j["status"] != "passed":
        raise SystemExit(f"job ended with status {j['status']}: {j.get('error')}")
    dl = _json(f"{base}/jobs/{job_id}/download?kind=report")
    url = urllib.parse.urljoin(base + "/", dl["url"])
    status, raw = _request(url)
    if status >= 400:
        raise SystemExit(f"report download failed: {status}")
    report = json.loads(raw)
    after = (report.get("after") or {}).get("verdict")
    print(
        f"report: status={report['status']} before={report['before']['verdict']} after={after} "
        f"iterations={report['iterations']} runtime_s={report['runtime_s']} opencv={report['tool']['opencv']['version']}"
    )
    if after != "pass":
        raise SystemExit(f"after verdict is {after}, expected pass")
    for kind in ("video", "analysis", "trace", "plot", "summary"):
        d = _json(f"{base}/jobs/{job_id}/download?kind={kind}")
        st, _ = _request(urllib.parse.urljoin(base + "/", d["url"]))
        print(f"  download {kind}: {st}")
        if st >= 400:
            raise SystemExit(f"{kind} download failed")
    segs = _json(f"{base}/jobs/{job_id}/segments")["segments"]
    if segs:
        st, body = _request(f"{base}/jobs/{job_id}/frames/{segs[0]['id']}.png")
        is_png = body[:8] == b"\x89PNG\r\n\x1a\n"
        print(f"  frame {segs[0]['id']}: {st} ({len(body)} bytes, png={is_png})")
    trace = _json(f"{base}/jobs/{job_id}/trace")
    print(f"  trace records: {len(trace['records'])} complete={trace['complete']}")
    print(
        f"timings: total {t_done - t0:.1f}s, queued->terminal {t_done - t_created:.1f}s, "
        f"pipeline {report['runtime_s']}s"
    )
    print("SMOKE OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outputs", help="cdk outputs json (uses the ApiUrl output)")
    ap.add_argument("--base-url", help="API base URL, e.g. http://localhost:8000")
    ap.add_argument("--sample", default="sample_strobe_region")
    ap.add_argument("--policy", default="fixed", choices=["fixed", "agent"])
    ap.add_argument("--profile", default="wcag", choices=["wcag", "broadcast"])
    ap.add_argument("--timeout", type=float, default=15 * 60)
    ap.add_argument("--poll", type=float, default=3.0)
    args = ap.parse_args(argv)
    if not args.base_url and not args.outputs:
        ap.error("--outputs or --base-url is required")
    base = args.base_url or base_from_outputs(args.outputs)
    return run(
        base,
        sample=args.sample,
        policy=args.policy,
        profile=args.profile,
        timeout_s=args.timeout,
        poll_s=args.poll,
    )


if __name__ == "__main__":
    sys.exit(main())
