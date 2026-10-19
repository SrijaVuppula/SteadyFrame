# SteadyFrame over MCP: bring your own agent

`steadyframe mcp` serves SteadyFrame's tools over the [Model Context Protocol](https://modelcontextprotocol.io),
so any MCP client can check a video for flashing, repair it and prove the repair: an agentic IDE
such as Kiro, Codex or VS Code, or your own agent. The built-in planner on AWS and an outside
agent use the same tools, and both are held to the same rules, because the rules are in the tools
(`steadyframe/agent/tools.py`), not in a prompt.

```bash
make install
make mcp-demo        # an MCP client drives the server over stdio on two sample clips
```

## Connect a client

The server speaks stdio by default (the client starts it) and streamable HTTP with `--http PORT`
(bound to 127.0.0.1). Use the absolute path of the `steadyframe` command in this checkout's
virtual environment.

Kiro, in `.kiro/settings/mcp.json` (workspace) or `~/.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "steadyframe": { "command": "/path/to/SteadyFrame/.venv/bin/steadyframe", "args": ["mcp"] }
  }
}
```

Codex, in `~/.codex/config.toml`:

```toml
[mcp_servers.steadyframe]
command = "/path/to/SteadyFrame/.venv/bin/steadyframe"
args = ["mcp"]
```

VS Code, in `.vscode/mcp.json`:

```json
{
  "servers": {
    "steadyframe": { "type": "stdio", "command": "/path/to/SteadyFrame/.venv/bin/steadyframe", "args": ["mcp"] }
  }
}
```

Then ask the agent, for example: *"Check ~/Videos/intro.mp4 for flashing with SteadyFrame and
fix it."* The server's instructions and the `repair_video` prompt give the agent the same rules
the built-in planner gets.

## What the server offers

| Tool | What it does |
|---|---|
| `analyze_video(path, profile)` | runs the OpenCV 5 analyzer (WCAG 2.3.1 or ITU-R BT.1702 / Ofcom); returns a `job_id`, the verdict, every hazard segment with its measurements, and the strategy catalogue |
| `get_segment_detail(job_id, segment_id)` | the segment's measurements, its luminance over time, parameter hints from the measured rate and swing, attempts left |
| `apply_remediation(job_id, segment_id, strategy, params)` | renders a candidate fix (S1 to S6) for that region and time; returns quality metrics; costs one of four attempts |
| `verify_candidate(job_id, candidate_id)` | re-runs the analyzer on the candidate: does the hazard pass now, and does the fix need a person's approval |
| `request_human_approval(job_id, segment_id, candidate_id, reason)` | asks the person at the client, through MCP elicitation |
| `accept_candidate(job_id, candidate_id)` | accepts a verified, passing (and, where needed, approved) candidate |
| `finalize(job_id, output_path)` | renders the whole file, re-verifies it, writes the repaired video, the verification record (JSON and HTML) and a WebVTT warning track |
| `verify_record(video_path, record_path)` | re-hashes a file and re-runs the analyzer against its record |
| `run_on_aws(path, policy, profile)` | sends the whole file to the deployed pipeline (AWS Lambda worker, fixed policy or the Bedrock planner) and returns the result and the job page |

The resource `steadyframe://jobs/{job_id}/trace` is the job's trace: every tool call, result and
decision, with the outside agent's calls marked `"by": "mcp"`.

## What an outside agent cannot do

The same refusals as for the built-in planner, tested in `tests/test_mcp.py` through a real MCP
client session:

- `accept_candidate` refuses a candidate that was not verified, did not pass, or needs approval
  that was not given.
- `finalize` refuses while any segment is still open; the job's status comes from re-analysing
  the rendered file, not from anything the agent says.
- Each segment has four attempts and each job 24; the tools count them.
- The agent is shown the analyzer's measurements, never pixels or the file's metadata tags.
- **A human decision cannot come from the agent.** `request_human_approval` sends the question to
  the person through the client (MCP elicitation) and records their answer in the trace as
  `person (MCP elicitation)`. If the person declines, the candidate stays out; if the client
  cannot ask a person, the segment stays waiting and `finalize` reports `needs_approval`. The
  trust boundary is the client: a client that answers elicitation by itself is answering for
  its user.

The server reads and writes files on the machine it runs on, with the permissions of the user who
started it; it is meant to run next to your own agent, not as a shared service. `run_on_aws`
uploads the file to the public demo pipeline, which deletes uploads after a day and applies the
demo's daily limits.

## A run, verbatim

`python -m eval.mcp_walkthrough demo/mcp/sample_red_fullscreen.mp4 --yes`: a scripted MCP client
(no model, so the run is reproducible) starts `steadyframe mcp` over stdio and makes the calls an
agent would. The full-screen red strobe has no gentle fix for its red flashing, so the server asks
the person.

```text
connected to steadyframe over stdio: 9 tools
  analyze_video, get_segment_detail, apply_remediation, verify_candidate, request_human_approval, accept_candidate, finalize, verify_record, run_on_aws

  analyze_video            verdict fail, 2 segment(s)
                           g000: general 0.50-4.80 s, 5.0 flashes/s
                           r001: red 0.50-4.80 s, 5.0 flashes/s
  finalize (too early)     segments still open: g000, r001
  apply_remediation        g000-c1 S1 {'alpha': 0.272} SSIM inside 0.81
  verify_candidate         passes=True approval=False
  accept_candidate         ok
  apply_remediation        r001-c1 S3  SSIM inside 0.71
  verify_candidate         passes=True approval=True

  ? SteadyFrame needs your decision on red flashing in sample_red_fullscreen.mp4, 0.50-4.80 s. The only fix that passes is S3 (red desaturation), which keeps SSIM 0.705 of the picture (auto-accept needs 0.75). The agent says: the only passing fix changes the picture a lot
  > approve (--yes)

  request_human_approval   approved
  accept_candidate         ok
  finalize                 passed: whole file re-verified as pass
  verify_record            record holds

  output  demo/mcp/sample_red_fullscreen.safe.mp4
  record  demo/mcp/sample_red_fullscreen.safe.record.html
  trace   demo/mcp/jobs/e737a1294708/trace.jsonl
```

`run_on_aws` on the Flashing box sample, from the same server: uploaded, repaired by the AWS Lambda
worker with the fixed policy and re-verified, `before: fail`, `after: pass`, 6.5 s (2026-10-19).
