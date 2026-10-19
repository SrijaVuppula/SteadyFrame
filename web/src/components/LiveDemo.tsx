// The live demo at the top of /judge: pick a clip, press Run, and watch a real job on the
// deployed AWS worker: the plan, each re-check and the result, as they happen. Nothing plays;
// the clip itself is never shown, only the measurements, stills and plots it produces.
import { useEffect, useState } from 'react';
import { api } from '../api';
import { useJob, useTrace } from '../hooks/useJob';
import { href } from '../hooks/useRoute';
import { fmtRange } from '../format';
import { TERMINAL_STATUSES, type DownloadKind, type Job, type Policy } from '../types';
import { flashRate, peak, where } from '../tourData';
import { Conversation, Icon, RateChart } from './tour';

const CLIPS = [
  { id: 'sample_strobe_region', name: 'Flashing box', blurb: '6 flashes a second in the middle of the frame' },
  { id: 'sample_red_strobe', name: 'Red strobe', blurb: 'a saturated red flash plus a general one' },
  { id: 'sample_clean', name: 'Calm clip', blurb: 'the control: nothing should be flagged' },
];

const STEPS: Array<[string, string]> = [
  ['queued', 'Worker'],
  ['analyzing', 'Analyze'],
  ['remediating', 'Fix'],
  ['rendering', 'Re-verify'],
  ['done', 'Result'],
];

function stepIndex(status: Job['status']): number {
  if (status === 'created' || status === 'uploaded' || status === 'queued') return 0;
  if (status === 'analyzing') return 1;
  if (status === 'remediating') return 2;
  if (status === 'rendering') return 3;
  return 4;
}

/** Seconds since `since`, ticking until `stopped`; then it keeps the last value. */
function Elapsed({ since, stopped }: { since: number; stopped: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (stopped) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [stopped]);
  return <span className="jx-elapsed">{Math.max(0, (now - since) / 1000).toFixed(1)} s</span>;
}

function DownloadButton({ jobId, kind, label }: { jobId: string; kind: DownloadKind; label: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className="jx-btn" disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        const r = await api.downloadUrl(jobId, kind);
        window.open(r.url, '_blank', 'noopener');
      } finally {
        setBusy(false);
      }
    }}>
      {label}
    </button>
  );
}

