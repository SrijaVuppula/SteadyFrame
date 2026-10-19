# Responsible use

**SteadyFrame is not a medical device.** It checks video against published
photosensitivity thresholds (WCAG 2.2 SC 2.3.1; ITU-R BT.1702 / Ofcom guidance as a
secondary profile) and rewrites segments that exceed them so that the same check passes.
That is all it claims.

## What the thresholds are and are not

- They are population-level guidelines derived from clinical studies. Individual sensitivity
  varies; some people react to stimuli below the thresholds and content that passes can
  still be uncomfortable or harmful for a particular person.
- They are defined on the *displayed* stimulus. We compute relative luminance from sRGB
  code values in the file. Display brightness, viewing distance, screen size, ambient light
  and player-side processing are unknown to us, so the real stimulus can differ.
- Heavy compression alters luminance and colour; we measured robustness to H.264 CRF 28
  and 35 on synthetic content (`eval/results/robustness.md`) but cannot cover every codec.
- The pattern detector is experimental and reports a warning, never a fail.
- We do not implement the WCAG exemption for fine balanced patterns (white noise), so such
  content is over-flagged rather than missed.

False negatives are possible. A pass is not a certification and must not be described as
one. Wording we use and ask users to keep: "checks video against published
photosensitivity thresholds". Wording we never use: "prevents seizures", "medically safe",
"certified", "seizure-free".

## Content safety in this project

- The synthetic generator (`synth/`) produces deliberately hazardous strobe clips. Its
  output lives under `data/` (gitignored), carries `WARNING.md`, is never committed and is
  never distributed. Please do not share the generated clips.
- The UI never autoplays uploaded content. Original playback sits behind a click-through
  warning, dimmed, small and slowed. Thumbnails are stills. Docs and the demo video show
  luminance plots and stills, not flashing clips.
- The remediated video is shown only after the analyzer verified the whole file.
- The recorded jobs bundled with the web app for the `/judge` tour (`web/public/judge/`)
  contain stills, plots, traces, records and the verified remediated output, never the
  hazardous input.

## The verification record and the warning track

- `record.json` / `record.html` say what was measured, with which thresholds and which build,
  and are re-checkable (`steadyframe verify`). The record says in its own text that it is not a
  certification. The AS-11 UK DPP PSE fields in it (`PSEPass`, `PSEManufacturer`,
  `PSEVersion`) are filled in that shape for convenience; which test tools a broadcaster
  accepts for those fields is the broadcaster's decision, and SteadyFrame is not on any such
  list.
- Threshold tests can miss: a UK TV advertisement that passed a Harding test was withdrawn in
  2024 after viewers reported seizures. That is one more reason the record states measurements
  rather than safety.
- `hazards.vtt` is a warning track for the original video. It helps a player warn viewers; it
  does not make the original safe to show.

## Data handling

- Uploads and outputs are stored in a private, encrypted S3 bucket behind presigned URLs
  and deleted by lifecycle rule after 24 hours. Job metadata and traces in DynamoDB expire
  after 7 days. No public buckets. Nothing is used for training.
- The agent sends analyzer measurements (numbers and segment ids) to the model, never
  frames, file names or container metadata. `eval/guardrails.py` plants instructions in a
  clip's file name and metadata tags and checks that none of that text reaches the model.
- Local mode (`docker compose up`) keeps everything on the machine.
- The public demo limits itself, so a visitor cannot run up its cost or crowd out others: 40
  Bedrock-planned checks a day overall and 8 per visitor (past either, the check runs with the
  free fixed policy and the page says why), 600 checks a day overall and 60 per visitor (past
  either, the API answers 429), and 20 requests a second across the API. A visitor is counted
  by a salted hash of their address and the day, kept for two days; the address itself is not
  stored. Details in `docs/API.md`.
- `steadyframe mcp` runs on the user's own machine with their permissions and reads only the
  files the agent names. Its agent is shown measurements only, like the built-in one, and a
  decision that needs a person goes to the person at the client (`docs/MCP.md`).

## Misuse considerations

- Could the analyzer be used to *make* content just under the thresholds? Yes, like any
  compliance checker. The thresholds are public; the tool adds nothing an author could not
  compute from the standard. We do not provide an "optimise toward the limit" mode and the
  conservative flag warns at exactly three flashes per second.
- The generator could be used to produce harmful content deliberately. It exists to test
  the analyzer; it renders synthetic grey/red rectangles, not persuasive content, and the
  same effect is trivial to produce with any video editor. We document this and keep its
  output out of the repository.

## Limitations of the evaluation

The detection evaluation is against synthetic ground truth produced by an independent
one-dimensional implementation of the rules and analytic area conditions; it shows that
the video analyzer implements the rules as written, not that the rules capture every real
hazard. The external set (`data/SOURCES.md`, `eval/external.py`) is small: EA IRIS's test
videos scored against IRIS's own expected results, Apple's flashing sample labelled by the
reference rules, and calm camera footage. The natural set (`data/natural.yaml`,
`eval/natural.py`) adds 17 openly licensed clips of real lights (emergency vehicles, club
lights, lightning, fireworks) labelled frame by frame by EA IRIS; it is ten minutes of video,
and on it SteadyFrame is stricter than IRIS where parts of the picture brighten while others
darken. Neither tool measures harm.
