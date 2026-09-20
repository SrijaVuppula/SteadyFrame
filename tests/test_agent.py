"""Agent loop tests with a scripted fake model. Every failure mode must degrade to the
fixed policy and leave a readable trace."""

import json

import pytest

from steadyframe.agent.loop import TOOL_SPECS, run_agent, system_prompt
from steadyframe.agent.providers import (
    HeuristicProvider,
    ModelResponse,
    ProviderError,
    ScriptedProvider,
    ToolCall,
)
from steadyframe.agent.tools import ApprovalPending, Job
from steadyframe.remediate.pipeline import fix_file

from .conftest import square_frames


def tc(name, **args):
    return ModelResponse(
        text=f"calling {name}",
        tool_calls=[ToolCall(f"id-{name}", name, args)],
        stop_reason="tool_use",
    )


@pytest.fixture
def strobe(tmp_clip):
    return tmp_clip(
        square_frames(120, 30, 6.0, size=(96, 72), region=(24, 18, 72, 54), start=1.0), codec="h264"
    )


def last_result(provider: ScriptedProvider, name: str):
    """Find the tool result the model was shown for a tool call named `name`."""
    for msgs in reversed(provider.calls):
        for m in reversed(msgs):
            for c in m.get("content", []):
                if "toolResult" in c:
                    return c["toolResult"]
    return None


def test_tool_specs_are_well_formed():
    names = [t["name"] for t in TOOL_SPECS]
    assert names == [
        "analyze_video",
        "get_segment_detail",
        "apply_remediation",
        "verify_candidate",
        "request_human_approval",
        "accept_candidate",
        "finalize",
    ]
    for t in TOOL_SPECS:
        assert t["inputSchema"]["json"]["type"] == "object"
    sp = system_prompt("wcag")
    assert "S1" in sp and "S6" in sp and "verify_candidate" in sp and "never see" in sp


def test_heuristic_agent_completes_and_uses_hints(strobe, tmp_path):
    rep = fix_file(strobe, tmp_path / "o.mp4", policy="heuristic", workdir=tmp_path / "wd")
    assert rep["status"] == "passed"
    assert rep["policy"] == "agent[heuristic]"
    seg = rep["segments"][0]
    assert (
        seg["strategy"] == "S1" and seg["params"]["alpha"] != 0.1
    )  # regional, parameter from the hint
    trace = [
        json.loads(line) for line in (tmp_path / "wd" / "trace.jsonl").read_text().splitlines()
    ]
    kinds = [(r["kind"], r["name"]) for r in trace]
    assert ("model", "turn") in kinds
    # perception -> decision -> action -> perception: verify result precedes the accept call
    names = [r["name"] for r in trace if r["kind"] == "tool_call"]
    assert names.index("verify_candidate") < names.index("accept_candidate")
    assert all(r.get("by") in ("model", "policy") for r in trace if r["kind"] == "tool_call")


def test_scripted_happy_path_with_dynamic_ids(strobe, tmp_path):
    # the script reads ids out of previous tool results, like a real model would
    def after_analyze(system, messages, tools):
        res = last_result(ScriptedProviderHolder.p, "analyze_video")
        sid = res["content"][0]["json"]["segments"][0]["id"]
        return tc("apply_remediation", segment_id=sid, strategy="S1", params={"alpha": 0.06})

    def after_apply(system, messages, tools):
        cid = last_result(ScriptedProviderHolder.p, "apply_remediation")["content"][0]["json"][
            "candidate_id"
        ]
        return tc("verify_candidate", candidate_id=cid)

    def after_verify(system, messages, tools):
        v = last_result(ScriptedProviderHolder.p, "verify_candidate")["content"][0]["json"]
        assert v["passes_for_type"] is True
        return tc("accept_candidate", candidate_id=v["candidate_id"])

    p = ScriptedProvider(
        [
            tc("analyze_video"),
            after_analyze,
            after_apply,
            after_verify,
            tc("finalize"),
            ModelResponse(text="done"),
        ]
    )
    ScriptedProviderHolder.p = p
    job = Job(strobe, tmp_path / "wd")
    label = run_agent(job, provider=p)
    assert label == "agent[scripted]"
    assert job.open_segments() == []
    assert job.state["llm"]["turns"] == 5  # the loop stops right after a successful finalize


class ScriptedProviderHolder:
    p = None


@pytest.mark.parametrize("kind", ["timeout", "throttled", "unavailable"])
def test_provider_failure_falls_back_to_fixed(strobe, tmp_path, kind):
    p = ScriptedProvider([tc("analyze_video"), ProviderError(kind, "simulated")])
    job = Job(strobe, tmp_path / "wd")
    label = run_agent(job, provider=p)
    assert label == "agent[scripted]+fixed-fallback"
    assert job.open_segments() == []
    assert job.state["llm"]["fallback"] == f"model {kind}"
    calls = [r for r in job.trace.records if r["kind"] == "tool_call"]
    assert any(r["by"] == "fixed-fallback" for r in calls)
    assert any(r["kind"] == "decision" and r["name"] == "fallback" for r in job.trace.records)


