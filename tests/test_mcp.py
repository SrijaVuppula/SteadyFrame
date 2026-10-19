"""The MCP server end to end, through a real MCP client session (in memory, no subprocess).

The external agent gets the same tools and the same guardrails as the built-in planner, and a
human decision can only come from the person at the client (elicitation)."""

from __future__ import annotations

import json

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import types  # noqa: E402
from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from steadyframe import mcp_server  # noqa: E402

from .conftest import square_frames  # noqa: E402

TOOLS = {
    "analyze_video",
    "get_segment_detail",
    "apply_remediation",
    "verify_candidate",
    "request_human_approval",
    "accept_candidate",
    "finalize",
    "verify_record",
    "run_on_aws",
}


def _session(answer=None):
    async def elicit(context, params):
        return answer(params) if answer else types.ErrorData(code=-1, message="no")

    return create_connected_server_and_client_session(
        mcp_server.mcp, elicitation_callback=elicit if answer else None
    )


async def _call(s, name, **args):
    r = await s.call_tool(name, args)
    text = r.content[0].text if r.content else ""
    if r.isError:
        return {"error": text}
    return json.loads(text)


@pytest.fixture
def clip(tmp_clip, tmp_path, monkeypatch):
    monkeypatch.setenv("STEADYFRAME_MCP_DIR", str(tmp_path / "mcp"))
    return tmp_clip(square_frames(90, 30, 6.0, start=0.5, region=(16, 12, 48, 36)))


def test_tools_prompt_and_resource_are_listed():
    async def run():
        async with _session() as s:
            tools = {t.name for t in (await s.list_tools()).tools}
            prompts = {p.name for p in (await s.list_prompts()).prompts}
            templates = (await s.list_resource_templates()).resourceTemplates
            return tools, prompts, [t.uriTemplate for t in templates]

    tools, prompts, templates = anyio.run(run)
    assert tools == TOOLS
    assert prompts == {"repair_video"}
    assert templates == ["steadyframe://jobs/{job_id}/trace"]


def test_an_external_agent_repairs_and_proves_it(clip):
    async def run():
        async with _session() as s:
            a = await _call(s, "analyze_video", path=str(clip))
            assert a["verdict"] == "fail" and a["segments"], a
            job, seg = a["job_id"], a["segments"][0]["id"]
            # guardrails hold for an outside agent exactly as for the built-in one
            assert "error" in await _call(s, "finalize", job_id=job)
            d = await _call(s, "get_segment_detail", job_id=job, segment_id=seg)
            assert d["parameter_hints"]
            alpha = d["parameter_hints"]["S1"]["alpha"]
            c = await _call(
                s,
                "apply_remediation",
                job_id=job,
                segment_id=seg,
                strategy="S1",
                params={"alpha": alpha},
            )
            cid = c["candidate_id"]
            assert "error" in await _call(s, "accept_candidate", job_id=job, candidate_id=cid)
            v = await _call(s, "verify_candidate", job_id=job, candidate_id=cid)
            assert v["passes_for_type"] and not v["requires_approval"], v
            assert (await _call(s, "accept_candidate", job_id=job, candidate_id=cid))["ok"]
            out = clip.with_name("out.safe.mp4")
            f = await _call(s, "finalize", job_id=job, output_path=str(out))
            assert f["status"] == "passed" and f["after_verdict"] == "pass", f
            r = await _call(s, "verify_record", video_path=str(out), record_path=f["record"])
            assert r["ok"], r
            trace = await s.read_resource(f"steadyframe://jobs/{job}/trace")
            return f, trace.contents[0].text

    f, trace = anyio.run(run)
    rows = [json.loads(line) for line in trace.splitlines()]
    assert {r.get("by") for r in rows if r.get("kind") == "tool_call"} == {"mcp"}
    assert any(r.get("name") == "accept" for r in rows)


def _needs_approval(s, clip):
    async def go():
        a = await _call(s, "analyze_video", path=str(clip))
        job, seg = a["job_id"], a["segments"][0]["id"]
        d = await _call(s, "get_segment_detail", job_id=job, segment_id=seg)
        c = await _call(
            s,
            "apply_remediation",
            job_id=job,
            segment_id=seg,
            strategy="S1",
            params={"alpha": d["parameter_hints"]["S1"]["alpha"]},
        )
        v = await _call(s, "verify_candidate", job_id=job, candidate_id=c["candidate_id"])
        assert v["requires_approval"], v
        return job, seg, c["candidate_id"]

    return go()


def test_approval_comes_from_the_person_at_the_client(clip, monkeypatch):
    monkeypatch.setenv("STEADYFRAME_APPROVAL_MIN_SSIM", "1.01")  # every candidate needs a person
    asked = []

    def person(params):
        asked.append(params.message)
        return types.ElicitResult(action="accept", content={"approve": True})

    async def run():
        async with _session(person) as s:
            job, seg, cid = await _needs_approval(s, clip)
            # without a decision the candidate cannot be accepted
            assert "error" in await _call(s, "accept_candidate", job_id=job, candidate_id=cid)
            r = await _call(
                s,
                "request_human_approval",
                job_id=job,
                segment_id=seg,
                candidate_id=cid,
                reason="only passing fix",
            )
            assert r["status"] == "approved", r
            assert (await _call(s, "accept_candidate", job_id=job, candidate_id=cid))["ok"]
            return await _call(s, "finalize", job_id=job)

    f = anyio.run(run)
    assert f["status"] == "passed"
    assert len(asked) == 1 and "SSIM" in asked[0] and "auto-accept needs 0.75" in asked[0]


def test_a_refusal_or_a_client_that_cannot_ask_keeps_the_fix_out(clip, monkeypatch):
    monkeypatch.setenv("STEADYFRAME_APPROVAL_MIN_SSIM", "1.01")

    async def refused():
        no = lambda p: types.ElicitResult(action="accept", content={"approve": False})  # noqa: E731
        async with _session(no) as s:
            job, seg, cid = await _needs_approval(s, clip)
            r = await _call(
                s,
                "request_human_approval",
                job_id=job,
                segment_id=seg,
                candidate_id=cid,
                reason="x",
            )
            return r, await _call(s, "accept_candidate", job_id=job, candidate_id=cid)

    async def cannot_ask():
        async with _session() as s:
            job, seg, cid = await _needs_approval(s, clip)
            r = await _call(
                s,
                "request_human_approval",
                job_id=job,
                segment_id=seg,
                candidate_id=cid,
                reason="x",
            )
            return r, await _call(s, "accept_candidate", job_id=job, candidate_id=cid)

    r, acc = anyio.run(refused)
    assert r["status"] == "rejected" and "error" in acc
    r, acc = anyio.run(cannot_ask)
    assert r["status"] == "pending_approval" and "error" in acc


def test_stdio_walkthrough_runs_the_real_server(clip, tmp_path, capsys):
    """`steadyframe mcp` as a subprocess over stdio, as an agent's MCP config starts it."""
    from eval import mcp_walkthrough

    out = tmp_path / "safe.mp4"
    rc = mcp_walkthrough.main([str(clip), "-o", str(out), "--workdir", str(tmp_path / "jobs")])
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "connected to steadyframe over stdio: 9 tools" in text
    assert "segments still open" in text and "record holds" in text
    assert out.exists() and out.with_name("safe.record.json").exists()
