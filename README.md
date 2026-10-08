# SteadyFrame

Finds flashing hazards in video, fixes them with the least invasive change, and verifies
its own fix. Checks content against published photosensitivity thresholds (WCAG 2.2
SC 2.3.1; ITU-R BT.1702 / Ofcom guidance as a second profile), localises every hazard in
time and space, and runs a closed loop: choose a fix, apply, re-analyse, escalate or ask a
human, re-verify the whole file.

Built for the OpenCV AI Competition 2026 (powered by AWS) on **OpenCV 5**
(`opencv-python-headless 5.0.0.93`), Python 3.11 and AWS (Lambda, S3, SQS, ECS Fargate on
Graviton, DynamoDB, Bedrock, CDK). Solo entry.

**Not a medical device.** A pass is not a certification; see `docs/RESPONSIBLE_USE.md`.

![architecture](docs/diagrams/architecture.svg)

## Quickstart

```bash
make install            # venv + pinned deps (requirements.lock) + editable install
make test               # 100+ tests, OpenCV 5 asserted at import
make synth              # deterministic hazardous test suite -> data/synthetic (gitignored, never play it)
make real               # openly licensed external clips listed in data/SOURCES.md -> data/real

steadyframe analyze data/synthetic/m_two_segments.mp4 --json out.json --plot out.png
steadyframe fix data/synthetic/m_two_segments.mp4 --policy fixed -o safe.mp4 --report report.json
steadyframe fix in.mp4 --policy agent -o safe.mp4      # Bedrock; needs STEADYFRAME_BEDROCK_MODEL_ID
steadyframe fix in.mp4 --policy heuristic -o safe.mp4  # same loop, deterministic stand-in, offline
```

`analyze` prints the verdict and every segment (type, time range, flash rate, area,
luminance swing, region, severity) and exits 2 on `fail`. `fix` writes the remediated
video, a `report.json` and a `trace.jsonl` of every decision.

Web endpoint, local: `docker compose up` then http://localhost:8080. AWS: `make deploy`
(see `infra/README.md`), then `make smoke`. Deployed endpoint: https://d25yofo4x3sac8.cloudfront.net

## How it works

1. **Analyze** (`steadyframe/analyzer.py`): per frame, `cv2.LUT` sRGB-to-linear, `INTER_AREA`
   resize to a 64x48 grid, `cv2.transform` for relative luminance, a vectorised per-cell
   transition tracker (accumulated change between local extrema, 0.10 threshold, darker
   state below 0.80), trailing one-second windows by timestamp, the 25%-of-any-10-degree
   window area rule with `cv2.boxFilter`, regions from `cv2.connectedComponentsWithStats`.
2. **Remediate** (`steadyframe/remediate/`): S1 regional temporal low-pass
   (`cv2.accumulateWeighted` in linear light), S2 luminance-swing compression, S3 red
   desaturation, S4 the same globally, S5 frame hold, S6 warning card. Quality: SSIM
   (`cv2.GaussianBlur`), PSNR, luminance change, temporal smoothness. Audio is remuxed.
3. **Loop** (`steadyframe/agent/`): a model on Amazon Bedrock (Converse API tool use) or a
   deterministic policy calls `analyze_video`, `get_segment_detail`, `apply_remediation`,
   `verify_candidate`, `request_human_approval`, `accept_candidate`, `finalize`. The model
   never sees pixels. Every failure mode degrades to the fixed policy; every call goes to
   the trace. Details: `docs/AGENT.md`, diagram: `docs/diagrams/agent_workflow.svg`.

## Results (reproduced by `make eval`; external clips need `make real` first)

| | |
|---|---|
| Detection: clip verdicts, boundary cases, per-second F1 | 44/44, 17/17, 1.000 |
| Robustness: H.264 CRF 28/35 variants keeping their verdict | 16/16 |
| Remediation (fixed policy): whole-file re-verification pass rate | 25/25, 1.1 iterations per segment |
| Agent (heuristic stand-in) vs fixed | same pass rate, 1.0 iterations per segment, higher SSIM inside regions |
| Agent (live Bedrock model) vs fixed | 25/25, 1.04 iterations per segment, SSIM inside regions 0.882 vs 0.861, 3.04 USD for the suite |
| External clips: EA IRIS test videos, Apple's flashing sample, 9 min of camera footage | 18/18 verdicts, IRIS's own verdict on 8/8, 0/551 control seconds flagged, 3/3 hazards fixed |
| Analyzer throughput, 720p, 4-vCPU x86, stock wheel | ~600 fps analysis-only, ~400 fps with decode |

Full tables: `eval/results/frozen/*.md`; failure gallery: `eval/results/frozen/failures.md`;
technical report: `docs/report/REPORT.md`; benchmark protocol (x86 / Graviton / COOL, one
command per EC2 configuration with `python -m bench.ec2`) and results: `bench/README.md`,
`bench/results/comparison.md`.

## Repository

```
steadyframe/   analyzer, profiles, remediation strategies, agent loop, CLI
synth/         synthetic clip generator + independent 1-D reference for ground truth
eval/          detection, robustness, remediation, agent_vs_fixed, external, failures, report renderer
bench/         x86 / Graviton / COOL benchmark harness
service/       Lambda handlers, worker, local FastAPI, smoke test     infra/  CDK (Python)
web/           React UI (flash-safe, WCAG AA, axe check in CI)
docs/          STANDARDS, NOTES, PRIOR_ART, AGENT, API, RESPONSIBLE_USE, report, diagrams
```

Standards text and every
implementation decision: `docs/STANDARDS.md`, `docs/NOTES.md`.

## Licence

Apache-2.0. Synthetic test clips are generated locally and never distributed.
