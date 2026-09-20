"""Model providers behind one small interface.

Messages use the Bedrock Converse shape directly (it is vendor neutral enough):
  {"role": "user"|"assistant", "content": [{"text": ...} | {"toolUse": {...}} | {"toolResult": {...}}]}
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ProviderError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind  # timeout | throttled | malformed | unavailable | other


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # end_turn | tool_use | max_tokens
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0

    def as_message(self) -> dict:
        content: list[dict] = []
        if self.text:
            content.append({"text": self.text})
        for tc in self.tool_calls:
            content.append({"toolUse": {"toolUseId": tc.id, "name": tc.name, "input": tc.input}})
        return {"role": "assistant", "content": content or [{"text": ""}]}


class Provider:
    name = "base"

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> ModelResponse:
        raise NotImplementedError


def load_config(path: str | Path | None = None) -> dict:
    p = Path(
        path
        or os.environ.get(
            "STEADYFRAME_AGENT_CONFIG",
            Path(__file__).resolve().parents[2] / "config" / "agent.yaml",
        )
    )
    cfg = yaml.safe_load(p.read_text()) if p.exists() else {"bedrock": {}, "loop": {}}
    b = cfg.setdefault("bedrock", {})
    b["model_id"] = os.environ.get("STEADYFRAME_BEDROCK_MODEL_ID", b.get("model_id") or "")
    b["region"] = os.environ.get(
        "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", b.get("region") or "us-east-1")
    )
    cfg.setdefault("loop", {})
    return cfg


# ---------------------------------------------------------------- Bedrock


class BedrockProvider(Provider):
    """Amazon Bedrock Converse API with tool use (boto3 bedrock-runtime)."""

    name = "bedrock"

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
        *,
        config: dict | None = None,
        client=None,
    ):
        cfg = config or load_config()["bedrock"]
        self.model_id = model_id or cfg.get("model_id") or ""
        if not self.model_id:
            raise ProviderError(
                "unavailable",
                "no Bedrock model id configured (STEADYFRAME_BEDROCK_MODEL_ID or config/agent.yaml)",
            )
        self.region = region or cfg.get("region", "us-east-1")
        self.max_tokens = int(cfg.get("max_tokens", 1500))
        self.temperature = float(cfg.get("temperature", 0.0))
        self.max_retries = int(cfg.get("max_retries", 3))
        self.timeout_s = int(cfg.get("timeout_s", 60))
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    read_timeout=self.timeout_s, connect_timeout=10, retries={"max_attempts": 0}
                ),
            )
        self.client = client

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> ModelResponse:
        from botocore.exceptions import BotoCoreError, ClientError

        attempt = 0
        while True:
            t0 = time.perf_counter()
            try:
                resp = self.client.converse(
                    modelId=self.model_id,
                    system=[{"text": system}],
                    messages=messages,
                    toolConfig={"tools": [{"toolSpec": t} for t in tools]},
                    inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
                )
                break
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if (
                    code
                    in (
                        "ThrottlingException",
                        "ServiceUnavailableException",
                        "ModelNotReadyException",
                        "InternalServerException",
                    )
                    and attempt < self.max_retries
                ):
                    attempt += 1
                    time.sleep(min(20.0, (2**attempt) + random.random()))
                    continue
                kind = "throttled" if code == "ThrottlingException" else "unavailable"
                raise ProviderError(kind, f"{code}: {e}") from e
            except BotoCoreError as e:  # read timeouts, connection errors
                name = type(e).__name__
                if "Timeout" in name and attempt < self.max_retries:
                    attempt += 1
                    continue
                raise ProviderError(
                    "timeout" if "Timeout" in name else "other", f"{name}: {e}"
                ) from e
        latency = time.perf_counter() - t0
        out = resp.get("output", {}).get("message", {})
        text = ""
        calls: list[ToolCall] = []
        for block in out.get("content", []):
            if "text" in block:
                text += block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                inp = tu.get("input", {})
                if not isinstance(inp, dict):
                    raise ProviderError("malformed", f"tool input is not an object: {inp!r}")
                calls.append(ToolCall(tu.get("toolUseId", ""), tu.get("name", ""), inp))
        usage = resp.get("usage", {})
        return ModelResponse(
            text=text,
            tool_calls=calls,
            stop_reason=resp.get("stopReason", "end_turn"),
            input_tokens=int(usage.get("inputTokens", 0)),
            output_tokens=int(usage.get("outputTokens", 0)),
            latency_s=latency,
        )


# ---------------------------------------------------------------- fakes for tests and offline runs


class ScriptedProvider(Provider):
    """Returns pre-baked responses in order; an item may be a ModelResponse, an exception to
    raise, or a callable(system, messages, tools) -> ModelResponse."""

    name = "scripted"

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> ModelResponse:
        self.calls.append(messages)
        if not self.script:
            return ModelResponse(text="(script exhausted)", stop_reason="end_turn")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(system, messages, tools)
        return item


class HeuristicProvider(Provider):
    """A deterministic stand-in for the LLM that follows the same tool protocol.

    It reads the last tool result and decides exactly the way the system prompt asks a model
    to: use get_segment_detail's measurements and parameter hints, prefer regional fixes,
    escalate on a failed verify, ask for approval when required. It lets the whole agent loop
    (tool calls, trace, fallbacks, evaluation) run offline and gives an honest
    "measurement-driven parameter selection" baseline for eval/agent_vs_fixed.py. It is not a
    substitute for the live Bedrock run in the report.
    """

    name = "heuristic"

    def __init__(self):
        self.n = 0

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> ModelResponse:
        self.n += 1
        last = messages[-1]
        results = [c["toolResult"] for c in last.get("content", []) if "toolResult" in c]
        if not results:
            return self._call("analyze_video", {}, "Starting: analyze the video.")
        tr = results[-1]
        name = _tool_name_for(messages, tr["toolUseId"])
        payload = _json_of(tr)
        if tr.get("status") == "error":
            return ModelResponse(
                text=f"Tool error: {payload}. Finalizing what we have.",
                tool_calls=[self._tc("finalize", {})],
                stop_reason="tool_use",
            )
        if name == "analyze_video":
            open_segs = [s for s in payload.get("segments", []) if s.get("status") == "open"]
            if not open_segs:
                return self._call("finalize", {}, "No open segments.")
            self._open = sorted(open_segs, key=lambda s: s["start_s"])
            return self._call(
                "get_segment_detail",
                {"segment_id": self._open[0]["id"]},
                f"{len(self._open)} hazard segment(s). Inspecting the first.",
            )
        if name == "get_segment_detail":
            return self._plan_from_detail(payload)
        if name == "apply_remediation":
            return self._call(
                "verify_candidate",
                {"candidate_id": payload["candidate_id"]},
                "Candidate rendered; verifying with the analyzer.",
            )
        if name == "verify_candidate":
            self._last_verify = payload
            if payload["passes_for_type"]:
                if payload["requires_approval"]:
                    sid = payload["candidate_id"].rsplit("-c", 1)[0]
                    return self._call(
                        "request_human_approval",
                        {
                            "segment_id": sid,
                            "reason": payload["approval_reason"],
                            "options": [{"candidate_id": payload["candidate_id"]}],
                        },
                        "Passes but needs a human decision.",
                    )
                return self._call(
                    "accept_candidate",
                    {"candidate_id": payload["candidate_id"]},
                    "Verified: accepting.",
                )
            sid = payload["candidate_id"].rsplit("-c", 1)[0]
            return self._call(
                "get_segment_detail",
                {"segment_id": sid},
                f"Still failing ({payload['reason']}); re-reading the segment to escalate.",
            )
        if name == "request_human_approval":
            if payload.get("status") == "approved":
                cid = payload["decision"].get("candidate_id") or self._last_verify["candidate_id"]
                return self._call("accept_candidate", {"candidate_id": cid}, "Approved.")
            sid = self._last_verify["candidate_id"].rsplit("-c", 1)[0]
            return self._call(
                "get_segment_detail", {"segment_id": sid}, "Rejected; trying something else."
            )
        if name == "accept_candidate":
            sid = payload["segment_id"]
            self._open = [s for s in getattr(self, "_open", []) if s["id"] != sid]
            if self._open:
                return self._call(
                    "get_segment_detail", {"segment_id": self._open[0]["id"]}, "Next segment."
                )
            return self._call("finalize", {}, "All segments accepted.")
        if name == "finalize":
            if payload.get("ok"):
                return ModelResponse(text="Done.", stop_reason="end_turn")
            nxt = (payload.get("open_segments") or [None])[0]
            if nxt:
                return self._call("get_segment_detail", {"segment_id": nxt}, "Segments still open.")
            return ModelResponse(text="Nothing more to do.", stop_reason="end_turn")
        return ModelResponse(
            text="Unexpected state; finishing.",
            tool_calls=[self._tc("finalize", {})],
            stop_reason="tool_use",
        )

    def _plan_from_detail(self, d: dict) -> ModelResponse:
        sid = d["id"]
        typ = d["type"]
        hints = d.get("parameter_hints", {})
        tried = [a["strategy"] for a in d.get("attempts", [])]
        left = d.get("iterations_left_for_segment", 0)
        dec = (d.get("approval") or {}).get("decision") or {}
        if dec.get("approved") and dec.get("candidate_id"):
            for a in d.get("attempts", []):
                if a["candidate_id"] == dec["candidate_id"] and (a.get("verified") or {}).get(
                    "passes_for_type"
                ):
                    return self._call(
                        "accept_candidate",
                        {"candidate_id": dec["candidate_id"]},
                        "A human approved this candidate; accepting it.",
                    )
        if left <= 0:
            opts = [
                {
                    "candidate_id": a["candidate_id"],
                    "strategy": a["strategy"],
                    "params": a["params"],
                }
                for a in d.get("attempts", [])
            ]
            return self._call(
                "request_human_approval",
                {
                    "segment_id": sid,
                    "reason": "iteration budget exhausted without a passing candidate",
                    "options": opts,
                },
                "Out of attempts.",
            )
        regional = hints.get("prefer_regional", True)
        if typ == "red":
            ladder = [
                ("S3", {"strength": 0.8}),
                ("S4", {"base": "S3", "strength": 1.0}),
                ("S5", {}),
                ("S6", {}),
            ]
        elif typ == "pattern":
            ladder = [("S6", {})]
        else:
            s1 = {"alpha": hints.get("S1", {}).get("alpha", 0.1)}
            s2 = {
                "max_swing": hints.get("S2", {}).get("max_swing", 0.05),
                "mean_alpha": hints.get("S2", {}).get("mean_alpha", 0.02),
            }
            if regional:
                ladder = [
                    ("S1", s1),
                    ("S2", s2),
                    ("S4", {"base": "S1", **s1}),
                    ("S5", {}),
                    ("S6", {}),
                ]
            else:
                ladder = [
                    ("S4", {"base": "S1", **s1}),
                    ("S4", {"base": "S2", **s2}),
                    ("S5", {}),
                    ("S6", {}),
                ]
        # after a failed S1, retry S1 once with a much lower alpha before moving on
        if tried and tried[-1] == "S1" and tried.count("S1") == 1 and typ == "general":
            a = max(0.02, round(float(s1["alpha"]) * 0.5, 3))
            return self._call(
                "apply_remediation",
                {"segment_id": sid, "strategy": "S1", "params": {"alpha": a}},
                f"S1 at alpha {s1['alpha']} left a residual swing; halving alpha to {a}.",
            )
        seen = 0
        for strategy, params in ladder:
            if strategy in tried:
                seen += 1
                continue
            why = f"{typ} hazard at {d['peak_flash_rate_hz']} Hz, dL {d['max_delta_L']}, area {d['max_area_fraction']}; {'regional' if regional else 'global'} fix, {strategy} with params from the measurements."
            return self._call(
                "apply_remediation",
                {"segment_id": sid, "strategy": strategy, "params": params},
                why,
            )
        opts = [
            {"candidate_id": a["candidate_id"], "strategy": a["strategy"], "params": a["params"]}
            for a in d.get("attempts", [])
        ]
        return self._call(
            "request_human_approval",
            {"segment_id": sid, "reason": "every strategy tried", "options": opts},
            "Nothing left to try.",
        )

    def _tc(self, name: str, args: dict) -> ToolCall:
        return ToolCall(f"h{self.n}", name, args)

    def _call(self, name: str, args: dict, text: str) -> ModelResponse:
        return ModelResponse(text=text, tool_calls=[self._tc(name, args)], stop_reason="tool_use")


def _tool_name_for(messages: list[dict], tool_use_id: str) -> str:
    for m in reversed(messages):
        for c in m.get("content", []):
            if "toolUse" in c and c["toolUse"]["toolUseId"] == tool_use_id:
                return c["toolUse"]["name"]
    return ""


def _json_of(tool_result: dict) -> dict:
    for c in tool_result.get("content", []):
        if "json" in c:
            return c["json"]
        if "text" in c:
            return {"text": c["text"]}
    return {}


def make_provider(name: str | None, **kw) -> Provider | None:
    """'bedrock' | 'heuristic' | None (None means: use the fixed policy)."""
    if name in (None, "", "fixed"):
        return None
    if name == "heuristic":
        return HeuristicProvider()
    if name == "bedrock":
        return BedrockProvider(**kw)
    raise ValueError(f"unknown provider {name!r}")


ProviderFactory = Callable[[], Provider]
