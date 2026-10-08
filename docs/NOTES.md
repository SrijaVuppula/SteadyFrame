# Engineering notes

Dated log of what I checked, where, and what I decided. Newest at the bottom.

## 2026-09-20  OpenCV 5 wheel

- Checked: `pip index versions opencv-python-headless` -> latest is **5.0.0.93** (then 4.14.0.94).
  The 5.0.0.93 wheel ships for manylinux x86_64 and aarch64 (installed here on x86_64; the
  aarch64 wheel is exercised by the arm64 Docker build later).
- `cv2.__version__` reports `5.0.0`. Build info: FFMPEG YES (avcodec 62.28, avformat 62.12),
  Intel IPP 2026.0, pthreads parallel framework, no GStreamer.
- Video I/O check: `cv2.VideoWriter` with `mp4v` writes, `cv2.VideoCapture` reads back the
  right frame count; H.264 (written with an external ffmpeg) also decodes. So the headless
  wheel is sufficient for decode. We still keep an ffmpeg-pipe reader as a fallback because
  `CAP_PROP_FRAME_COUNT` is unreliable on some containers and we want ffmpeg for audio anyway.
- Decision: pin `opencv-python-headless==5.0.0.93`, assert `cv2.__version__.startswith("5.")`
  at import time.

## 2026-09-20  ffmpeg binary

- `apt` is not available in every environment we run in. `imageio-ffmpeg==0.6.0` ships a
  static ffmpeg 7.0.2 (linux x86_64 and aarch64) with libx264. We use it via
  `imageio_ffmpeg.get_ffmpeg_exe()`, overridable with `STEADYFRAME_FFMPEG`. It has no
  ffprobe, so metadata comes from `cv2.VideoCapture` props with an `ffmpeg -i` parse as fallback.

## 2026-09-20  WCAG 2.2 thresholds

- Source: w3c/wcag repository, files `guidelines/terms/20/general-flash-and-red-flash-thresholds.html`,
  `guidelines/terms/20/relative-luminance.html`, `guidelines/sc/20/three-flashes-or-below-threshold.html`
  (https://github.com/w3c/wcag, main branch, read 2026-09-20; the rendered text is
  https://www.w3.org/TR/WCAG22/#dfn-general-flash-and-red-flash-thresholds). Full quotes in `docs/STANDARDS.md`.
- Confirmed: 10% of max relative luminance, darker image < 0.80, three flashes per second,
  25% of any 10 degree field, 341 x 256 px on a 1024 x 768 display, sRGB linearisation with
  the 0.04045 knee.
- **Note:** WCAG 2.2 now defines saturated red via R/(R+G+B) >= 0.8 *and* a
  chromaticity difference of more than 0.2 in the CIE 1976 UCS (u'v') diagram, citing ISO 9241-391.
  The `max(0, R-G-B) * 320 > 20` rule I started from is the older working definition used by
  PEAT and by EA IRIS. Decision: implement the PEAT/IRIS rule (comparable with existing tools,
  used by the synthetic ground truth), and additionally compute the u'v' distance so the
  report can show both. Recorded in STANDARDS.md.

## 2026-09-20  Ofcom / ITU-R BT.1702

- Primary PDFs (ofcom.org.uk, itu.int) would not load for me at the time. The values
  below are from the Ofcom "Guidance Note for Licensees on Flashing Images and Regular Patterns
  in Television" (Annex 1) as reproduced by Epilepsy Action / ASA summaries and by the
  ACM TACCESS 2024 gap analysis (dl.acm.org/doi/full/10.1145/3694790):
  flash = change of 20 cd/m2 or more where the darker image is below 160 cd/m2; more than three
  flashes in any one second is a breach; the area rule is 25% of the *whole screen*; a
  potentially harmful regular pattern has more than five light-dark pairs of stripes, is high
  contrast, covers more than 25% of the screen and lasts more than half a second (or flashes /
  changes direction).
- Decision: expose these as the `broadcast` profile (area over the whole frame instead of the
  10 degree window; same 3 Hz rule). We do not have absolute cd/m2 without a display model, so
  the broadcast profile keeps the relative-luminance 0.10 transition threshold and says so.
  TODO: download Annex 1 and paste the exact quotes into STANDARDS.md.

## 2026-09-20  Prior art

- EA IRIS: https://github.com/electronicarts/IRIS, BSD-3-Clause, C++ library on OpenCV (vcpkg,
  version unpinned), detects luminance flash, red flash and patterns, CSV/JSON output,
  frame-level (no spatial localisation), no remediation. Also an Unreal plugin.
- Apple VideoFlashingReduction: https://github.com/apple/VideoFlashingReduction, MIT, Swift /
  MATLAB / Mathematica reference of Apple's "Video flashing reduction" algorithm (risk score
  plus global dimming). Global, not localised, no verification loop.