function LiveRun({ jobId, startedAt, navigate, onReset }: { jobId: string; startedAt: number; navigate: (p: string) => void; onReset: () => void }) {
  const { job, error } = useJob(jobId);
  const { records } = useTrace(jobId, job?.status);
  const terminal = !!job && TERMINAL_STATUSES.has(job.status);
  const idx = job ? stepIndex(job.status) : 0;
  const segs = job?.before?.segments ?? [];
  const tlBefore = job?.before?.timeline;
  const tlAfter = job?.after?.timeline ?? null;
  const duration = job?.input?.duration_s ?? 5;

  return (
    <div className="jx-live-run">
      <ol className="jx-stepper" aria-label="Job progress">
        {STEPS.map(([key, label], i) => (
          <li key={key} className={i < idx || (terminal && i === idx) ? 'done' : i === idx ? 'now' : ''} aria-current={i === idx && !terminal ? 'step' : undefined}>
            <span className="jx-step-dot" aria-hidden="true">{i < idx || (terminal && i === idx) ? '✓' : i + 1}</span>
            {label}
          </li>
        ))}
      </ol>
      <p className="jx-live-status" role="status" aria-live="polite">
        {job ? (job.progress?.detail || job.status.replace('_', ' ')) : 'Creating the job…'}
        {' · '}
        <Elapsed since={startedAt} stopped={terminal} />
        {job?.status === 'queued' && ' · the first job after a quiet spell waits for a worker to start'}
      </p>
      {error && !job && <p className="alert" role="alert">{error}</p>}

      {records.length > 0 && (
        <div className="jx-live-convo">
          <Conversation records={records} live={!terminal} />
        </div>
      )}

      {job && terminal && (
        <div className="jx-live-result">
          <div className="jx-verdicts">
            <span className={`jx-verdict v-${job.before?.verdict ?? 'na'}`}>Before: {job.before?.verdict ?? '–'}</span>
            <span className="jx-arrow" aria-hidden="true">→</span>
            <span className={`jx-verdict v-${job.after?.verdict ?? 'na'}`}>After: {job.after?.verdict ?? (job.status === 'needs_approval' ? 'waiting for you' : '–')}</span>
            <span className="jx-result-time">
              {job.stats?.worker_s ? `${job.stats.worker_s.toFixed(1)} s of worker time` : 'done'} on AWS Lambda (Graviton)
            </span>
          </div>
          {job.status === 'no_hazards' && <p>Nothing in this clip breaks the thresholds, so it passes unchanged. That is the control working.</p>}
          {job.status === 'needs_approval' && (
            <p>The only fix that passes changes the picture a lot, so it is waiting for a person.{' '}
              <a href={href(`/jobs/${jobId}`)} onClick={(e) => { e.preventDefault(); navigate(`/jobs/${jobId}`); }}>Decide on the job page →</a></p>
          )}
          {job.status === 'error' && <p className="alert" role="alert">{job.error ?? 'The job failed.'}</p>}
          {tlBefore && segs.length > 0 && (
            <div className="jx-live-chart">
              <RateChart before={tlBefore} after={tlAfter} segments={segs} duration={duration} />
              <p className="jx-chart-caption"><span className="jx-key before">before</span> <span className="jx-key after">after</span>
                Peak {peak(flashRate(tlBefore)).toFixed(0)} flashes a second before{tlAfter ? `, ${peak(flashRate(tlAfter)).toFixed(1)} after` : ''}; the limit is 3.</p>
            </div>
          )}
          {segs.length > 0 && (
            <div className="jx-live-finds">
              {segs.map((s) => (
                <figure key={s.id} className="jx-live-find">
                  <img src={api.frameUrl(jobId, s.id)} width={240} height={180} alt={`Still frame from ${s.id} with the flagged region outlined`} />
                  <figcaption><strong>{s.peak_flash_rate_hz} / s</strong> · {s.type === 'red' ? 'red flash' : 'flash'} · {where(s)} · {fmtRange(s.start_s, s.end_s)}</figcaption>
                </figure>
              ))}
            </div>
          )}
          <div className="jx-cta">
            {job.downloads?.record && <DownloadButton jobId={jobId} kind="record" label="Verification record" />}
            {job.downloads?.video && <DownloadButton jobId={jobId} kind="video" label={job.status === 'no_hazards' ? 'Output (unchanged)' : 'Repaired video'} />}
            {job.downloads?.warnings && <DownloadButton jobId={jobId} kind="warnings" label="Warning track" />}
            <a className="jx-btn" href={href(`/jobs/${jobId}`)} onClick={(e) => { e.preventDefault(); navigate(`/jobs/${jobId}`); }}>Full job page</a>
            <button type="button" className="jx-btn" onClick={onReset}>Run another</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function LiveDemo({ navigate }: { navigate: (p: string) => void }) {
  const [clip, setClip] = useState(CLIPS[0].id);
  const [policy, setPolicy] = useState<Policy>('agent');
  const [run, setRun] = useState<{ jobId: string; startedAt: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    const t0 = Date.now();
    try {
      const r = await api.jobFromSample({ sample_id: clip, profile: 'wcag', policy, conservative: false });
      setRun({ jobId: r.job_id, startedAt: t0 });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="jx-live" aria-labelledby="live-h">
      <div className="jx-live-head">
        <span className="jx-live-badge"><Icon name="bolt" /> Live</span>
        <h2 id="live-h">Run it now: a real job on AWS</h2>
        <p>Pick a test clip and press Run. The deployed worker analyzes it with OpenCV 5, repairs what it finds and re-checks its own repair, here, while you watch. Usually 5 to 40 seconds.</p>
      </div>
      {!run ? (
        <>
          <fieldset className="jx-clips">
            <legend>Clip</legend>
            {CLIPS.map((c) => (
              <label key={c.id} className={`jx-clip${clip === c.id ? ' on' : ''}`}>
                <input type="radio" name="clip" value={c.id} checked={clip === c.id} onChange={() => setClip(c.id)} />
                <strong>{c.name}</strong>
                <span>{c.blurb}</span>
              </label>
            ))}
          </fieldset>
          <fieldset className="jx-planner">
            <legend>Who plans the repair</legend>
            <label><input type="radio" name="planner" checked={policy === 'agent'} onChange={() => setPolicy('agent')} /> Amazon Bedrock model <span className="jx-fine">(you see it think, about 30 s)</span></label>
            <label><input type="radio" name="planner" checked={policy === 'fixed'} onChange={() => setPolicy('fixed')} /> Fixed policy <span className="jx-fine">(no model, a few seconds)</span></label>
          </fieldset>
          <button type="button" className="jx-btn primary jx-run" disabled={busy} onClick={start}>
            {busy ? 'Starting…' : 'Run live check'}
          </button>
          <p className="jx-fine">The clips are rendered by the project's own test generator. Nothing plays on this page; you see measurements, still frames and plots.</p>
          {error && <p className="alert" role="alert">Could not start the job: {error}</p>}
        </>
      ) : (
        <LiveRun key={run.jobId} jobId={run.jobId} startedAt={run.startedAt} navigate={navigate} onReset={() => setRun(null)} />
      )}
    </section>
  );
}
