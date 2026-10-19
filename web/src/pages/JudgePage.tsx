// /judge: a stranger's 90-second path through the product. Everything on it is a recording
// of the worker's real outputs (eval/judge_bundle.py) or a number read from the frozen
// evaluation results; it needs no account, no upload and no running worker.
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../api';
import { HazardTimeline } from '../components/HazardTimeline';
import { HAZARD_LABEL, fmtRange, paramsText } from '../format';
import { href } from '../hooks/useRoute';
import { REPO_URL, VIDEO_URL, judgeFile, loadIndex, loadJudgeJob, type JudgeIndex, type JudgeJob } from '../judge';
import type { Segment, TraceRecord } from '../types';

interface Props {
  navigate: (path: string) => void;
}

function where(s: Segment): string {
  const r = s.regions;
  if (!r.length) return 'on screen';
  const x0 = Math.min(...r.map((q) => q.x)), y0 = Math.min(...r.map((q) => q.y));
  const x1 = Math.max(...r.map((q) => q.x + q.w)), y1 = Math.max(...r.map((q) => q.y + q.h));
  if ((x1 - x0) * (y1 - y0) >= 0.8) return 'most of the screen';
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const col = cx < 1 / 3 ? 'left' : cx > 2 / 3 ? 'right' : '';
  const row = cy < 1 / 3 ? 'top' : cy > 2 / 3 ? 'bottom' : '';
  return !col && !row ? 'centre of the screen' : `${row}${row && col ? '-' : ''}${col} of the screen`;
}

interface Line {
  key: number;
  who: 'model' | 'analyzer' | 'tool' | 'decision';
  text: string;
  tone?: 'pass' | 'fail' | 'info';
}

/** The decision chain of a trace, in words: what the model said and did, what the analyzer answered. */
function chain(records: TraceRecord[]): Line[] {
  const out: Line[] = [];
  for (const r of records) {
    const res = (r.result ?? {}) as Record<string, unknown>;
    const args = (r.args ?? {}) as Record<string, unknown>;
    if (r.kind === 'model') {
      const calls = (Array.isArray(r.tool_calls) ? r.tool_calls : []) as { name?: string; input?: Record<string, unknown> }[];
      const call = calls[0];
      const text = typeof r.text === 'string' ? r.text.trim() : '';
      const action = call?.name === 'apply_remediation'
        ? `apply ${String(call.input?.strategy)} to ${String(call.input?.segment_id)}${call.input?.params ? ` (${paramsText(call.input.params as Record<string, unknown>)})` : ''}`
        : call?.name ? call.name.replace(/_/g, ' ') : '';
      if (!text && ['verify_candidate', 'finalize'].includes(call?.name ?? '')) continue;
      out.push({ key: r.seq, who: 'model', text: `${text}${text && action ? ' → ' : ''}${action}` });
    } else if (r.kind === 'tool_result' && r.name === 'verify_candidate' && !r.error) {
      const passes = res.passes_for_type === true;
      const appr = res.requires_approval === true;
      out.push({ key: r.seq, who: 'analyzer', tone: passes ? 'pass' : 'fail',
        text: `re-analysed ${String(res.candidate_id ?? args.candidate_id)}: ${String(res.reason ?? (passes ? 'passes' : 'still failing'))}${appr ? ' (needs a person to approve)' : ''}` });
    } else if (r.kind === 'tool_result' && r.error && r.by !== 'policy') {
      out.push({ key: r.seq, who: 'tool', tone: 'fail', text: `${r.name} refused: ${r.error}` });
    } else if (r.kind === 'tool_call' && r.by !== 'model' && r.name === 'apply_remediation') {
      out.push({ key: r.seq, who: 'tool', text: `policy applies ${String(args.strategy)} to ${String(args.segment_id)}` });
    } else if (r.kind === 'decision' && ['accept', 'paused', 'finalize', 'fallback', 'human_approval'].includes(r.name)) {
      const text =
        r.name === 'accept' ? `accepted ${String(r.candidate_id)} (${String(r.strategy)})`
        : r.name === 'paused' ? `job paused for a person: ${String(r.reason)}`
        : r.name === 'finalize' ? `whole file re-verified: ${String(r.after_verdict)}, ${String(r.frames_out)} frames, sync ${r.sync_ok ? 'ok' : 'off'}`
        : r.name === 'fallback' ? `fallback to the fixed policy: ${String(r.reason)}`
        : `human decision: ${(r.decision as { approved?: boolean })?.approved ? 'approved' : 'rejected'}`;
      out.push({ key: r.seq, who: 'decision', text, tone: r.name === 'finalize' ? (r.after_verdict === 'pass' ? 'pass' : 'fail') : 'info' });
    }
  }
  return out;
}

