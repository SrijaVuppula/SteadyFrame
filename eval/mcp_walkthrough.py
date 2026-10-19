"""Drive `steadyframe mcp` over stdio the way an MCP client does, and print every step.

    python -m eval.mcp_walkthrough clip.mp4 [-o safe.mp4] [--profile broadcast] [--yes]

It starts the server as a subprocess (the same command an agent's MCP config runs), lists the
tools, and walks one clip through the loop: analyze, read each segment, render a candidate with
the analyzer's own parameter hint, verify it, ask the person when the fix needs approval (the
question appears here, as it would in an agent's client; --yes answers it), accept, finalize,
and re-check the verification record. The steps are scripted so the run is reproducible; an
agent makes the same calls and gets the same refusals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


def _say(step: str, detail: str = "") -> None:
    print(f"  {step:<24} {detail}", flush=True)


async def walk(clip: Path, out: Path | None, profile: str, yes: bool, workdir: str | None) -> dict:
    async def elicit(context, params: types.ElicitRequestParams):
        print(f"\n  ? {params.message}")
        if yes:
            print("  > approve (--yes)\n")
            return types.ElicitResult(action="accept", content={"approve": True})
        answer = input("  approve? [y/N] ").strip().lower()
        return types.ElicitResult(action="accept", content={"approve": answer == "y"})

    args = ["-m", "steadyframe.cli", "mcp"] + (["--workdir", workdir] if workdir else [])
    server = StdioServerParameters(command=sys.executable, args=args)
    async with (
        stdio_client(server) as (r, w),
        ClientSession(r, w, elicitation_callback=elicit) as s,
    ):
        init = await s.initialize()
        tools = [t.name for t in (await s.list_tools()).tools]
        print(f"connected to {init.serverInfo.name} over stdio: {len(tools)} tools")
        print(f"  {', '.join(tools)}\n")

        async def call(name: str, **kw) -> dict:
            res = await s.call_tool(name, kw)
            text = res.content[0].text if res.content else "{}"
            if res.isError:
                return {"refused": text.removeprefix(f"Error executing tool {name}: ")}
            return json.loads(text)

        a = await call("analyze_video", path=str(clip), profile=profile)
        job = a["job_id"]
        _say("analyze_video", f"verdict {a['verdict']}, {len(a['segments'])} segment(s)")
        for seg in a["segments"]:
            sid = seg["id"]
            _say(
                "",
                f"{sid}: {seg['type']} {seg['start_s']:.2f}-{seg['end_s']:.2f} s, "
                f"{seg['peak_flash_rate_hz']} flashes/s",
            )
        early = await call("finalize", job_id=job)
        _say("finalize (too early)", early.get("refused", "accepted?!"))

        for seg in a["segments"]:
            sid = seg["id"]
            d = await call("get_segment_detail", job_id=job, segment_id=sid)
            strategy = "S3" if seg["type"] == "red" else "S1"
            params = {"alpha": d["parameter_hints"]["S1"]["alpha"]} if strategy == "S1" else {}
            c = await call(
                "apply_remediation", job_id=job, segment_id=sid, strategy=strategy, params=params
            )
            cid = c["candidate_id"]
            ssim = c["quality"].get("ssim_inside")
            _say("apply_remediation", f"{cid} {strategy} {params or ''} SSIM inside {ssim:.2f}")
            v = await call("verify_candidate", job_id=job, candidate_id=cid)
            _say(
                "verify_candidate",
                f"passes={v['passes_for_type']} approval={v['requires_approval']}",
            )
            if not v["passes_for_type"]:
                _say("", "still failing; an agent would change the parameters or the strategy")
                continue
            if v["requires_approval"]:
                q = await call(
                    "request_human_approval",
                    job_id=job,
                    segment_id=sid,
                    candidate_id=cid,
                    reason="the only passing fix changes the picture a lot",
                )
                _say("request_human_approval", q.get("status", q.get("refused", "")))
            acc = await call("accept_candidate", job_id=job, candidate_id=cid)
            _say("accept_candidate", "ok" if acc.get("ok") else acc.get("refused", ""))

        f = await call("finalize", job_id=job, **({"output_path": str(out)} if out else {}))
        if "refused" in f:
            _say("finalize", f["refused"])
            return f
        _say("finalize", f"{f['status']}: whole file re-verified as {f['after_verdict']}")
        rec = await call("verify_record", video_path=f["output"], record_path=f["record"])
        _say("verify_record", "record holds" if rec.get("ok") else "record does NOT hold")
        print(f"\n  output  {f['output']}\n  record  {f['record_html']}\n  trace   {f['trace']}")
        return {**f, "record_ok": rec.get("ok")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("clip", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--profile", default="wcag", choices=["wcag", "broadcast"])
    ap.add_argument("--yes", action="store_true", help="approve when the server asks")
    ap.add_argument("--workdir", help="the server's job directory")
    a = ap.parse_args(argv)
    res = anyio.run(walk, a.clip, a.output, a.profile, a.yes, a.workdir)
    return 0 if res.get("status") in ("passed", "no_hazards") else 1


if __name__ == "__main__":
    sys.exit(main())