- PEAT (Trace Center): free download, closed source, licence prohibits use on content produced
  commercially for broadcast, film, home entertainment or gaming. Windows only.
- Harding FPA (Cambridge Research Systems): commercial, the broadcast reference.
- Flikcer (arXiv 2108.09491): Chrome extension, detection + dimming in the browser.
- Decision: IRIS is a usable *detection baseline* if it builds; it is a C++/vcpkg project so
  we treat it as optional in `eval/` (skipped when the binary is absent). Details in `docs/PRIOR_ART.md`.

## 2026-09-20  COOL

- Sources: AWS Marketplace listings "Cloud Optimized OpenCV For AWS Graviton4"
  (prodview-fdvbfiewzuehs) and "...For Graviton3" (prodview-5b2boxpyztidw); AWS blog
  "Accelerating OpenCV on Graviton - the COOL framework"; opencv.org/cool. Read via search
  snippets on 2026-09-20 (the pages themselves were blocked from here).
- Delivery: **AMIs** (Ubuntu 24.04 LTS) with a precompiled OpenCV build. Based on **OpenCV 5**
  with Arm KleidiCV optimisations. Accelerated operations named: resize, Gaussian / adaptive
  Gaussian threshold, contour detection ("and more"). Reported average speedup about 1.5x
  (blog), 30% in one example. Pricing: the software price per hour was not visible in the
  snippets; TODO: read it from the listing when subscribing.
- Decision: our core workload (per-frame `cv2.resize` INTER_AREA, `cv2.boxFilter`,
  `cv2.LUT`, `cv2.connectedComponentsWithStats`, `cv2.GaussianBlur` in SSIM and S1) is exactly
  the class of op COOL claims to speed up. Since COOL *is* OpenCV 5, the same code runs in both
  paths; `bench/run.py` records `cv2.getBuildInformation()` and the loaded `.so` path as the
  proof of which build executed. Benchmark instances: c8g (Graviton4) with the COOL AMI vs the
  stock wheel on the same instance vs c7i (x86) - same size class.

## 2026-09-20  Bedrock Converse tool use

- boto3 1.43.98 `bedrock-runtime.converse(modelId, messages, system, toolConfig={tools:[{toolSpec:
  {name, description, inputSchema:{json: ...}}}]}, inferenceConfig)`. Tool calls come back as
  `stopReason == "tool_use"` with content blocks `{"toolUse": {"toolUseId", "name", "input"}}`;
  results are sent as a user message with `{"toolResult": {"toolUseId", "content":[{"json": ...}],
  "status": "success"|"error"}}`.
- Model IDs are not hardcoded. `STEADYFRAME_BEDROCK_MODEL_ID` (default in `config/agent.yaml`)
  is expected to be a cross-region inference profile such as `us.<vendor>.<model>-v1:0`;
  the owner picks whatever is enabled in the account.

## 2026-09-20  Project name

- "SteadyFrame" is used by a few unrelated video production companies (steadyframeatl.com,
  steadyandframe.com, steadyframe.in) and nothing in software/accessibility. No trademark hit
  found for a software product. Decision: keep the name; the GitHub repo is `steadyframe`.

## 2026-09-20  Analyzer: grid-first per-frame path

- Per-pixel luminance + red metrics (LUT, transform, split, divide on 921k pixels) cost
  ~19 ms per 720p frame, 11 ms of it in `cv2.split`. Linearising once and INTER_AREA
  downsampling the 3-channel linear frame to the grid before `cv2.transform` is exact for
  luminance (linear map of a mean = mean of the map) and moves the red metrics to the
  cell-average colour. 1.6 ms per frame afterwards; detection results identical on the suite.
- Consequence recorded in STANDARDS.md: the red rule is evaluated on the cell-average colour.

## 2026-09-20  S1 blends in linear light

- Averaging sRGB code values left a 24% residual luminance swing on a 6 Hz square wave with
  alpha 0.1 where the EMA maths says 13%; in linear light the measurement matches the
  prediction, and the parameter hint `alpha` from the measured swing/rate becomes usable.

## 2026-09-20  Mask feathering is outward only

- A Gaussian feather applied to the exact region box gave the region's edge pixels ~84%
  weight; the analyzer kept failing those edge cells. The box is now padded by 3 sigma
  before the blur so every original pixel keeps weight >= 0.99.

## 2026-09-20  Human decisions are consumed once

- A decision passed on resume applied to every later `request_human_approval` for the same
  segment, so one rejection rejected everything. Decisions are popped on first use; a new
  request pauses the job again.

## 2026-09-20  Heuristic provider

