# SteadyFrame

Finds the flashing in a video that can trigger seizures, repairs only that spot, and proves the
repair. OpenCV 5 and AWS.

**Try it live: [d25yofo4x3sac8.cloudfront.net](https://d25yofo4x3sac8.cloudfront.net)**. No sign-up; it works on a phone or a laptop.

1. Pick a test clip and press **Run check**. A real job runs on AWS while you watch: within a
   few seconds the hazard is located on screen and in time, a repair is planned and applied,
   and the same analyzer re-checks the result. With **Bedrock model** selected you watch the
   model plan the repair step by step (about 20 to 30 seconds); **Fixed policy** takes a few
   seconds. The four clips tell a short story: a flashing box that is fixed in place, a red
   strobe, a full-screen red strobe that has no gentle fix and asks you to approve one, and a
   calm clip where nothing should be flagged.
2. When a check asks for your decision, press **Approve** or **Reject**. The paused job resumes
   from its saved state. Then download the repaired video and its verification record, or
   check a clip of your own (up to 120 s).

Nothing on the page plays: hazards are shown as still frames and plots, never as moving video.

![The SteadyFrame live demo after a check. A dark film-strip banner reads "Find the flash. Steady the frame." with the credits planned by Amazon Bedrock, checked by OpenCV 5, approved by you. On the left, the clip picker shows four drawn thumbnails (Flashing box selected, Red strobe, Full-screen red, Calm clip), the planner and standard toggles, the Run check button and a drop zone for your own clip. On the right, the check for Flashing box took 4.2 seconds with the fixed policy and carries two rubber stamps, Before: Fail and After: Pass. A chart of flashes per second shows the red before line peaking at 6, above the dashed limit of 3, and the green after line staying under it. Below, a still frame with the flagged region outlined reads 6 flashes/s, centre, 1.00 to 4.43 s, fixed with temporal low-pass, SSIM 0.86, followed by the downloads: verification record, repaired video, warning track and JSON.](docs/screenshots/live_run.png)

## The problem

Flashing and high-contrast patterned images can trigger seizures in people with photosensitive
epilepsy: about 3 to 5% of the roughly 50 million people with epilepsy worldwide, most often
first between the ages of 7 and 19 ([WHO](https://www.who.int/news-room/fact-sheets/detail/epilepsy),
[Epilepsy Society](https://epilepsysociety.org.uk/sites/default/files/2025-04/PhotosensitiveepilepsyApril2025.pdf)).
One cartoon broadcast in Japan on 16 December 1997 sent 685 people to hospital
([Annals of Neurology via ScienceDaily](https://sciencedaily.com/releases/1999/06/990601080722.htm)).
Strobing images have been sent to people with epilepsy on purpose, and since 2024 that is a
crime in the UK ([Online Safety Act 2023, s.183](https://www.legislation.gov.uk/ukpga/2023/50/section/183)).

The rules exist: WCAG 2.2 success criterion 2.3.1 for the web, ITU-R BT.1702 and Ofcom guidance
for broadcast, and UK programme delivery carries a mandatory photosensitivity field in its
[AS-11 UK DPP](https://amwa-tv.github.io/AS-11_UK_DPP_HD/AMWA_AS_11_UK_DPP_HD.html) metadata.
The tools don't fit the people who need them. The broadcast checker (Harding FPA) is
commercial, and per-video test services start at about £30
([hardingtest.com](https://www.hardingtest.com/)). The free checker, PEAT, may not be used on
commercially produced broadcast, film or game content and was last released in 2017
([Trace Center](https://trace.umd.edu/peat/)). EA's open-source
[IRIS](https://github.com/electronicarts/IRIS) reports frames, not where on screen. All of them
answer pass or fail for the whole file; none repairs the problem.

## What it does

**OpenCV measures. The model plans. Plain code decides whether a repair passed, and a person
signs off on anything drastic.**

SteadyFrame checks a video against the published thresholds, finds each hazard's time range
and region on screen, and repairs it with the least invasive of six strategies, from a regional
temporal low-pass in linear light to a frame hold. Every candidate repair goes back through
the same analyzer; if it still fails, the next attempt is stronger; if the only passing repair
changes the picture too much, the job pauses for a person. The whole file is re-verified at
the end. You get the repaired video, a verification record that anyone can re-check with one
command, and a WebVTT warning track for players that show the original.

What the model decides, and what code decides:

- **The model** (Amazon Bedrock, through tool use) chooses which strategy to try on each
  segment and how strong to make it, from the analyzer's measurements and physics-based
  parameter hints, and when to ask a person. It never sees pixels, file names or metadata.
- **Code** measures every frame, renders each candidate, re-analyses it, refuses to accept
  anything unverified, failing or unapproved, enforces the attempt budgets, falls back to a
  deterministic policy if the model fails, and re-verifies the whole file. Only the analyzer
  can mark a job as passed.

### How SteadyFrame uses OpenCV 5

All image work is OpenCV 5 (`opencv-python-headless 5.0.0.93`, asserted at import).

| What for | OpenCV | Code |
| --- | --- | --- |
| Decode frames with timestamps | `VideoCapture` (ffmpeg pipe fallback) | [`io/video.py`](steadyframe/io/video.py) |
| sRGB to linear light, one table lookup per frame | `LUT` | [`luminance.py`](steadyframe/luminance.py) |
| Downsample the linear frame to a 64x48 grid (exact for luminance, 12x faster than per-pixel maps) | `resize` with `INTER_AREA` | [`luminance.py`](steadyframe/luminance.py) |
| Relative luminance and red metrics per cell | `transform`, `split`, `max` | [`luminance.py`](steadyframe/luminance.py) |
| The 25%-of-any-10-degree-field area rule | `boxFilter` | [`area.py`](steadyframe/area.py) |
| Hazard regions | `connectedComponentsWithStats` | [`analyzer.py`](steadyframe/analyzer.py) |
| Regular-pattern detector (experimental) | `dft`, `magnitude`, `blur` | [`pattern.py`](steadyframe/pattern.py) |
| Temporal low-pass and swing compression repairs | `accumulateWeighted` | [`s1_temporal.py`](steadyframe/remediate/s1_temporal.py), [`s2_swing.py`](steadyframe/remediate/s2_swing.py) |
| Feathered region masks | `GaussianBlur` | [`mask.py`](steadyframe/remediate/mask.py) |
| Picture quality of each repair (SSIM, PSNR) | `GaussianBlur`, `cvtColor`, `dilate` | [`quality.py`](steadyframe/remediate/quality.py) |
| Red desaturation toward equal-luminance grey | `LUT`, `transform` | [`colour.py`](steadyframe/remediate/colour.py) |
| Warning card, still frames with regions outlined | `putText`, `rectangle`, `imencode` | [`s6_card.py`](steadyframe/remediate/s6_card.py), [`worker.py`](service/worker.py) |

Per frame the analyzer spends 79% of its time inside OpenCV built-ins and runs at about 600
frames a second on 720p on four vCPUs. Every threshold and the text it comes from:
[`docs/STANDARDS.md`](docs/STANDARDS.md).

### How SteadyFrame uses AWS

| Service | What for | Code |
| --- | --- | --- |
| Amazon Bedrock (Converse API, tool use) | Planning each repair from the measurements | [`agent/providers.py`](steadyframe/agent/providers.py), [`agent/loop.py`](steadyframe/agent/loop.py) |
| AWS Lambda, arm64 (Graviton), container image | The worker that runs each job, in seconds | [`lambda_worker.py`](service/lambda_worker.py), [`stacks/worker.py`](infra/stacks/worker.py) |
| Amazon EventBridge | Keeps one worker warm every five minutes | [`stacks/worker.py`](infra/stacks/worker.py) |
| Amazon ECS on Fargate, ARM64 | Fallback worker for jobs left waiting | [`worker.py`](service/worker.py), [`stacks/worker.py`](infra/stacks/worker.py) |
| Amazon SQS | Job queue with a dead-letter queue | [`stacks/queue.py`](infra/stacks/queue.py) |
| Amazon API Gateway and AWS Lambda | The REST API: jobs, uploads, traces, approvals, downloads | [`lambda/handler.py`](service/lambda/handler.py), [`core.py`](service/core.py) |
| Amazon S3 and Amazon CloudFront | Uploads and outputs (private, 1-day lifecycle) and the website | [`stacks/storage.py`](infra/stacks/storage.py), [`stacks/web.py`](infra/stacks/web.py) |
| Amazon DynamoDB | Job records and the decision trace (7-day TTL) | [`core.py`](service/core.py), [`stacks/data.py`](infra/stacks/data.py) |
| Amazon CloudWatch, Amazon SNS, AWS Budgets | Logs, metrics, dashboard, alarms and a monthly cost budget, by e-mail | [`stacks/observability.py`](infra/stacks/observability.py) |
| IAM | A least-privilege policy per component | [`infra/policies/`](infra/policies/) |
| AWS CDK | All of the above, in seven stacks | [`infra/`](infra/README.md) |

Everything runs on free-tier services and credits: nothing runs between jobs, and the idle cost
is about zero.

![SteadyFrame on AWS: the browser talks to API Gateway and an API Lambda, which puts jobs on SQS; an arm64 Lambda worker running OpenCV 5 takes each job, kept warm by EventBridge, with an ECS Fargate fallback; the worker plans with Amazon Bedrock and writes to S3, DynamoDB and CloudWatch.](docs/diagrams/architecture.svg)

### Measured

Every number comes from a script and is frozen in [`eval/results/frozen/`](eval/results/frozen/);
[`docs/report/REPORT.md`](docs/report/REPORT.md) has the methods and full tables.

- **Detection:** 44 of 44 synthetic clips with independent ground truth judged correctly,
  including 17 of 17 boundary cases (3 vs 3.5 vs 4 flashes a second, a 0.09 vs 0.11 swing, a
  darker state of 0.79 vs 0.81, 24% vs 26% of the area). Per-second F1 1.000; 16 of 16 H.264
  re-encodes keep their verdict.
- **Other people's clips:** 18 of 18 third-party clips judged correctly. On EA IRIS's own test
  videos SteadyFrame matches IRIS's expected verdict on 8 of 8, and 35 of 35 frames IRIS fails
  fall inside a detected segment. In 9 minutes of real camera footage, 0 of 551 seconds were
  wrongly flagged.
- **Repair:** 25 of 25 hazardous clips repaired and passing whole-file re-verification. The
  live Bedrock agent also fixed 25 of 25, with 1.04 attempts per hazard against 1.10 for the
  fixed policy, and kept more of the picture inside the hazard region (SSIM 0.882 against
  0.861), for $3.04 of model calls for the whole suite. It was slower and needed more attempts
  on two red clips; the report lists every case where it did worse.
- **Trying to break it:** a hostile planner on the same tools tried to accept unverified and
  failed repairs, skip or fake the human approval, finish early, forge ids, push parameters out
  of range, burn the budget and stall; one more clip hid instructions in its file name and
  metadata. 10 of 10 attacks held, 0 false passes, and none of the planted text reached the
  model ([`eval/guardrails.py`](eval/guardrails.py)).
- **Speed:** a job on the warm Lambda worker takes about 4 seconds end to end, and about 46
  seconds from cold; it took 505 seconds when the only worker was Fargate scaling from zero.
- **Accessibility:** zero axe-core violations on the live demo and job pages, checked in CI.

## Structure

- `steadyframe/` — the analyzer, threshold profiles, the six repair strategies, the agent's
  tools and loop, the verification record, and the command line.
- `service/` — the API (Lambda and a local FastAPI app), the workers (Lambda and ECS), the test
  clips, `make demo` and the deployed smoke test.
- `web/` — the live demo and job pages (React, TypeScript), flash-safe and WCAG AA.
- `infra/` — the AWS CDK app, seven stacks, and the exported IAM policies.
- `eval/` — every evaluation script; `synth/` — the synthetic clip generator and the independent
  reference implementation used as ground truth; `bench/` — the throughput benchmark.
- `docs/` — standards, the agent, the API, prior art, responsible use, the dated engineering log,
  the technical report and the rubric-to-evidence map ([`docs/JUDGES.md`](docs/JUDGES.md)).

## Setup

Requires Python 3.11 and, for the web app locally, Docker. No credentials are needed to run
SteadyFrame on your own machine.

```bash
git clone https://github.com/SrijaVuppula/SteadyFrame.git && cd SteadyFrame
make install     # virtualenv with the pinned dependencies (requirements.lock)
make demo        # renders the test clips, checks, repairs and verifies them, in seconds
```

`make demo` writes `demo/<clip>/record.html` (the verification record), `before_after.png` and
`hazards.vtt`. The rendered input clips flash by design; open the records and plots, not the
inputs.

For the web app, API and worker on your machine, still without credentials:
`docker compose up --build`, then open http://localhost:8080.

From the command line:

```bash
steadyframe analyze in.mp4 --json out.json --plot out.png --vtt hazards.vtt   # exits 2 on fail
steadyframe fix in.mp4 --policy fixed -o safe.mp4 --report report.json --record record.json
steadyframe verify safe.mp4 --record record.json   # re-hash and re-analyze; exits 4 if it doesn't hold
```

### The Bedrock planner

`steadyframe fix in.mp4 --policy agent ...` plans with a model on Amazon Bedrock. It needs AWS
credentials and `STEADYFRAME_BEDROCK_MODEL_ID` set to a Bedrock inference profile with tool use;
the model id is configuration only and never in the code. `--policy heuristic` runs the same
loop offline with a deterministic stand-in. Details: [`docs/AGENT.md`](docs/AGENT.md).

### Deploy to AWS

```bash
make web
make deploy CDK_ARGS="-c bedrock_model_id=<inference profile id> -c alert_email=<you@example.com>"
make smoke       # uploads a test clip to the deployed API and checks the repaired output passes
```

[`infra/README.md`](infra/README.md) has the stacks, the context options, the costs and how to
tear it down (`make destroy`).

### Other commands

- `make test` — the test suite (pytest, including the CDK template tests)
- `make lint` — ruff check and format
- `make synth` and `make real` — generate the synthetic suite; download the third-party clips
- `make eval`, `make freeze`, `make report` — run every evaluation, freeze the results, render the report
- `make slides` — results slides for the video, from the frozen numbers
- `make judge` — re-record the example jobs bundled with the web app
- `make bench` — the analyzer throughput benchmark on this machine

## Responsible use and privacy

SteadyFrame checks video against published photosensitivity thresholds. It is not a medical
device, and a pass means the thresholds were met as implemented here, not that a clip is safe
for every viewer; threshold tests have known misses. The web app never autoplays anything, and
hazardous inputs are never shown or bundled. Uploads and outputs are deleted after one day, job
records after seven, and nothing is used for training. The model receives analyzer numbers
only. See [`docs/RESPONSIBLE_USE.md`](docs/RESPONSIBLE_USE.md).

## Status and limits

Deployed and working end to end on AWS, as above. Known limits, each measured or stated in
the report:

- Luminance is relative to peak white (sRGB). On the Ofcom note's own reference display its 20
  and 160 cd/m² limits are exactly the 0.10 and 0.80 used here, but a brighter real display is
  not modelled.
- The area rule runs on a grid, so a hazard right at the 25% boundary can flip with grid size.
- A full-screen strobe has no regional repair; when the repair changes the picture too much,
  the job waits for a person.
- The pattern detector is experimental and off by default. The third-party set is small, with no
  labelled concert or emergency-vehicle footage yet.
- The optional COOL (Cloud Optimized OpenCV) engine and benchmark are in the code but have not
  been run, because they need a paid AWS Marketplace subscription.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Synthetic test clips are generated
locally and never distributed; third-party clips are listed with their licences in
[`data/SOURCES.md`](data/SOURCES.md).
