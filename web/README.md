# SteadyFrame web UI

React 19 + Vite + TypeScript, plain CSS, no UI framework. Talks only to the HTTP API described
in `../docs/API.md` (`src/types.ts` mirrors it; `src/api.ts` is the typed client).

## Run

    npm ci                       # pinned deps (package-lock.json); chromedriver download is skipped, see below
    npm run dev                  # http://localhost:5173, proxies /api -> http://localhost:8000 (docker compose)
    STEADYFRAME_API_TARGET=http://host:port npm run dev   # proxy somewhere else
    npm run build                # tsc --noEmit + vite build -> dist/
    npm run lint                 # eslint + tsc --noEmit
    npm run a11y                 # build, serve dist, run axe on 3 pages, write a11y-report.json

Config: `VITE_API_BASE` (default `/api`, same origin; CloudFront routes `/api/*` to API Gateway
in AWS, the vite dev server proxies it locally). `VITE_MOCK_API=1` or `?fixture=1` in the URL
serves the bundled fixtures instead of the network, so the UI can be previewed offline:

    npm run dev -- --open '/jobs/fx-passed?fixture=1'
    # fixture jobs: fx-passed (fixed policy, two segments), fx-approval (agent policy, paused
    # for approval), fx-red (general + red flash). Starting a job in fixture mode simulates the
    # status sequence over ~10 s.

## Accessibility check

`npm run a11y` runs `@axe-core/cli` (WCAG 2.x A/AA + best-practice tags) against `/`,
`/jobs/fx-passed` and `/jobs/fx-approval` in fixture mode and exits non-zero on any serious or
critical violation. Output: `a11y-report.json` (committed as evidence; rerun after UI changes). Browser resolution: `CHROME_PATH`, else the Playwright Chromium under
`PLAYWRIGHT_BROWSERS_PATH` (`/opt/pw-browsers`). Driver: `CHROMEDRIVER_PATH`, else the pinned
`chromedriver` npm package. Its postinstall is disabled in `.npmrc` because its version-lookup
host is blocked on some networks; the script instead installs the driver matching the detected
Chrome from `storage.googleapis.com/chrome-for-testing-public` on first run.

## Flash safety

- Nothing autoplays. The original clip sits behind a click-through warning and is then shown
  dimmed (`brightness(0.4)`), at most 320 px wide, at 0.25x speed, without loop, with controls
  and a stop button (`src/components/OriginalPreview.tsx`).
- Hazard thumbnails are server-rendered stills (`GET /jobs/{id}/frames/{segment}.png`).
- `prefers-reduced-motion` disables every transition; there are no animations or blinking
  elements in any mode.

## Layout

    src/api.ts            typed client (HTTP) + ApiClient interface
    src/mock.ts           fixture-backed client (VITE_MOCK_API=1 / ?fixture=1)
    src/types.ts          docs/API.md as TypeScript
    src/hooks/            useRoute (tiny router), useJob (polling), useSegments, useTrace
    src/pages/            HomePage (upload, samples, options), JobPage
    src/components/       HazardTimeline, LuminancePlot, SegmentInspector, StillFrame,
                          TraceViewer, ApprovalDialog, Downloads, RemediationSummary,
                          OriginalPreview, RemediatedPreview, JobStatusPanel, Layout
    src/fixtures/         job_*.json, segments_*.json, trace_*.json, samples.json
    public/fixtures/      still frames for the fixture jobs
    scripts/a11y.mjs      axe runner;  scripts/make_fixtures.py regenerates fixtures from real outputs
