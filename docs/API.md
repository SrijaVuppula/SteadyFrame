# SteadyFrame HTTP API

One API shape, two implementations: `service/lambda/` (API Gateway + Lambda, production)
and `service/local_api.py` (FastAPI, `docker compose up`). The frontend talks only to this.

All responses are JSON. Errors: `{"error": "message"}` with 4xx/5xx. CORS is open for GET/POST/PUT.

## Job lifecycle

```
created -> uploaded -> queued -> analyzing -> remediating -> rendering -> passed
                                                 |                      |-> failed_verification
                                                 |-> needs_approval --(approve)--> queued
                                     analyzing -> no_hazards
                                     any        -> error
```

## Endpoints

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/health` | | `{"ok": true, "opencv": "5.0.0", "version": "0.1.0", "mode": "aws"\|"local"}` |
| GET | `/samples` | | `[{"id": "sample_strobe_region", "name": "...", "description": "...", "hazard_types": ["general"], "duration_s": 5, "warning": true}]` |
| POST | `/jobs` | `{"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 123, "profile": "wcag"\|"broadcast", "policy": "fixed"\|"agent", "conservative": false}` | `{"job_id": "...", "upload": {"method": "PUT", "url": "<presigned or /jobs/{id}/upload>", "headers": {"Content-Type": "video/mp4"}}}` |
| PUT | `/jobs/{id}/upload` | raw bytes (local mode only; AWS uses the presigned S3 URL) | `{"ok": true}` |
| POST | `/jobs/{id}/start` | | `{"job_id": "...", "status": "queued"}` |
| POST | `/jobs/from-sample` | `{"sample_id": "...", "profile": "wcag", "policy": "fixed"}` | `{"job_id": "...", "status": "queued"}` |
| GET | `/jobs/{id}` | | Job object (below) |
| GET | `/jobs/{id}/segments` | | `{"segments": [Segment + {"region_series": {"t": [...], "L": [...]}, "remediation": {...} or null}]}` |
| GET | `/jobs/{id}/trace` | `?after=<seq>` | `{"records": [TraceRecord...], "complete": bool}` |
| POST | `/jobs/{id}/approve` | `{"segment_id": "g000", "approved": true, "candidate_id": "g000-c2"}` | `{"job_id": "...", "status": "queued"}` |
| GET | `/jobs/{id}/download` | `?kind=video\|report\|analysis\|trace\|plot\|summary` | `{"url": "<presigned GET, 15 min>", "kind": "video"}` (local mode: a direct URL) |
| GET | `/jobs/{id}/frames/{segment_id}.png` | | PNG still frame from the middle of the segment with the regions outlined. Never animated. |

Limits enforced server-side: 100 MB, 120 s, container in {mp4, mov, webm, mkv, gif}. Rejected
uploads get status `error` with `error` = reason.

## Job object

```json
{
  "job_id": "3f2a...", "status": "passed", "created_at": "2026-10-01T12:00:00Z", "updated_at": "...",
  "profile": "wcag", "policy": "fixed", "conservative": false,
  "input": {"filename": "clip.mp4", "width": 1280, "height": 720, "fps": 30.0, "duration_s": 12.4, "has_audio": true},
  "progress": {"stage": "remediating", "detail": "segment g001 attempt 2 (S2)", "fraction": 0.6},
  "before": {"verdict": "fail", "per_second": [...], "segments": [Segment...], "timeline": {"t": [...], "mean_L": [...], "general_rate_hz": [...], "red_rate_hz": [...]}},
  "after":  {"verdict": "pass", "per_second": [...], "segments": [], "timeline": {...}},
  "remediation": {"status": "passed", "iterations": 3, "runtime_s": 41.2, "quality": {"ssim_overall": 0.97, "ssim_outside": 0.999, "ssim_inside": 0.91, "mean_abs_dL_inside": 0.05},
                  "segments": [{"segment_id": "g000", "type": "general", "outcome": "accepted", "strategy": "S1", "params": {"alpha": 0.08}, "attempts": [...], "quality": {...}}]},
  "pending_approvals": [{"segment_id": "g001", "reason": "S6: strategy S6 always needs approval", "options": [{"candidate_id": "g001-c4", "strategy": "S6", "params": {}, "quality": {...}}]}],
  "downloads": {"video": true, "report": true, "analysis": true, "trace": true, "plot": true, "summary": true},
  "error": null,
  "tool": {"version": "0.1.0", "opencv": "5.0.0"}
}
```

`Segment` is the analysis.json segment (`steadyframe/schema.py`): `{id, type, verdict, start_frame,
end_frame, start_s, end_s, peak_flash_rate_hz, max_area_fraction, max_delta_L, regions: [{x,y,w,h}],
severity_score}`. `TraceRecord` is one line of `trace.jsonl` (`steadyframe/agent/trace.py`):
`{seq, job_id, t_rel_s, ts, kind: tool_call|tool_result|decision|model|error|job, name, args?, result?, error?, iteration?, by?}`.

## Storage layout (AWS)

```
s3://<bucket>/uploads/<job_id>/input.<ext>          lifecycle: delete after 1 day
s3://<bucket>/outputs/<job_id>/safe.mp4             report.json  analysis.json  trace.jsonl  plot.png
s3://<bucket>/outputs/<job_id>/stills/<segment>.png  summary.html
s3://<bucket>/outputs/<job_id>/work.tar             (paused jobs only: job.json + candidate clips)
dynamodb jobs   pk job_id                            the Job object minus timeline arrays (those live in analysis.json)
dynamodb traces pk job_id, sk seq                    TraceRecord
sqs  jobs queue -> ECS Fargate (ARM64) worker, message {"job_id": "..."}
```
