"""The LLM decision loop: perception (analyzer output) -> decision (tool call) -> action ->
perception again (verify) -> accept / escalate / ask a human.

The model only ever sees analyzer measurements, never pixels. Every model turn and tool
call is written to the trace. Any provider failure (timeout, throttling, malformed tool
call, repeated tool errors, turn budget) degrades to the fixed policy for whatever is
still open, and the report says which policy actually finished the job."""

from __future__ import annotations

import json

from ..remediate.registry import describe
from .policy_fixed import run_fixed_policy
from .providers import ModelResponse, Provider, ProviderError, load_config
from .tools import ApprovalPending, Job, ToolError

TOOL_SPECS: list[dict] = [
    {
        "name": "analyze_video",
        "description": "Run the OpenCV 5 photosensitivity analyzer on the job's video. Returns the overall verdict, video metadata, every hazard segment with its measurements (type, time range, peak flash rate, area fraction, luminance swing, regions, severity) and the strategy catalogue.",
        "inputSchema": {
            "json": {"type": "object", "properties": {}, "additionalProperties": False}
        },
    },
    {
        "name": "get_segment_detail",
        "description": "Details for one hazard segment: measurements, the region's luminance over time, applicable strategies, parameter hints derived from the measurements, attempts so far and the remaining iteration budget.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {"segment_id": {"type": "string"}},
                "required": ["segment_id"],
                "additionalProperties": False,
            }
        },
    },
    {
        "name": "apply_remediation",
        "description": "Render a candidate fix for a segment with a strategy (S1..S6) and parameters. Returns a candidate_id and quality metrics (SSIM inside/outside the regions, luminance change). Costs one iteration of the budget.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "strategy": {"type": "string", "enum": ["S1", "S2", "S3", "S4", "S5", "S6"]},
                    "params": {
                        "type": "object",
                        "description": "strategy parameters; see the catalogue from analyze_video. Omit for defaults.",
                    },
                },
                "required": ["segment_id", "strategy"],
                "additionalProperties": False,
            }
        },
    },
    {
        "name": "verify_candidate",
        "description": "Re-run the analyzer on a candidate. Returns passes_for_type (the hazard type is gone), any remaining hazards, quality metrics and whether human approval is required before this candidate can be accepted.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {"candidate_id": {"type": "string"}},
                "required": ["candidate_id"],
                "additionalProperties": False,
            }
        },
    },
    {
        "name": "request_human_approval",
        "description": "Pause the job and ask a human to approve one of the listed candidates (required for S6 and for low-quality fixes, or when nothing passes). The job resumes with their decision.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "candidate_id": {"type": "string"},
                                "strategy": {"type": "string"},
                                "params": {"type": "object"},
                            },
                            "required": ["candidate_id"],
                        },
                    },
                },
                "required": ["segment_id", "reason", "options"],
                "additionalProperties": False,
            }
        },
    },
    {
        "name": "accept_candidate",
        "description": "Accept a verified candidate as the fix for its segment.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {"candidate_id": {"type": "string"}},
                "required": ["candidate_id"],
                "additionalProperties": False,
            }
        },
    },
    {
        "name": "finalize",
        "description": "Declare the job done. Fails if any segment is still open. After this the pipeline renders the full video with every accepted fix and re-verifies the whole file.",
        "inputSchema": {
            "json": {"type": "object", "properties": {}, "additionalProperties": False}
        },
    },
]