- `eval/agent_vs_fixed.py` needs an offline agent; the `HeuristicProvider` follows the
  exact tool protocol and uses the parameter hints. It is labelled everywhere as a stand-in
  and the report keeps a separate row for the live Bedrock run.


## 2026-10-08  External clips

- Wikimedia Commons, the Internet Archive and Pexels still don't load from the build machine,
  but GitHub does. Three openly licensed sets found there: EA IRIS's test videos (BSD-3)
  with IRIS's own expected per-frame logs, Apple's VideoFlashingReduction sample clip (MIT),
  and the Intel IoT DevKit sample videos (CC BY 4.0, real camera footage). URLs pinned to
  commits in `data/SOURCES.md`, labels and sha256 in `data/external.yaml`,
  scored by `eval/external.py`.
- IRIS applies the area rule to the whole screen, so `broadcast` is the like-for-like
  profile. IRIS also has an "extended failure" rule (four or more transitions a second for
  four of five seconds) that we don't implement. It fires on `2Hz_6s` (with no flash
  failure, so that clip passes in both tools' flash rule) and on `3Hz_6s` (alongside flash
  failures).
- The Apple clip is six bursts of uniform full-frame sine flashing (about 1, 2, 3, 4, 6 and
  12 Hz). Uniform, so the 1-D reference on the frame mean is a valid label; the script checks
  the quadrant deviation before using it.
- Still no concert or emergency-vehicle footage.

## 2026-10-08  Two remediation bugs the synthetic suite never hit

- Neighbouring hazards. The Apple bursts are ~0.8 s apart. A candidate clip spans the
  segment plus 0.5 s margins plus 1 s of padding, so it contains the start of the next burst,
  which is not treated yet, and `verify_candidate` counted that burst against the current
  segment. Every strategy "failed" and both policies ran out of attempts. Now each segment
  records `detected_s` (the first frame that broke the rule, before the start is back-dated),
  and a remaining hazard whose failing frames lie inside another not-yet-accepted segment is
  reported as `remaining_in_untreated_segments` and not held against the candidate. Accepted
  segments are rendered into every candidate, so a hazard there still counts. The whole-file
  re-verification at the end is unchanged and still decides the job.
- Flashing at the limit. IRIS `3Hz_6s` flashes at exactly three flashes a second for 6 s;
  frame timing at 25 fps puts seven transitions in a few windows around 1.2-1.7 s. Treating
  only those frames adds a transition at the treatment's own boundary next to windows that
  already hold six, and they fail. The analyzer now reports each segment's "episode" (the
  contiguous frames where the at-limit cells cover more than the area threshold), and a plan
  widens to it when it reaches past the 0.5 s margin. On clean bursts it doesn't, so the
  synthetic suite's plans are unchanged. Re-ran `make eval`: detection, robustness and
  remediation are identical except `r_red_strobe_region`'s SSIM inside the region (0.877 ->
  0.880). The previous commit gives 0.880 on this machine too, so that is the encoder build
  on this host, not the change.
- Heuristic provider: after a failed S4 on an S1 base it now retries once at half alpha, as
  it already did for regional S1, and the ladder matches attempts by (strategy, base) so
  S4/S2 is reachable after S4/S1. On IRIS `flashStripes` (12.5 Hz, full swing) the hinted
  alpha 0.165 is right for the steady state but the EMA's start-up steps are transitions too;
  the retry at 0.083 passes.
- Cost of the episode bookkeeping: one extra `cv2.boxFilter` on the 64x48 at-limit mask per
  frame and type. Interleaved runs of `bench_strobe.mp4` on this host, previous commit vs
  this one: 560 / 569 fps vs 558 / 549 fps (median of 9). Within noise, so the frozen
  benchmark (634 fps on the original build host) still describes the analyzer.
- The live Bedrock results in `eval/results/frozen/agent_live/` and
  `agent_vs_fixed_bedrock.*` were produced before these changes (commit fdf0c19). On the
  synthetic suite the changes don't alter any plan, so they stand; they were not re-run.

## 2026-10-08  Ofcom wording, infra lockfile, benchmark launcher

- The Ofcom PDF still doesn't open from here. One sentence of the legacy guidance note
  (20 cd/m2, darker image below 160 cd/m2) is quoted in STANDARDS.md from a search index's
  extract of the PDF, labelled as such. The rest of Annex 1 still needs pasting from the PDF.
- `infra/package-lock.json` committed (CDK CLI 2.1142.0), so `npm ci` in `make deploy` works
  from a clean checkout.
- `bench/ec2.py`: the three benchmark configurations without SSH. User-data gets presigned S3
  URLs for the source archive and the results; the instance self-terminates and the script
  terminates it anyway. Not run yet: needs the deploy credentials and, for COOL, the
  Marketplace subscription and AMI id.
