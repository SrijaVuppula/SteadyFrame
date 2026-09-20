# Devpost submission text

## Project name
SteadyFrame

## Tagline
Finds flashing hazards in video, fixes them with the least invasive change, and verifies its own fix. OpenCV 5 + AWS.

## Inspiration
Flashing video can trigger seizures for people with photosensitive epilepsy. The standard
checker (Harding FPA) is commercial; the free one (PEAT) may not be used on commercial
broadcast, film or game content and is a decade old. Both say pass or fail. A creator who
fails learns nothing about where, and gets no fix.

## What it does
Upload a video. SteadyFrame checks it against published photosensitivity thresholds
(WCAG 2.3.1, ITU-R BT.1702 / Ofcom), localises every hazard in time and space, and runs a
closed loop: pick the least invasive fix for the segment, apply it, re-run the analyzer on
the result, escalate or ask a human, and re-verify the whole file. You get a hazard
timeline, before/after luminance plots, the agent's decision trace, a JSON report and a
downloadable video that passes the same check.

## How we built it
- Analyzer in OpenCV 5 (`opencv-python-headless 5.0.0.93`): per-frame relative luminance
  through a 256-entry `cv2.LUT`, `INTER_AREA` downsampling to a 64x48 grid, a vectorised
  per-cell transition state machine implementing the "adjacent peaks and valleys" rule,
  trailing one-second windows driven by timestamps, the 25%-of-any-10-degree-field area
  rule with `cv2.boxFilter`, regions with `cv2.connectedComponentsWithStats`.
- Six remediation strategies from regional temporal smoothing (`cv2.accumulateWeighted` in
  linear light) to a warning card, with SSIM/PSNR quality metrics built on `cv2.GaussianBlur`.
- An agent on Amazon Bedrock (Converse API, tool use) that only sees analyzer measurements,
  writes every decision to a trace, and degrades to a deterministic fixed policy on any
  failure. Human approval for invasive fixes pauses and resumes the job.
- AWS: S3 + CloudFront frontend, API Gateway + Lambda, SQS, ECS Fargate ARM64 worker,
  DynamoDB, CloudWatch dashboard, all in CDK. `docker compose up` runs the same thing locally.
- Evaluation: a synthetic suite with every boundary case in the standard generated from an
  independent 1-D reference; detection, robustness, remediation, agent-vs-fixed and a
  three-configuration benchmark (x86, Graviton, COOL on Graviton) are each one command.

## Challenges
Averaging frames in sRGB code values left twice the luminance swing the maths predicted;
temporal smoothing had to move to linear light. A feathered mask that faded *inward* left
the edge cells of a region half-fixed and the verify step kept failing them, which is the
loop doing its job. Exactly-three-flashes-per-second is a floating-point boundary case
in both the generator and the window counter.

## Accomplishments
Exact agreement with the reference on all 44 synthetic clips and 17 boundary cases;
every hazard fixed and re-verified; a readable trace where you can see a verify result
change the next tool call; one-command reproduction of every number in the report.

## What we learned
Localisation is what makes remediation possible; a global dimmer is the only fix you can
apply without it. And a verification loop catches implementation mistakes that unit tests
on the pieces do not.

## What's next
Real-world labelled data, the fine-pattern exemption, a display model, and a browser
extension that calls the API.

## Special awards
- **Agentic Vision Award**: opt in. Evidence: `docs/AGENT.md`, `docs/diagrams/agent_workflow.svg`,
  annotated traces in `docs/examples/`, failure handling and human control in
  `tests/test_agent.py`, evaluation in `eval/results/agent_vs_fixed*.md`.
- **Best Use of COOL Award**: opt in. Evidence: `bench/README.md`, `bench/results/comparison.md`,
  build information and loaded library paths per configuration in `bench/results/*.json`.

## Built with
python, opencv 5, numpy, ffmpeg, react, typescript, aws-lambda, api-gateway, s3, cloudfront,
sqs, ecs-fargate, graviton, dynamodb, cloudwatch, bedrock, cdk, docker
