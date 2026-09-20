# The agent

Perception, decision, action, perception again. The model never sees a pixel: everything
it reasons over is a number the OpenCV 5 analyzer produced, and every decision is written
to `trace.jsonl` (and to DynamoDB in the service).

![agent workflow](diagrams/agent_workflow.svg)

Source: `docs/diagrams/agent_workflow.mmd`.

## Tools (`steadyframe/agent/tools.py`, schemas in `agent/loop.py`)

| Tool | Returns | OpenCV 5 work behind it |
|---|---|---|
| `analyze_video()` | verdict, video metadata, hazard segments (type, times, peak flash rate, area fraction, luminance swing, regions, severity), strategy catalogue | LUT + transform luminance, INTER_AREA grid, transition tracker, boxFilter area, connectedComponentsWithStats regions |
| `get_segment_detail(segment_id)` | measurements, region luminance series, applicable strategies, **parameter hints**, attempts so far, remaining budget, any human decision | region series from the grid history |
| `apply_remediation(segment_id, strategy, params)` | candidate id, quality metrics (SSIM in/out of the regions, dL) | accumulateWeighted / linear-light gain / red desaturation / frame hold / card, GaussianBlur masks, GaussianBlur-based SSIM |
| `verify_candidate(candidate_id)` | passes_for_type, remaining hazards, quality, requires_approval + reason | the analyzer again, on the candidate clip |
| `request_human_approval(segment_id, reason, options)` | approved / rejected, or the job pauses | - |
| `accept_candidate(candidate_id)` | ok | - |
| `finalize()` | ok, or the list of segments still open | full render + whole-file re-verification happen in the pipeline afterwards |

Parameter hints are physics, not magic: S1 is an exponential moving average, and a square
wave with half-period N frames keeps `(1 - r^N) / (1 + r^N)` of its swing (`r = 1 - alpha`).
From the measured swing and rate we solve for the alpha that lands 10% under the WCAG
transition threshold. The fixed policy ignores hints (defaults only); the agent may use them.

## Constraints (`config/agent.yaml`)

- 4 iterations per segment, 24 per job (`BudgetExhausted` is a tool error the model sees).
- 40 model turns; 3 consecutive tool errors; any `ProviderError` (timeout, throttling,
  malformed tool call, model unavailable) -> the remaining open segments go to the fixed
  policy, the trace gets a `fallback` decision and the report's `policy` says
  `agent[bedrock]+fixed-fallback`.
- S6 and any fix with overall SSIM under 0.75 need `request_human_approval`. The job pauses
  (`needs_approval`), `job.json` + candidates persist, and it resumes with the decision.
- `--policy fixed` (`--no-llm`) runs without any model. `--policy heuristic` runs the same
  loop with a deterministic stand-in that follows the tool protocol (for CI and offline
  evaluation; see `eval/results/agent_vs_fixed.md` for what it does and does not show).

## Providers

`steadyframe/agent/providers.py`: `BedrockProvider` (Converse API + toolConfig, retries with
backoff on throttling), `ScriptedProvider` (tests), `HeuristicProvider` (offline stand-in).
Model IDs come from `STEADYFRAME_BEDROCK_MODEL_ID` or `config/agent.yaml`, never code.

## Running live

    export AWS_PROFILE=...  AWS_REGION=us-east-1
    export STEADYFRAME_BEDROCK_MODEL_ID=<inference profile id from the console>
    for c in m_two_segments r_red_strobe_region v_720p_16x9 w_sine_6hz a_sweep_11x11cells; do
      steadyframe fix data/synthetic/$c.mp4 --policy agent -o /tmp/$c.safe.mp4 \
        --report eval/results/frozen/agent_live/$c.report.json --workdir /tmp/wd_$c
      cp /tmp/wd_$c/trace.jsonl eval/results/frozen/agent_live/$c.trace.jsonl
    done
    python -m eval.agent_vs_fixed --provider bedrock

## Example traces

`docs/examples/` holds two annotated traces from the heuristic provider where a verify
result visibly changes the next call. Replace or add the live Bedrock traces after the
run above.
