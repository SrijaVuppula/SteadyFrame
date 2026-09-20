# Demo video script (max 5:00; target 4:30)

Rules: no unremediated flashing content is shown at full size or speed. Hazards appear as
luminance plots and stills. If a strobe clip must appear, it is small, dimmed (50%),
slowed (25%) and an on-screen warning shows five seconds before.

| t | shot | voice-over |
|---|---|---|
| 0:00-0:20 | Owner on camera | "Hi, I'm Srija. Flashing video can trigger seizures in people with photosensitive epilepsy. The tools that check for it are commercial or restricted, they say pass or fail, and they don't tell you where the problem is or fix it. SteadyFrame finds the hazard, fixes it with the smallest change it can, and checks its own work." |
| 0:20-0:35 | Title card, then the problem slide: PEAT licence quote, Harding, "no localisation, no fix" | "It checks video against published thresholds, WCAG 2.3.1 and the broadcast guidance, using OpenCV 5, and runs on AWS." |
| 0:35-2:35 | **Live demo** on the deployed site. Upload a sample (the region strobe). Job runs. | "Upload a clip. The worker, an ARM64 Fargate task running OpenCV 5, computes relative luminance per frame, tracks luminance transitions per cell of a grid, counts flashes in a sliding one-second window and applies the area rule." |
| | Hazard timeline appears. Click a segment: still frame with the region box; region luminance plot. | "Here's the hazard: 6 flashes a second, a 0.5 luminance swing, in this region, from 1.0 to 3.4 seconds. Not a pass/fail, a location." |
| | Open the agent trace viewer. Scroll: analyze -> detail -> apply S1 -> verify -> accept. | "Now the agent. It only sees these numbers, never pixels. It reads the flash rate and swing, picks the gentlest strategy, a regional temporal low-pass with an alpha it computed from the measurements, renders it, and then re-runs the same analyzer on the result. Here the verify came back 'still failing', so it lowered alpha and tried again. Only a verified candidate gets accepted." (Use the escalation trace if the live one passed first try.) |
| | Approval dialog on a second sample (the one that needs S5/S6). Click Approve. | "When a fix is invasive, it stops and asks. The job pauses, the state persists, and it resumes with my decision." |
| | Before/after luminance plot. Download the safe video; play it (this one is verified safe, still shown small). | "The whole file is re-verified at the end. Same clip, flash removed, audio untouched." |
| 2:35-3:20 | Architecture diagram (docs/diagrams/architecture.svg) | "Browser to API Gateway and Lambda, uploads by presigned URL to S3 with a 24-hour lifecycle, jobs through SQS to a Fargate worker on Graviton. Bedrock runs the planner through the Converse tool-use API. Infrastructure is CDK; `make deploy` from a clean account. Everything the agent does goes to a trace in DynamoDB, which is what you saw in the viewer." |
| 3:20-4:20 | Results slides from eval/results: detection table, boundary cases, remediation table, agent vs fixed, benchmark chart (3 configs). Then the failure gallery. | "On the synthetic suite, 44 clips including every boundary case in the standard, detection is exact, and every hazard was fixed and re-verified. The agent needed fewer iterations and left more of the picture intact than the fixed policy. On Graviton with COOL the analyzer ran at N times realtime versus M on x86 (numbers from bench/results/comparison.md). And here's where it fails: a region edge that flips with grid size, sub-threshold flashing the tool ignores by design, the experimental pattern detector." |
| 4:20-4:35 | Owner on camera | "It's not a medical device and a pass is not a certification. It's an open tool that tells creators where the problem is and hands them a fix they can check. Code, report and endpoint are in the submission. Thanks." |

Shot list to capture: (1) camera intro and outro; (2) screen recording of the full demo
at 1080p; (3) trace viewer close-up; (4) approval dialog; (5) before/after plot;
(6) slides exported from `docs/report/`; (7) benchmark chart.