def system_prompt(profile_name: str) -> str:
    cat = "\n".join(
        f"- {s['id']} {s['name']} (invasiveness {s['invasiveness']}, {s['scope']}, for {', '.join(s['applies_to'])}"
        f"{', needs human approval' if s['requires_approval'] else ''}): {s['doc']}. Params: "
        + ", ".join(
            f"{k}={v.get('default')} [{v.get('min', '-')}..{v.get('max', '-')}]"
            for k, v in s["params"].items()
        )
        for s in describe()
    )
    return f"""You are the remediation planner of SteadyFrame. A video failed a photosensitivity check
(profile: {profile_name}; thresholds from WCAG 2.3.1 / ITU-R BT.1702). Your objective: make every
hazard segment pass re-verification with the smallest visible change, using the tools.

Rules:
1. Start with analyze_video. Work segment by segment, most severe first if you like.
2. Read get_segment_detail before choosing: use the measured flash rate, luminance swing (max_delta_L),
   area fraction and the parameter_hints. Prefer regional strategies (S1, S2, S3) over global (S4, S5),
   and S6 only as a last resort.
3. Every candidate must be verified with verify_candidate. If it still fails, change the parameters
   (for example a lower S1 alpha) or escalate to a more invasive strategy. Explain in one sentence
   what the verify result told you and why the next call follows from it.
4. accept_candidate only after a passing verify. If verify says requires_approval, call
   request_human_approval with that candidate before accepting.
5. Respect the iteration budget shown in the detail. When it is exhausted, request_human_approval
   with the candidates you have. If the detail shows a human decision that approved a candidate
   (approval.decision.approved with a candidate_id), accept that candidate; if it was rejected,
   try something else.
6. Call finalize when every segment is accepted. Do not describe pixels; you never see them.
   Keep messages short: one or two sentences of reasoning per turn.

Strategy catalogue:
{cat}
"""


def _tool_result(tool_use_id: str, payload: dict, *, error: str | None = None) -> dict:
    if error is not None:
        return {
            "toolResult": {
                "toolUseId": tool_use_id,
                "content": [{"text": error}],
                "status": "error",
            }
        }
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"json": _jsonable(payload)}],
            "status": "success",
        }
    }


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def run_agent(job: Job, provider: Provider | None = None, *, config: dict | None = None) -> str:
    """Drive the job with a model. Returns the policy label that finished it."""
    cfg = config or load_config()
    loop_cfg = cfg.get("loop", {})
    max_turns = int(loop_cfg.get("max_turns", 40))
    max_err = int(loop_cfg.get("max_consecutive_errors", 3))
    if provider is None:
        from .providers import BedrockProvider

        try:
            provider = BedrockProvider(config=cfg.get("bedrock", {}))
        except ProviderError as e:
            job.trace.log("error", "provider", error=str(e), fallback="fixed")
            run_fixed_policy(job, by="fixed-fallback")
            return "fixed (no model available)"

    llm = job.state.setdefault(
        "llm",
        {
            "provider": provider.name,
            "turns": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_s": 0.0,
            "errors": [],
        },
    )
    system = system_prompt(job.profile.name)
    messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {"text": "A new job started. Analyze the video and remediate every hazard segment."}
            ],
        }
    ]
    consecutive_errors = 0
    finalized = False
    nudged = False
    fallback_reason: str | None = None

    for turn in range(max_turns):
        try:
            resp: ModelResponse = provider.converse(system, messages, TOOL_SPECS)
        except ProviderError as e:
            llm["errors"].append({"turn": turn, "kind": e.kind, "message": str(e)})
            job.trace.log("error", "model", turn=turn, error_kind=e.kind, error=str(e))
            fallback_reason = f"model {e.kind}"
            break
        llm["turns"] += 1
        llm["input_tokens"] += resp.input_tokens
        llm["output_tokens"] += resp.output_tokens
        llm["latency_s"] = round(llm["latency_s"] + resp.latency_s, 3)
        job.trace.model(
            "turn",
            turn=turn,
            text=resp.text,
            tool_calls=[{"name": t.name, "input": t.input} for t in resp.tool_calls],
            stop_reason=resp.stop_reason,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            latency_s=round(resp.latency_s, 3),
        )
        messages.append(resp.as_message())
        job.save()

        if not resp.tool_calls:
            if finalized or (not job.open_segments() and job.state.get("analysis") is not None):
                break
            if nudged:
                fallback_reason = "model stopped with open segments"
                break
            nudged = True
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "text": "Segments are still open: "
                            + ", ".join(job.open_segments() or ["(none analyzed yet)"])
                            + ". Continue with the tools, or call finalize."
                        }
                    ],
                }
            )
            continue

        results: list[dict] = []
        for tc in resp.tool_calls:
            try:
                payload = _dispatch(job, tc.name, tc.input)
                consecutive_errors = 0
                if tc.name == "finalize" and payload.get("ok"):
                    finalized = True
            except ApprovalPending:
                raise
            except ToolError as e:
                consecutive_errors += 1
                llm["errors"].append({"turn": turn, "kind": "tool_error", "message": str(e)})
                results.append(_tool_result(tc.id, {}, error=str(e)))
                continue
            except Exception as e:  # anything else a tool raised: report to the model, count it
                consecutive_errors += 1
                llm["errors"].append(
                    {"turn": turn, "kind": "tool_exception", "message": f"{type(e).__name__}: {e}"}
                )
                job.trace.log("error", "tool", name=tc.name, error=f"{type(e).__name__}: {e}")
                results.append(_tool_result(tc.id, {}, error=f"{type(e).__name__}: {e}"))
                continue
            results.append(_tool_result(tc.id, payload))
        messages.append({"role": "user", "content": results})
        if consecutive_errors >= max_err:
            fallback_reason = f"{consecutive_errors} consecutive tool errors"
            break
        if finalized:
            break
    else:
        fallback_reason = f"turn budget ({max_turns}) exhausted"

    if fallback_reason and job.open_segments():
        job.trace.decision(
            "fallback", reason=fallback_reason, policy="fixed", open_segments=job.open_segments()
        )
        llm["fallback"] = fallback_reason
        job.save()
        run_fixed_policy(job, by="fixed-fallback")
        return f"agent[{provider.name}]+fixed-fallback"
    if fallback_reason:
        llm["fallback"] = fallback_reason
        job.save()
    return f"agent[{provider.name}]"


