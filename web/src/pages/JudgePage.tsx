// /judge: a stranger's 90-second path through the product. Everything on it is a recording
// of the worker's real outputs (eval/judge_bundle.py) or a number read from the frozen
// evaluation results; it needs no account, no upload and no running worker.
//
// Flash safety: nothing on this page moves on its own. No animation, no video autoplay, no
// blinking state; hazards appear only as still frames and plots.
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../api';
import { HazardTimeline } from '../components/HazardTimeline';
import { fmtRange, paramsText } from '../format';
import { href } from '../hooks/useRoute';
import { REPO_URL, VIDEO_URL, judgeFile, loadIndex, loadJudgeJob, type JudgeIndex, type JudgeJob, type JudgeResult } from '../judge';
import type { Segment, Timeline, TraceRecord } from '../types';

interface Props {
  navigate: (path: string) => void;
}

// ---------------------------------------------------------------- helpers

function where(s: Segment): string {
  const r = s.regions;
  if (!r.length) return 'on screen';
  const x0 = Math.min(...r.map((q) => q.x)), y0 = Math.min(...r.map((q) => q.y));
  const x1 = Math.max(...r.map((q) => q.x + q.w)), y1 = Math.max(...r.map((q) => q.y + q.h));
  if ((x1 - x0) * (y1 - y0) >= 0.8) return 'whole screen';
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const col = cx < 1 / 3 ? 'left' : cx > 2 / 3 ? 'right' : '';
  const row = cy < 1 / 3 ? 'top' : cy > 2 / 3 ? 'bottom' : '';
  return !col && !row ? 'centre' : `${row}${row && col ? '-' : ''}${col}`;
}

