"""API Gateway HTTP API -> one Lambda. Routes every endpoint in docs/API.md by method + path.

Packaged from the ``service/`` directory (handler ``lambda/handler.handler``), so ``core`` and
``samples`` are top-level modules there; in the repo they are ``service.core`` etc. Only boto3
is needed at runtime and it ships with the Python 3.11 runtime. cv2 is never imported here.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

try:
    from service import core
except ImportError:  # deployed layout: /var/task/{core.py, samples.py, lambda/handler.py}
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import core  # type: ignore[no-redef]

ApiError = core.ApiError
_ctx = None
_api = None

CORS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET,POST,PUT,OPTIONS",
    "access-control-allow-headers": "*",
}


def api() -> core.Api:
    global _ctx, _api
    if _api is None:
        _ctx = core.Context.from_env()
        _api = core.Api(_ctx)
    return _api


def _json_response(status: int, body, extra: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", **CORS, **(extra or {})},
        "body": json.dumps(body, default=core._json_default),
    }


def _redirect(url: str) -> dict:
    return {
        "statusCode": 302,
        "headers": {"location": url, "cache-control": "no-store", **CORS},
        "body": "",
    }


def _body(event: dict) -> dict:
    raw = event.get("body")
    if raw in (None, ""):
        return {}
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except ValueError as e:
        raise ApiError(400, "body is not valid JSON") from e
    return parsed if isinstance(parsed, dict) else {}


def _no_raw_upload():
    raise ApiError(405, "upload with the presigned URL returned by POST /jobs")


ROUTES = [
    ("GET", re.compile(r"^/health$"), lambda a, m, ev, q: a.health()),
    ("GET", re.compile(r"^/samples$"), lambda a, m, ev, q: a.samples()),
    ("POST", re.compile(r"^/jobs$"), lambda a, m, ev, q: a.create_job(_body(ev))),
    ("POST", re.compile(r"^/jobs/from-sample$"), lambda a, m, ev, q: a.from_sample(_body(ev))),
    ("PUT", re.compile(r"^/jobs/([^/]+)/upload$"), lambda a, m, ev, q: _no_raw_upload()),
    ("POST", re.compile(r"^/jobs/([^/]+)/start$"), lambda a, m, ev, q: a.start(m[1])),
    ("GET", re.compile(r"^/jobs/([^/]+)$"), lambda a, m, ev, q: a.get_job(m[1])),
    ("GET", re.compile(r"^/jobs/([^/]+)/segments$"), lambda a, m, ev, q: a.segments(m[1])),
    (
        "GET",
        re.compile(r"^/jobs/([^/]+)/trace$"),
        lambda a, m, ev, q: a.trace(m[1], q.get("after", 0)),
    ),
    (
        "POST",
        re.compile(r"^/jobs/([^/]+)/approve$"),
        lambda a, m, ev, q: a.approve(m[1], _body(ev)),
    ),
    (
        "GET",
        re.compile(r"^/jobs/([^/]+)/download$"),
        lambda a, m, ev, q: a.download(m[1], q.get("kind")),
    ),
    (
        "GET",
        re.compile(r"^/jobs/([^/]+)/frames/([^/]+)\.png$"),
        lambda a, m, ev, q: _redirect(a.ctx.store.download_url(a.frame_key(m[1], m[2]))),
    ),
]


def normalise_path(raw: str) -> str:
    path = raw or "/"
    if path.startswith("/api/") or path == "/api":
        path = path[4:] or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def handler(event: dict, context=None) -> dict:
    http = (event.get("requestContext") or {}).get("http") or {}
    method = (http.get("method") or event.get("httpMethod") or "GET").upper()
    path = normalise_path(event.get("rawPath") or event.get("path") or "/")
    query = event.get("queryStringParameters") or {}
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS, "body": ""}
    try:
        for m_method, pattern, fn in ROUTES:
            m = pattern.match(path)
            if not m:
                continue
            if m_method != method:
                continue
            result = fn(api(), m, event, query)
            if isinstance(result, dict) and "statusCode" in result and "headers" in result:
                return result
            return _json_response(200, result)
        if any(p.match(path) for _mm, p, _f in ROUTES):
            return _json_response(405, {"error": f"{method} not allowed on {path}"})
        return _json_response(404, {"error": "not found"})
    except ApiError as e:
        return _json_response(e.status, {"error": e.message})
    except Exception as e:  # keep the contract: JSON error bodies only
        print(
            json.dumps(
                {
                    "level": "error",
                    "msg": "unhandled",
                    "error": f"{type(e).__name__}: {e}",
                    "path": path,
                }
            )
        )
        return _json_response(500, {"error": "internal error"})
