"""Local API for ``docker compose up`` and offline judges.

Same routes as the Lambda (docs/API.md), served under both ``/`` and ``/api`` so the
frontend's default ``VITE_API_BASE=/api`` works with or without nginx in front. Files are
served straight from the local store under ``/files/<key>``. Unless LOCAL_INLINE_WORKER=0,
a worker thread runs in-process so a single container is a complete system.

    uvicorn --factory service.local_api:create_app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import contextlib
import os
import threading

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .core import Api, ApiError, Context


def _prefix(request: Request) -> str:
    return "/api" if request.url.path.startswith("/api/") else ""


def build_router(api: Api) -> APIRouter:
    r = APIRouter()

    @r.get("/health")
    def health():
        return api.health()

    @r.get("/samples")
    def samples():
        return api.samples()

    @r.post("/jobs")
    async def create_job(request: Request):
        return api.create_job(await _json(request), _prefix(request))

    @r.post("/jobs/from-sample")
    async def from_sample(request: Request):
        return api.from_sample(await _json(request))

    @r.put("/jobs/{job_id}/upload")
    async def upload(job_id: str, request: Request):
        data = await request.body()
        return api.upload(job_id, data, request.headers.get("content-type"))

    @r.post("/jobs/{job_id}/start")
    def start(job_id: str):
        return api.start(job_id)

    @r.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return api.get_job(job_id)

    @r.get("/jobs/{job_id}/segments")
    def segments(job_id: str):
        return api.segments(job_id)

    @r.get("/jobs/{job_id}/trace")
    def trace(job_id: str, after: int = 0):
        return api.trace(job_id, after)

    @r.post("/jobs/{job_id}/approve")
    async def approve(job_id: str, request: Request):
        return api.approve(job_id, await _json(request))

    @r.get("/jobs/{job_id}/download")
    def download(job_id: str, request: Request, kind: str | None = None):
        return api.download(job_id, kind, _prefix(request))

    @r.get("/jobs/{job_id}/frames/{segment_id}.png")
    def frame(job_id: str, segment_id: str):
        key = api.frame_key(job_id, segment_id)
        return FileResponse(api.ctx.store.path(key), media_type="image/png")

    return r


async def _json(request: Request) -> dict:
    body = await request.body()
    if not body:
        return {}
    try:
        import json

        return json.loads(body)
    except ValueError as e:
        raise ApiError(400, "body is not valid JSON") from e


def create_app(ctx: Context | None = None, *, inline_worker: bool | None = None) -> FastAPI:
    ctx = ctx or Context.from_env()
    if ctx.mode != "local":
        raise RuntimeError("the local API only runs with STEADYFRAME_MODE=local")
    if inline_worker is None:
        inline_worker = os.environ.get("LOCAL_INLINE_WORKER", "1") != "0"
    api = Api(ctx)
    stop = threading.Event()

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        thread = None
        if inline_worker:
            from . import worker

            thread = threading.Thread(
                target=worker.run_loop,
                args=(ctx,),
                kwargs={"stop": stop, "wait_s": 1.0},
                daemon=True,
            )
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=5)

    app = FastAPI(title="SteadyFrame local API", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx
    app.state.api = api
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def _api_error(_request, exc: ApiError):
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    router = build_router(api)
    app.include_router(router)
    app.include_router(router, prefix="/api")
    files = StaticFiles(directory=str(ctx.store.root))
    app.mount("/files", files, name="files")
    app.mount("/api/files", files, name="api-files")
    return app
