# For judges: where each criterion's evidence is

**Fastest path (nothing to install):** https://d25yofo4x3sac8.cloudfront.net/judge. Press
**Run live check** and a real job runs on AWS while you watch (5 to 40 s); below it are recorded
examples (a live-model run that changes its plan, a job paused for a person), the verification
record, the measured results and the adversarial test.

**One sentence:** the model picks the fix; the analyzer decides whether it worked; a person
signs off on anything drastic.

Every number below is filled in from `eval/results/frozen/*.json` by `python -m eval.report`
(this file is rendered from `docs/JUDGES.template.md`).

## Overall rubric

| Criterion (weight) | What to look at | Evidence |
|---|---|---|
| **Technical execution (30%)** — correctness and depth of the OpenCV 5 implementation, architecture, reliability, evaluation | `steadyframe/analyzer.py` (grid-first luminance: `cv2.LUT` → `cv2.resize` INTER_AREA → `cv2.transform`; `cv2.boxFilter` area rule; `cv2.connectedComponentsWithStats` regions), `steadyframe/remediate/` (`cv2.accumulateWeighted` in linear light, SSIM on `cv2.GaussianBlur`), `docs/report/REPORT.md` | {{detection.n_clips}} synthetic clips with independent ground truth: per-second F1 {{detection.per_second.f1:.3f}}, {{detection.boundary_correct}}/{{detection.boundary_total}} boundary cases, {{robustness_summary.crf_correct}}/{{robustness_summary.crf_total}} H.264 re-encodes keep their verdict. Third-party clips: {{external.by_profile.wcag.clip_agreement}}/{{external.n_clips}} verdicts, EA IRIS's own verdict on {{external.by_profile.broadcast.iris_agreement}}/{{external.by_profile.broadcast.iris_clips}}, {{external.by_profile.wcag.control_fp_seconds}}/{{external.by_profile.wcag.control_seconds}} calm camera seconds flagged. {{remediation.passed}}/{{remediation.n_clips}} hazardous clips fixed and passing whole-file re-verification. Failure gallery: `eval/results/frozen/failures.md`. |
| **Innovation (20%)** | `docs/PRIOR_ART.md`, `docs/AGENT.md` | Existing checkers (Harding FPA, PEAT, EA IRIS) answer pass/fail; none localises the hazard on screen, none repairs it, none verifies a repair. Here localisation makes a regional repair possible, the same analyzer verifies every candidate, and the model's strength parameter comes from the physics of the filter (`parameter_hints` in `steadyframe/agent/tools.py`). |
| **Real-world impact (20%)** | `README.md` ("The problem": incidents and requirements, sourced), `steadyframe/record.py` | UK broadcast delivery (AS-11 UK DPP) has a mandatory PSE pass/fail field; the verification record fills those fields and can be re-checked by anyone with `steadyframe verify`. The viewer warning track (`hazards.vtt`) helps people who watch the unrepaired original. Free tools exclude commercial use (PEAT) or stop at frame-level detection (IRIS). |
| **User experience (10%)** | the live site, `/judge`, `web/` | Nothing autoplays; the original sits behind a click-through warning and plays dimmed, small and slowed; `prefers-reduced-motion` respected; WCAG AA contrast; keyboard navigable; axe check in CI (`web/a11y-report.json`). Hazards are shown as stills with the region outlined and as plots, never as moving video. |
| **Documentation and presentation (10%)** | `README.md`, `docs/report/REPORT.md`, `docs/diagrams/`, the video | Every number in the report is a placeholder filled from a results file; one command reproduces each table (`make eval`, `make freeze`). Dated engineering log with every decision and bug: `docs/NOTES.md`. |
| **Cloud delivery, reproducibility, responsible operation (10%)** | `infra/` (CDK, 7 stacks), `infra/policies/`, `.github/workflows/ci.yml`, `docs/RESPONSIBLE_USE.md` | `make deploy` from a clean account; least-privilege IAM per component; 1-day object lifecycle, 7-day record TTL; CloudWatch dashboard, alarms and a cost budget to e-mail. The worker is an arm64 Lambda function fed by SQS (under 5 s end to end when warm, inside the free tier) with an ECS Fargate fallback, so the live demo answers in seconds and idles at about zero. `make demo` runs the whole loop locally with no credentials; `docker compose up --build` runs the web app, API and worker locally. |

## Agentic Vision Award

| Criterion (weight) | Evidence |
|---|---|
| **Substantive OpenCV 5 and agent integration (30%)** | The agent's seven tools (`steadyframe/agent/tools.py`) are OpenCV 5 analysis, rendering and verification. The model never sees pixels; its context is built only from analyzer measurements. |
| **Orchestration and appropriate autonomy (25%)** | Perception (analyze, segment detail) → decision (model chooses strategy and strength) → action (render a candidate) → perception again (re-analysis) → accept, escalate, or ask a person. `docs/diagrams/agent_workflow.svg`. On `/judge`, "The check fails, so the model changes its plan" is a recorded live run where a failed re-analysis changed the next call. |
| **Task effectiveness and evaluation (20%)** | Live Bedrock agent on the 25-clip suite: {{agent_vs_fixed_bedrock.agent.passed}}/{{agent_vs_fixed_bedrock.agent.n_clips}} fixed, {{agent_vs_fixed_bedrock.agent.mean_iterations_per_segment:.2f}} attempts per hazard vs {{agent_vs_fixed_bedrock.fixed.mean_iterations_per_segment:.2f}} for the fixed policy, SSIM inside the hazard region {{agent_vs_fixed_bedrock.agent.mean_ssim_inside:.3f}} vs {{agent_vs_fixed_bedrock.fixed.mean_ssim_inside:.3f}}, {{agent_vs_fixed_bedrock.cost_usd:.2f}} USD of model calls. Where it did worse is listed (`eval/results/frozen/agent_vs_fixed_bedrock.md`). |
| **Failure handling, observability, security, human control (15%)** | Adversarial planner (`eval/guardrails.py`): {{guardrails.summary.held}}/{{guardrails.summary.runs}} attacks held, {{guardrails.summary.false_pass}} false passes, {{guardrails.summary.refused_calls}} hostile calls refused; instructions planted in the file name and metadata never reach the model. Every provider failure falls back to the deterministic policy and says so in the trace. Strong repairs pause for a person; decisions are consumed once. Every call goes to `trace.jsonl` and DynamoDB; CloudWatch metrics and alarms. |
| **UX, documentation, demonstration (10%)** | Trace viewer with "this verify result changed the next call" highlights; approval dialog; annotated traces in `docs/examples/`; `/judge`. |

## Best Use of COOL Award: not entered

COOL is sold through AWS Marketplace, and this project deliberately runs on free-tier services
and credits only, so COOL never executed and no COOL result is claimed. What exists, untested on
COOL itself: a benchmark launcher that would run the analyzer on a Graviton4 instance from the
COOL AMI and refuse to start unless `cv2` loads from `/opt/cool` (`bench/ec2.py`), and an opt-in
worker engine built FROM the COOL container image (`-c worker_engine=cool`, `infra/README.md`).

## Not claimed

A pass means the published thresholds were met as implemented here (`docs/STANDARDS.md`); it is
not a certification and not medical advice. Limits: `docs/report/REPORT.md` section
"Limitations" and the last section of `/judge`.