def test_malformed_tool_calls_are_reported_then_fallback(strobe, tmp_path):
    p = ScriptedProvider(
        [
            tc("analyze_video"),
            tc("apply_remediation", segment_id="nope", strategy="S1"),  # unknown segment
            tc("no_such_tool"),
            tc("verify_candidate"),  # missing argument
            tc("finalize"),  # never reached: 3 consecutive errors trigger the fallback
        ]
    )
    job = Job(strobe, tmp_path / "wd")
    label = run_agent(job, provider=p)
    assert label.endswith("+fixed-fallback")
    # the model saw an error tool result for each bad call
    errs = [
        c["toolResult"]
        for m in p.calls[-1]
        for c in m.get("content", [])
        if "toolResult" in c and c["toolResult"].get("status") == "error"
    ]
    assert len(errs) >= 2
    assert job.state["llm"]["fallback"] == "3 consecutive tool errors"
    assert job.open_segments() == []


def test_tool_exception_is_returned_to_model(strobe, tmp_path, monkeypatch):
    from steadyframe.agent import tools as t

    def boom(*a, **k):
        raise RuntimeError("renderer crashed")

    monkeypatch.setattr(t, "render", boom)
    p = ScriptedProvider(
        [
            tc("analyze_video"),
            lambda s, m, tl: tc(
                "apply_remediation",
                segment_id=last_result(p, "x")["content"][0]["json"]["segments"][0]["id"],
                strategy="S1",
            ),
            ModelResponse(text="giving up"),
        ]
    )
    job = Job(strobe, tmp_path / "wd")
    # the model gives up, the fixed fallback cannot render either, so the job ends up asking a human
    with pytest.raises(ApprovalPending):
        run_agent(job, provider=p)
    err = [c["toolResult"] for m in p.calls[-1] for c in m.get("content", []) if "toolResult" in c][
        -1
    ]
    assert err["status"] == "error" and "renderer crashed" in err["content"][0]["text"]
    assert job.state["llm"]["errors"][0]["kind"] == "tool_error"


def test_budget_exhaustion_reaches_human_approval(strobe, tmp_path):
    # a model that keeps trying a hopeless S1 alpha runs into the per-segment budget and the
    # heuristic then asks for approval; with approve_all the job still completes
    p = HeuristicProvider()
    job = Job(
        strobe,
        tmp_path / "wd",
        max_iterations_per_segment=1,
        approve_all=True,
        approval_min_ssim=1.01,
    )
    run_agent(job, provider=p)
    names = [r["name"] for r in job.trace.records if r["kind"] == "tool_call"]
    assert "request_human_approval" in names
    assert job.open_segments() == []


def test_turn_budget_exhausted_falls_back(strobe, tmp_path):
    p = ScriptedProvider(
        [tc("analyze_video")] + [ModelResponse(text="thinking...", stop_reason="end_turn")] * 5
    )
    job = Job(strobe, tmp_path / "wd")
    label = run_agent(
        job, provider=p, config={"loop": {"max_turns": 3, "max_consecutive_errors": 3}}
    )
    assert label.endswith("+fixed-fallback")
    assert job.state["llm"]["fallback"] in (
        "turn budget (3) exhausted",
        "model stopped with open segments",
    )


def test_approval_pending_propagates_through_agent(strobe, tmp_path):
    rep = fix_file(
        strobe,
        tmp_path / "o.mp4",
        policy="heuristic",
        workdir=tmp_path / "wd",
        approval_min_ssim=1.01,
    )
    assert rep["status"] == "needs_approval" and rep["pending_approvals"]
    sid = rep["pending_approvals"][0]["segment_id"]
    cid = rep["pending_approvals"][0]["options"][0]["candidate_id"]
    rep2 = fix_file(
        strobe,
        tmp_path / "o.mp4",
        policy="heuristic",
        workdir=tmp_path / "wd",
        approval_min_ssim=1.01,
        decisions={sid: {"approved": True, "candidate_id": cid}},
    )
    assert rep2["status"] == "passed"


def test_no_model_configured_falls_back(strobe, tmp_path, monkeypatch):
    monkeypatch.delenv("STEADYFRAME_BEDROCK_MODEL_ID", raising=False)
    job = Job(strobe, tmp_path / "wd")
    label = run_agent(job, provider=None, config={"bedrock": {"model_id": ""}, "loop": {}})
    assert label == "fixed (no model available)"
    assert job.open_segments() == []


def test_bedrock_provider_parses_converse_response():
    from steadyframe.agent.providers import BedrockProvider

    class FakeClient:
        def converse(self, **kw):
            assert (
                kw["modelId"] == "test-model"
                and kw["toolConfig"]["tools"][0]["toolSpec"]["name"] == "analyze_video"
            )
            return {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"text": "ok"},
                            {"toolUse": {"toolUseId": "t1", "name": "analyze_video", "input": {}}},
                        ],
                    }
                },
                "stopReason": "tool_use",
                "usage": {"inputTokens": 12, "outputTokens": 5},
            }

    prov = BedrockProvider(
        model_id="test-model", region="us-east-1", client=FakeClient(), config={"model_id": "x"}
    )
    r = prov.converse("sys", [{"role": "user", "content": [{"text": "hi"}]}], TOOL_SPECS)
    assert (
        r.tool_calls[0].name == "analyze_video"
        and r.input_tokens == 12
        and r.stop_reason == "tool_use"
    )


def test_bedrock_provider_maps_throttling(monkeypatch):
    from botocore.exceptions import ClientError

    from steadyframe.agent.providers import BedrockProvider

    class Throttle:
        def converse(self, **kw):
            raise ClientError(
                {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"
            )

    monkeypatch.setattr("time.sleep", lambda s: None)
    prov = BedrockProvider(model_id="m", client=Throttle(), config={"max_retries": 1})
    with pytest.raises(ProviderError) as e:
        prov.converse("s", [], TOOL_SPECS)
    assert e.value.kind == "throttled"