def _dispatch(job: Job, name: str, args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolError(f"arguments for {name} must be an object")
    by = "model"
    if name == "analyze_video":
        return job.analyze_video(by=by)
    if name == "get_segment_detail":
        return job.get_segment_detail(_req(args, "segment_id"), by=by)
    if name == "apply_remediation":
        params = args.get("params") or {}
        if not isinstance(params, dict):
            raise ToolError("params must be an object")
        return job.apply_remediation(
            _req(args, "segment_id"), _req(args, "strategy"), params, by=by
        )
    if name == "verify_candidate":
        return job.verify_candidate(_req(args, "candidate_id"), by=by)
    if name == "request_human_approval":
        opts = args.get("options") or []
        if not isinstance(opts, list):
            raise ToolError("options must be a list")
        return job.request_human_approval(
            _req(args, "segment_id"), str(args.get("reason", "")), opts, by=by
        )
    if name == "accept_candidate":
        return job.accept_candidate(_req(args, "candidate_id"), by=by)
    if name == "finalize":
        open_ = job.open_segments()
        pending = [k for k, o in job.state["segments"].items() if o["status"] == "pending_approval"]
        if open_:
            raise ToolError(f"segments still open: {', '.join(open_)}")
        job.trace.decision("finalize_requested", by=by, pending=pending)
        return {
            "ok": True,
            "open_segments": [],
            "pending_approval": pending,
            "accepted": [k for k, o in job.state["segments"].items() if o["status"] == "accepted"],
        }
    raise ToolError(f"unknown tool {name!r}")


def _req(args: dict, key: str) -> str:
    v = args.get(key)
    if not isinstance(v, str) or not v:
        raise ToolError(f"missing or invalid '{key}'")
    return v


__all__ = ["run_agent", "system_prompt", "TOOL_SPECS"]