function Chain({ rec }: { rec: JudgeJob }) {
  const lines = useMemo(() => chain(rec.trace.records), [rec]);
  return (
    <ol className="chain" aria-label="Decisions in order">
      {lines.map((l) => (
        <li key={l.key} className={`chain-${l.who}${l.tone ? ` tone-${l.tone}` : ''}`}>
          <span className="chain-who">{l.who === 'model' ? 'Model' : l.who === 'analyzer' ? 'Analyzer' : l.who === 'tool' ? 'Tools' : 'Pipeline'}</span>
          <span className="chain-text">{l.text}</span>
        </li>
      ))}
    </ol>
  );
}

function JobLink({ id, navigate, children }: { id: string; navigate: (p: string) => void; children: ReactNode }) {
  return (
    <a href={href(`/jobs/${id}`)} onClick={(e) => { e.preventDefault(); navigate(`/jobs/${id}`); }}>
      {children}
    </a>
  );
}

export function JudgePage({ navigate }: Props) {
  const [index, setIndex] = useState<JudgeIndex | null>(null);
  const [jobs, setJobs] = useState<Record<string, JudgeJob>>({});
  const [error, setError] = useState<string | null>(null);
  const [liveBusy, setLiveBusy] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);

  useEffect(() => {
    document.title = 'SteadyFrame · for judges';
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

  if (error) {
    return <section className="card"><h1>For judges</h1><p className="alert" role="alert">The recorded jobs did not load ({error}).</p></section>;
  }
  if (!index) return <section className="card"><h1>For judges</h1><p role="status">Loading…</p></section>;

  const live = jobs['jd-live'];
  const adapt = jobs['jd-adapt'];
  const appr = jobs['jd-approval'];
  const caseOf = (id: string) => index.cases.find((c) => c.id === id);
  const g = index.guardrails;

  return (
    <div className="judge">
      <h1>SteadyFrame in 90 seconds</h1>
      <p className="lede">
        Flashing video can trigger seizures in people with photosensitive epilepsy. Existing checkers
        answer pass or fail for the whole file. SteadyFrame says <em>when</em> and <em>where</em> each
        hazard is, repairs only that part, and re-runs the same check on its own repair.
      </p>
      <p className="claim"><strong>The model picks the fix. The analyzer decides whether it worked. A person signs off on anything drastic.</strong></p>
      <p className="judge-links">
        {VIDEO_URL && <><a href={VIDEO_URL}>Video (5 min)</a> · </>}
        <a href={REPO_URL}>Code</a> · <a href={`${REPO_URL}/blob/main/docs/report/REPORT.md`}>Technical report</a> ·{' '}
        <a href={`${REPO_URL}/blob/main/docs/JUDGES.md`}>Rubric → evidence map</a> ·{' '}
        <a href={href('/')} onClick={(e) => { e.preventDefault(); navigate('/'); }}>Upload your own clip</a>
      </p>
      <p className="muted small">
        Every job below is a recording of the deployed worker's code run on a test clip
        (<code>python -m eval.judge_bundle</code>, recorded {index.generated_at.slice(0, 10)}, OpenCV {index.opencv}
        {index.offline ? ', offline planner' : ', live model on Amazon Bedrock'}). Nothing on this page plays on its own,
        and no unrepaired clip is included: hazards are shown as stills and plots.
      </p>

      {live && (
        <section className="card" aria-labelledby="j1">
          <h2 id="j1"><span className="step">1</span> What it found</h2>
          <p>{caseOf('jd-live')?.blurb}</p>
          <HazardTimeline duration={live.job.input?.duration_s ?? 10} before={live.job.before!} after={live.job.after} selectedId={null} onSelect={() => undefined} />
          <div className="judge-stills">
            {(live.job.before?.segments ?? []).map((s) => (
              <figure key={s.id} className="still">
                <img src={judgeFile('jd-live', `stills/${s.id}.png`)} width={320} alt={`Still frame from ${s.id} with the flagged region outlined`} loading="lazy" />
                <figcaption className="small">
                  <strong>{s.peak_flash_rate_hz} flashes a second</strong>, swing {s.max_delta_L.toFixed(2)}, {where(s)},{' '}
                  {fmtRange(s.start_s, s.end_s)} · {HAZARD_LABEL[s.type]}
                </figcaption>
              </figure>
            ))}
          </div>
          <p className="small"><JobLink id="jd-live" navigate={navigate}>Open the full job page</JobLink> (timeline, luminance plots, region series, trace).</p>
        </section>
      )}

      {live && adapt && (
        <section className="card" aria-labelledby="j2">
          <h2 id="j2"><span className="step">2</span> How it decided</h2>
          <p className="muted small">
            The model sees only the analyzer's numbers, never pixels. Each line is from the recorded trace.
          </p>
          <div className="two-col judge-chains">
            <div>
              <h3>{caseOf('jd-live')?.title}</h3>
              <Chain rec={live} />
              <p className="small"><JobLink id="jd-live" navigate={navigate}>Full trace</JobLink></p>
            </div>
            <div>
              <h3>{caseOf('jd-adapt')?.title}</h3>
              <p className="small">{caseOf('jd-adapt')?.blurb}</p>
              <Chain rec={adapt} />
              <p className="small"><JobLink id="jd-adapt" navigate={navigate}>Full trace</JobLink></p>
            </div>
          </div>
        </section>
      )}

      {appr && (
        <section className="card" aria-labelledby="j3">
          <h2 id="j3"><span className="step">3</span> When it stops and asks</h2>
          <p>{caseOf('jd-approval')?.blurb}</p>
          {appr.job.pending_approvals[0] && (
            <p className="approval-quote">
              Segment <code>{appr.job.pending_approvals[0].segment_id}</code>: {appr.job.pending_approvals[0].reason}.
            </p>
          )}
          <p>
            <JobLink id="jd-approval" navigate={navigate}>Open the paused job and decide</JobLink>. Approve and it
            resumes from its saved state and passes; reject and it tries the next strategy and asks again. Both
            outcomes are recordings of the real resume.
          </p>
        </section>
      )}

      {live && (
        <section className="card" aria-labelledby="j4">
          <h2 id="j4"><span className="step">4</span> What you can keep</h2>
          <ul className="keep">
            <li><a href={judgeFile('jd-live', 'record.html')}>Verification record</a> (printable): SHA-256 of input and output, every threshold applied, each segment and its fix, any human decision, and the delivery fields in the shape of the UK DPP's AS-11 PSE metadata.</li>
            <li><a href={judgeFile('jd-live', 'record.json')}>The same record as JSON</a>. Anyone can check it on their own machine: <code>steadyframe verify safe.mp4 --record record.json</code> re-hashes the file and re-runs the analyzer.</li>
            <li><a href={judgeFile('jd-live', 'hazards.vtt')}>Viewer warning track</a> (WebVTT): a cue before and during each hazard, for players that show the original.</li>
            <li><a href={judgeFile('jd-live', 'safe.mp4')}>The repaired video</a> (verified; opens in a new player, does not autoplay here).</li>
          </ul>
        </section>
      )}

      <section className="card" aria-labelledby="j5">
        <h2 id="j5"><span className="step">5</span> What was measured</h2>
        <div className="table-wrap" tabIndex={0}>
          <table className="data">
            <caption className="sr-only">Headline results, each read from a frozen results file</caption>
            <thead><tr><th scope="col">Measure</th><th scope="col">Result</th><th scope="col">Source</th></tr></thead>
            <tbody>
              {index.results.map((r) => (
                <tr key={r.label}><td>{r.label}</td><td><strong>{r.text}</strong></td><td><a href={`${REPO_URL}/blob/main/${r.source}`}>{r.source.split('/').pop()}</a></td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">The live agent is worse than the fixed policy on two red clips in attempts and runtime; the report lists every case where it did worse.</p>
      </section>

      {g && (
        <section className="card" aria-labelledby="j6">
          <h2 id="j6"><span className="step">6</span> Try to break it</h2>
          <p>
            A hostile planner speaks the same tool protocol as the model and tries one shortcut per run.{' '}
            <strong>{g.summary.held}/{g.summary.runs} held, {g.summary.false_pass} false passes</strong>, {g.summary.refused_calls} hostile calls refused.
          </p>
          <div className="table-wrap" tabIndex={0}>
            <table className="data">
              <caption className="sr-only">Adversarial planner runs</caption>
              <thead><tr><th scope="col">Attack</th><th scope="col">Refused</th><th scope="col">Job status</th><th scope="col">Held</th></tr></thead>
              <tbody>
                {g.rows.map((r) => (
                  <tr key={r.attack}><td>{r.what}</td><td><code>{r.refused}</code></td><td>{r.status.replace('_', ' ')}</td><td>{r.held ? 'yes' : 'NO'}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="card" aria-labelledby="j7">
        <h2 id="j7"><span className="step">7</span> Run it yourself</h2>
        <div className="actions">
          <button type="button" className="btn primary" disabled={liveBusy} onClick={runLive}>
            {liveBusy ? 'Starting…' : 'Run a sample on the live AWS worker'}
          </button>
        </div>
        <p className="muted small">
          Starts a real job (6 Hz region strobe, Bedrock agent) on ECS Fargate. If the worker has been idle it
          scales from zero, so the first job can wait a few minutes; the recordings above need no worker.
        </p>
        {liveError && <p className="alert" role="alert">{liveError}</p>}
        <p>On your own machine, no credentials or cloud account:</p>
        <pre className="cmd" tabIndex={0} aria-label="Commands to run it locally"><code>{`git clone ${REPO_URL}.git && cd SteadyFrame
make install
make demo`}</code></pre>
      </section>

      <section className="card" aria-labelledby="j8">
        <h2 id="j8"><span className="step">8</span> What it does not do</h2>
        <ul>{index.limits.map((l) => <li key={l}>{l}</li>)}</ul>
      </section>
    </div>
  );
}