/** First n sentences, for chat bubbles; the full text is one click away in the trace. */
function brief(text: string, n = 2): string {
  // split only where a sentence ends and the next begins, never inside "0.955" or "S4."
  const parts = text.replace(/\s+/g, ' ').trim().split(/(?<=[.!?])\s+(?=[A-Z"'(])/);
  const out = parts.slice(0, n).join(' ').trim();
  return parts.length > n ? `${out} …` : out;
}

const peak = (xs: number[] | undefined) => (xs && xs.length ? Math.max(...xs) : 0);

type IconName = 'doc' | 'terminal' | 'captions' | 'play' | 'cross' | 'shield' | 'eye' | 'wrench' | 'stamp';

function Icon({ name }: { name: IconName }) {
  const p: Record<IconName, ReactNode> = {
    doc: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>,
    terminal: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M12 15h5" /></>,
    captions: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 13h4M13 13h4M7 16h10" /></>,
    play: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M10 9l5 3-5 3z" /></>,
    cross: <path d="M6 6l12 12M18 6L6 18" />,
    shield: <><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></>,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>,
    wrench: <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" />,
    stamp: <><path d="M9 3h6v6l2 3H7l2-3z" /><path d="M5 15h14v3H5zM7 21h10" /></>,
  };
  return (
    <svg className="jx-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {p[name]}
    </svg>
  );
}

// ---------------------------------------------------------------- before/after chart

function RateChart({ before, after, segments, duration }: { before: Timeline; after: Timeline | null; segments: Segment[]; duration: number }) {
  const W = 960, H = 280, ML = 40, MR = 16, MT = 16, MB = 34;
  const ymax = Math.max(4, Math.ceil(peak(before.general_rate_hz) + 1));
  const x = (t: number) => ML + (t / duration) * (W - ML - MR);
  const y = (v: number) => MT + (1 - v / ymax) * (H - MT - MB);
  const path = (tl: Timeline | null) => {
    if (!tl) return '';
    let d = '';
    for (let i = 0; i < tl.t.length; i++) d += `${d ? 'L' : 'M'}${x(tl.t[i]).toFixed(1)},${y(tl.general_rate_hz[i] ?? 0).toFixed(1)}`;
    return d;
  };
  const ticks = Array.from({ length: Math.floor(duration) + 1 }, (_, i) => i).filter((t) => duration <= 12 || t % 2 === 0);
  const pb = peak(before.general_rate_hz), pa = peak(after?.general_rate_hz);
  // the label goes in the middle of the widest stretch without a hazard, clear of the lines
  const edges = [0, ...[...segments].sort((a, b) => a.start_s - b.start_s).flatMap((s) => [s.start_s, s.end_s]), duration];
  let quietMid = duration / 2, widest = -1;
  for (let i = 0; i + 1 < edges.length; i += 2) {
    if (edges[i + 1] - edges[i] > widest) { widest = edges[i + 1] - edges[i]; quietMid = (edges[i] + edges[i + 1]) / 2; }
  }
  return (
    <svg className="jx-chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Flashes per second over ${duration.toFixed(0)} seconds: before the fix the peak is ${pb.toFixed(0)}; after it, ${pa.toFixed(1)}; the limit is 3.`}>
      {segments.map((s) => (
        <rect key={s.id} className="jx-chart-seg" x={x(s.start_s)} y={MT} width={Math.max(2, x(s.end_s) - x(s.start_s))} height={H - MT - MB} rx="6" />
      ))}
      {[0, Math.round(ymax / 2), ymax].map((v) => (
        <g key={v}>
          <line className="jx-chart-grid" x1={ML} x2={W - MR} y1={y(v)} y2={y(v)} />
          <text className="jx-chart-label" x={ML - 8} y={y(v) + 4} textAnchor="end">{v}</text>
        </g>
      ))}
      {ticks.map((t) => (
        <text key={t} className="jx-chart-label" x={x(t)} y={H - 10} textAnchor="middle">{t}s</text>
      ))}
      <line className="jx-chart-limit" x1={ML} x2={W - MR} y1={y(3)} y2={y(3)} />
      <text className="jx-chart-limit-label" x={x(quietMid)} y={y(3) - 8} textAnchor="middle">limit: 3 flashes a second</text>
      <path className="jx-chart-before" d={path(before)} />
      {after && <path className="jx-chart-after" d={path(after)} />}
    </svg>
  );
}

// ---------------------------------------------------------------- conversation

interface Bubble {
  key: number;
  who: 'model' | 'analyzer' | 'pipeline';
  text: string;
  action?: string;
  tone?: 'pass' | 'fail';
  pivot?: boolean;
}

function conversation(records: TraceRecord[]): Bubble[] {
  const out: Bubble[] = [];
  let lastVerifyFailed = false;
  for (const r of records) {
    const res = (r.result ?? {}) as Record<string, unknown>;
    if (r.kind === 'model') {
      const calls = (Array.isArray(r.tool_calls) ? r.tool_calls : []) as { name?: string; input?: Record<string, unknown> }[];
      const c = calls[0];
      const text = typeof r.text === 'string' ? r.text.trim() : '';
      if (!text) continue; // bare "verify" / "finalize" turns: the analyzer bubble says it
      const action = c?.name === 'apply_remediation'
        ? `apply ${String(c.input?.strategy)}${c.input?.params ? ` · ${paramsText(c.input.params as Record<string, unknown>)}` : ''}`
        : c?.name ? c.name.replace(/_/g, ' ') : undefined;
      out.push({ key: r.seq, who: 'model', text: brief(text), action, pivot: lastVerifyFailed && c?.name === 'apply_remediation' });
      if (c?.name === 'apply_remediation') lastVerifyFailed = false;
    } else if (r.kind === 'tool_result' && r.name === 'verify_candidate' && !r.error) {
      const passes = res.passes_for_type === true;
      lastVerifyFailed = !passes;
      out.push({ key: r.seq, who: 'analyzer', tone: passes ? 'pass' : 'fail',
        text: passes ? 'Re-analysed the candidate: no hazard left in this segment.' : `Re-analysed the candidate: ${String(res.reason ?? 'still failing')}.` });
    } else if (r.kind === 'decision' && r.name === 'finalize') {
      out.push({ key: r.seq, who: 'pipeline', tone: r.after_verdict === 'pass' ? 'pass' : 'fail',
        text: `Whole file re-verified: ${r.after_verdict === 'pass' ? 'passes' : 'fails'} · ${String(r.frames_out)} frames · audio and timing kept.` });
    }
  }
  return out;
}

function Conversation({ rec }: { rec: JudgeJob }) {
  const items = useMemo(() => conversation(rec.trace.records), [rec]);
  return (
    <ol className="jx-convo" aria-label="What the model said and what the analyzer answered, in order">
      {items.map((b) => (
        <li key={b.key} className={`jx-msg jx-${b.who}${b.tone ? ` tone-${b.tone}` : ''}${b.pivot ? ' pivot' : ''}`}>
          <span className="jx-avatar" aria-hidden="true">{b.who === 'model' ? 'M' : b.who === 'analyzer' ? 'A' : 'P'}</span>
          <div className="jx-bubble">
            <span className="jx-who">{b.who === 'model' ? 'Model · Amazon Bedrock' : b.who === 'analyzer' ? 'Analyzer · OpenCV 5' : 'Pipeline'}</span>
            {b.pivot && <span className="jx-pivot">Changed its plan because of the failed check</span>}
            <p>{b.text}</p>
            {b.action && <code className="jx-action">→ {b.action}</code>}
          </div>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------- page

function JobLink({ id, navigate, className, children }: { id: string; navigate: (p: string) => void; className?: string; children: ReactNode }) {
  return (
    <a className={className} href={href(`/jobs/${id}`)} onClick={(e) => { e.preventDefault(); navigate(`/jobs/${id}`); }}>
      {children}
    </a>
  );
}

const keyOf = (r: JudgeResult) => (r as JudgeResult & { key?: string }).key;

export function JudgePage({ navigate }: Props) {
  const [index, setIndex] = useState<JudgeIndex | null>(null);
  const [jobs, setJobs] = useState<Record<string, JudgeJob>>({});
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<'jd-adapt' | 'jd-live'>('jd-adapt');
  const [liveBusy, setLiveBusy] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);

  useEffect(() => {
    document.title = 'SteadyFrame · the 90-second tour';
    loadIndex()
      .then(async (ix) => {
        setIndex(ix);
        const loaded = await Promise.all(ix.cases.map(async (c) => [c.id, await loadJudgeJob(c.id)] as const));
        setJobs(Object.fromEntries(loaded));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    return () => { document.title = 'SteadyFrame'; };
  }, []);

  async function runLive() {
    setLiveBusy(true);
    setLiveError(null);
    try {
      const r = await api.jobFromSample({ sample_id: 'sample_strobe_region', profile: 'wcag', policy: 'agent', conservative: false });
      navigate(`/jobs/${r.job_id}`);
    } catch (e) {
      setLiveError(e instanceof Error ? e.message : String(e));
      setLiveBusy(false);
    }
  }

  if (error) return <section className="card"><h1>The tour</h1><p className="alert" role="alert">The recorded jobs did not load ({error}).</p></section>;
  if (!index) return <section className="card"><h1>The tour</h1><p role="status">Loading…</p></section>;

  const live = jobs['jd-live'];
  const adapt = jobs['jd-adapt'];
  const appr = jobs['jd-approval'];
  const g = index.guardrails;
  const R = index.results;
  const stat = (key: string) => R.find((r) => keyOf(r) === key)?.text ?? '–';
  const pending = appr?.job.pending_approvals[0];
  const pendingQ = pending?.options?.[0]?.quality as { ssim_overall?: number } | undefined;

  return (
    <div className="jx">
      {/* ---------------------------------------------------------------- hero */}
      <header className="jx-hero">
        <p className="jx-eyebrow">OpenCV AI Competition 2026 · the 90-second tour</p>
        <h1>
          Find the flashing that can trigger seizures.
          <span className="jx-h1-2"> Fix only that spot. Prove the fix.</span>
        </h1>
        <p className="jx-lede">
          Other checkers answer pass or fail for the whole video. SteadyFrame says <strong>when</strong> and
          <strong> where</strong> the hazard is, repairs just that region, and re-runs the same check on its own repair.
        </p>
        <div className="jx-cta">
          <a className="jx-btn primary" href="#find">Start the tour</a>
          {VIDEO_URL && <a className="jx-btn" href={VIDEO_URL}>Watch the video</a>}
          <a className="jx-btn" href={REPO_URL}>View the code</a>
        </div>
        <ul className="jx-pills" aria-label="How decisions are split">
          <li><Icon name="wrench" /> The model picks the fix</li>
          <li><Icon name="eye" /> The analyzer decides if it worked</li>
          <li><Icon name="stamp" /> A person signs off on anything drastic</li>
        </ul>
        {live?.job.before?.timeline && (
          <figure className="jx-hero-figure">
            <RateChart before={live.job.before.timeline} after={live.job.after?.timeline ?? null}
              segments={live.job.before.segments} duration={live.job.input?.duration_s ?? 10} />
            <figcaption>
              <span className="jx-key before">before</span> <span className="jx-key after">after</span>
              Flashes per second in a recorded job: {live.job.before.segments.length} hazards, at{' '}
              {live.job.before.segments.map((s) => s.peak_flash_rate_hz).join(' and ')} a second, brought under the limit; everything
              outside the flagged regions left untouched.
            </figcaption>
          </figure>
        )}
      </header>

      {/* ---------------------------------------------------------------- stats */}
      <section className="jx-stats" aria-label="Headline results">
        {[
          ['clips', 'synthetic clips judged right'],
          ['iris', "of EA IRIS's own verdicts matched"],
          ['controls', 'seconds of real footage falsely flagged'],
          ['fixed', 'hazards fixed and re-verified'],
          ['guardrails', 'attacks on the agent held'],
        ].map(([k, label]) => (
          <div key={k} className="jx-stat">
            <span className="jx-stat-value">{k === 'guardrails' ? stat(k).split(' ')[0] : stat(k)}</span>
            <span className="jx-stat-label">{label}</span>
          </div>
        ))}
      </section>

      <nav className="jx-nav" aria-label="Tour sections">
        {[['find', 'Find'], ['decide', 'Decide'], ['ask', 'Ask a person'], ['keep', 'Keep'], ['measured', 'Measured'], ['break', 'Break it'], ['try', 'Try it']].map(([id, label], i) => (
          <a key={id} href={`#${id}`}><span>{String(i + 1).padStart(2, '0')}</span> {label}</a>
        ))}
      </nav>

      <p className="jx-recorded">
        Every job on this page is a recording of the deployed worker's own code
        (<code>python -m eval.judge_bundle</code>, recorded {index.generated_at.slice(0, 10)}, OpenCV {index.opencv}
        {index.offline ? ', offline planner' : ', live model on Amazon Bedrock'}). Nothing here plays on its own, and no
        unrepaired clip is included.
      </p>

      {/* ---------------------------------------------------------------- 01 find */}
      {live && (
        <section id="find" className="jx-section" aria-labelledby="find-h">
          <div className="jx-section-head">
            <span className="jx-step">01 · Find</span>
            <h2 id="find-h">Not "fail". Where, when, and how bad.</h2>
            <p>OpenCV 5 measures every frame on a 64×48 grid: luminance swing, flash rate in a sliding one-second window, the area rule, red flashes, and the region on screen.</p>
          </div>
          <div className="jx-finds">
            {(live.job.before?.segments ?? []).map((s) => (
              <article key={s.id} className="jx-find">
                <img src={judgeFile('jd-live', `stills/${s.id}.png`)} width={320} height={240} loading="lazy"
                  alt={`Still frame from ${s.id} with the flagged region outlined`} />
                <div className="jx-find-body">
                  <p className="jx-find-rate"><strong>{s.peak_flash_rate_hz}</strong> flashes / s</p>
                  <dl>
                    <div><dt>swing</dt><dd>{s.max_delta_L.toFixed(2)}</dd></div>
                    <div><dt>where</dt><dd>{where(s)}</dd></div>
                    <div><dt>when</dt><dd>{fmtRange(s.start_s, s.end_s)}</dd></div>
                  </dl>
                </div>
              </article>
            ))}
          </div>
          <div className="jx-panel">
            <HazardTimeline duration={live.job.input?.duration_s ?? 10} before={live.job.before!} after={live.job.after} selectedId={null} onSelect={() => undefined} />
          </div>
          <p className="jx-more"><JobLink id="jd-live" navigate={navigate}>Open the full job page →</JobLink></p>
        </section>
      )}

      {/* ---------------------------------------------------------------- 02 decide */}
      {live && adapt && (
        <section id="decide" className="jx-section" aria-labelledby="decide-h">
          <div className="jx-section-head">
            <span className="jx-step">02 · Decide</span>
            <h2 id="decide-h">The model plans. The analyzer checks. Watch it change its mind.</h2>
            <p>The model never sees a pixel, only the analyzer's numbers. Each candidate fix goes back through the same analyzer that found the problem, and only a verified candidate can be accepted.</p>
          </div>
          <div className="jx-tabs" role="group" aria-label="Choose a recorded run">
            <button type="button" aria-pressed={run === 'jd-adapt'} onClick={() => setRun('jd-adapt')}>Red full-screen strobe: changes its plan</button>
            <button type="button" aria-pressed={run === 'jd-live'} onClick={() => setRun('jd-live')}>Two regions: right first time</button>
          </div>
          <div className="jx-panel jx-convo-panel">
            <Conversation rec={run === 'jd-adapt' ? adapt : live} />
          </div>
          <p className="jx-more"><JobLink id={run} navigate={navigate}>See every tool call in the full trace →</JobLink></p>
        </section>
      )}

      {/* ---------------------------------------------------------------- 03 ask */}
      {appr && (
        <section id="ask" className="jx-section jx-split" aria-labelledby="ask-h">
          <div className="jx-section-head">
            <span className="jx-step">03 · Ask a person</span>
            <h2 id="ask-h">When a fix changes the picture too much, it stops and asks.</h2>
            <p>The job pauses with its state saved. Approve, and it resumes and passes. Reject, and it tries the next strategy and asks again. Both outcomes are real recordings.</p>
          </div>
          {pending && (
            <div className="jx-dialog" role="group" aria-label="The recorded approval request">
              <p className="jx-dialog-title">Approval needed · segment {pending.segment_id}</p>
              <p className="jx-dialog-reason">{pending.reason}</p>
              {pendingQ?.ssim_overall !== undefined && (
                <div className="jx-meter" aria-hidden="true">
                  <div className="jx-meter-fill" style={{ width: `${Math.round(pendingQ.ssim_overall * 100)}%` }} />
                  <div className="jx-meter-mark" style={{ left: '75%' }} />
                </div>
              )}
              <p className="jx-dialog-note">Picture kept (SSIM) {pendingQ?.ssim_overall?.toFixed(3)} · automatic acceptance needs 0.75</p>
              <JobLink id="jd-approval" navigate={navigate} className="jx-btn primary">Open it and decide →</JobLink>
            </div>
          )}
        </section>
      )}

      {/* ---------------------------------------------------------------- 04 keep */}
      {live && (
        <section id="keep" className="jx-section" aria-labelledby="keep-h">
          <div className="jx-section-head">
            <span className="jx-step">04 · Keep</span>
            <h2 id="keep-h">Proof you can hand to a broadcaster, and re-check yourself.</h2>
          </div>
          <div className="jx-tiles">
            <a className="jx-tile" href={judgeFile('jd-live', 'record.html')}>
              <Icon name="doc" /><strong>Verification record</strong>
              <span>File hashes, every threshold applied, each fix and any human decision, plus the UK DPP AS-11 photosensitivity fields.</span>
            </a>
            <div className="jx-tile jx-tile-code">
              <Icon name="terminal" /><strong>Re-check it anywhere</strong>
              <code>steadyframe verify safe.mp4 --record record.json</code>
              <span>Re-hashes the file and re-runs the analyzer. <a href={judgeFile('jd-live', 'record.json')}>Get record.json</a></span>
            </div>
            <a className="jx-tile" href={judgeFile('jd-live', 'hazards.vtt')}>
              <Icon name="captions" /><strong>Viewer warning track</strong>
              <span>WebVTT cues before and during each hazard, for players that show the original.</span>
            </a>
            <a className="jx-tile" href={judgeFile('jd-live', 'safe.mp4')}>
              <Icon name="play" /><strong>The repaired video</strong>
              <span>Verified to pass. Opens in your player; nothing plays here.</span>
            </a>
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- 05 measured */}
      <section id="measured" className="jx-section" aria-labelledby="measured-h">
        <div className="jx-section-head">
          <span className="jx-step">05 · Measured</span>
          <h2 id="measured-h">Every number comes from a script, and the failures are published too.</h2>
        </div>
        <div className="jx-results">
          {R.filter((r) => keyOf(r) !== 'guardrails').map((r) => (
            <a key={r.label} className="jx-result" href={`${REPO_URL}/blob/main/${r.source}`}>
              <span className="jx-result-value">{keyOf(r) === 'cost' ? `$${r.text}` : r.text}</span>
              <span className="jx-result-label">{r.label}</span>
              <span className="jx-result-src">{r.source.split('/').pop()}</span>
            </a>
          ))}
        </div>
        <p className="jx-note">The live agent did worse than the fixed policy on two red clips (more attempts, longer runtime); the report lists every case where it did worse.</p>
      </section>

      {/* ---------------------------------------------------------------- 06 break */}
      {g && (
        <section id="break" className="jx-section" aria-labelledby="break-h">
          <div className="jx-section-head">
            <span className="jx-step">06 · Try to break it</span>
            <h2 id="break-h">A hostile planner tried every shortcut. None got through.</h2>
            <p>Same tools as the model, one attack per run, including instructions hidden in the file name and metadata.</p>
          </div>
          <div className="jx-score">
            <div><span className="jx-score-big">{g.summary.held}/{g.summary.runs}</span><span>attacks held</span></div>
            <div><span className="jx-score-big">{g.summary.false_pass}</span><span>false passes</span></div>
            <div><span className="jx-score-big">{g.summary.refused_calls}</span><span>hostile calls refused</span></div>
          </div>
          <ul className="jx-attacks">
            {g.rows.map((r) => (
              <li key={r.attack} className={r.held ? 'held' : 'broken'}>
                <Icon name={r.held ? 'shield' : 'cross'} />
                <span className="jx-attack-what">{r.what}</span>
                <span className="jx-attack-out">
                  {r.held ? 'Held' : 'NOT HELD'} · {r.status === 'passed'
                    ? 'the open hazard was then fixed properly'
                    : r.status === 'needs_approval' ? 'the job waited for a person' : `job ${r.status.replace('_', ' ')}`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ---------------------------------------------------------------- 07 try */}
      <section id="try" className="jx-section" aria-labelledby="try-h">
        <div className="jx-section-head">
          <span className="jx-step">07 · Try it</span>
          <h2 id="try-h">Run it live on AWS, or on your laptop in three commands.</h2>
        </div>
        <div className="jx-try">
          <div className="jx-try-card">
            <h3>On the live AWS worker</h3>
            <p>Starts a real job: a 6 Hz region strobe, planned by the Bedrock agent on ECS Fargate (Graviton).</p>
            <button type="button" className="jx-btn primary" disabled={liveBusy} onClick={runLive}>
              {liveBusy ? 'Starting…' : 'Run a sample job'}
            </button>
            <p className="jx-fine">An idle worker scales from zero, so the first job can take a few minutes to start. The recordings above need no worker.</p>
            {liveError && <p className="alert" role="alert">{liveError}</p>}
          </div>
          <div className="jx-try-card">
            <h3>On your machine, no credentials</h3>
            <pre className="jx-term" tabIndex={0} aria-label="Commands to run it locally"><code>{`git clone ${REPO_URL}.git
cd SteadyFrame
make install
make demo`}</code></pre>
            <p className="jx-fine">Renders three sample clips, then analyzes, fixes and verifies them in seconds.</p>
          </div>
        </div>
        <ul className="jx-stack" aria-label="Built with">
          {['OpenCV 5', 'Amazon Bedrock', 'ECS on Graviton', 'Lambda', 'API Gateway', 'S3 + CloudFront', 'SQS', 'DynamoDB', 'CloudWatch', 'AWS CDK', 'React'].map((t) => <li key={t}>{t}</li>)}
        </ul>
      </section>

      {/* ---------------------------------------------------------------- limits */}
      <section className="jx-section jx-limits" aria-labelledby="limits-h">
        <h2 id="limits-h">What it does not do</h2>
        <ul>{index.limits.map((l) => <li key={l}>{l}</li>)}</ul>
        <p className="jx-links">
          <a href={`${REPO_URL}/blob/main/docs/report/REPORT.md`}>Technical report</a>
          <a href={`${REPO_URL}/blob/main/docs/JUDGES.md`}>Rubric → evidence map</a>
          <a href={href('/')} onClick={(e) => { e.preventDefault(); navigate('/'); }}>Upload your own clip</a>
        </p>
      </section>
    </div>
  );
}
