// One check, live or finished: progress as a film strip, the before/after stamps, the chart,
// where it flashed, an inline approval when the job waits for a person, how it got there and
// the downloads. Nothing plays; the clip is shown only as measurements, stills and plots.
import { useEffect, useState } from 'react';
import { api } from '../api';
import { STRATEGY_NAME, fmtRange, paramsText } from '../format';
import { useJob, useTrace } from '../hooks/useJob';
import { href } from '../hooks/useRoute';
import { where } from '../tourData';
import { TERMINAL_STATUSES, type DownloadKind, type Job } from '../types';
import { Reel } from './art';
import { Conversation, Icon, RateChart, type IconName } from './tour';

const STEPS: Array<[string, string]> = [
  ['queued', 'Worker'],
  ['analyzing', 'Analyze'],
  ['remediating', 'Repair'],
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

// Terminal status, as read out to screen readers.
const STATUS: Record<string, string> = {
  passed: 'Repaired and passes',
  no_hazards: 'No hazards found',
  failed_verification: 'Could not repair within budget',
  needs_approval: 'Waiting for your decision',
  error: 'Error',
};

/** Seconds since `since`, ticking until `stopped`; then it keeps the last value. */
function Elapsed({ since, stopped }: { since: number; stopped: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (stopped) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [stopped]);
  return <>{Math.max(0, (now - since) / 1000).toFixed(1)}</>;
}

function DownloadButton({ jobId, kind, label, icon }: { jobId: string; kind: DownloadKind; label: string; icon: IconName }) {
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className="sf-chip" disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        const r = await api.downloadUrl(jobId, kind);
        window.open(r.url, '_blank', 'noopener');
      } finally {
        setBusy(false);
      }
    }}>
      <Icon name={icon} />{label}
    </button>
  );
}

function Approval({ job, onDecided }: { job: Job; onDecided: () => void }) {
  const pending = job.pending_approvals?.[0];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!pending) return null;
  const option = pending.options?.[0];
  const ssim = option?.quality?.ssim_overall;
  async function decide(approved: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.approve(job.job_id, { segment_id: pending!.segment_id, approved, candidate_id: option?.candidate_id });
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="sf-approval" role="group" aria-labelledby="sf-approval-h">
      <p id="sf-approval-h" className="sf-approval-q">Your call</p>
      <p className="sf-approval-why">
        The only fix that passes changes the picture a lot
        {ssim != null && <> (SSIM <strong>{ssim.toFixed(3)}</strong>; auto-accept needs 0.75)</>}.
      </p>
      <div className="sf-actions">
        <button type="button" className="sf-btn primary" disabled={busy} onClick={() => decide(true)}>Approve</button>
        <button type="button" className="sf-btn" disabled={busy} onClick={() => decide(false)}>Reject</button>
      </div>
      {error && <p className="alert" role="alert">{error}</p>}
    </div>
  );
}

function Stamp({ label, verdict, tone }: { label: string; verdict: string; tone: string }) {
  return (
    <span className={`sf-stamp t-${tone}`}>
      <span className="sf-stamp-k">{label}</span>
      <span className="sf-stamp-v">{verdict}</span>
    </span>
  );
}

const TONE: Record<string, string> = { pass: 'ok', warn: 'warn', fail: 'bad' };

interface Props {
  jobId: string;
  label: string;
  startedAt?: number;
  example?: boolean;
  navigate: (p: string) => void;
  onStatus?: (jobId: string, status: string) => void;
}

export function CheckView({ jobId, label, startedAt, example, navigate, onStatus }: Props) {
  const { job, error, refresh } = useJob(jobId);
  const { records } = useTrace(jobId, job?.status);
  const terminal = !!job && TERMINAL_STATUSES.has(job.status);
  useEffect(() => {
    if (job && TERMINAL_STATUSES.has(job.status)) onStatus?.(jobId, job.status);
  }, [job, jobId, onStatus]);

  const idx = job ? stepIndex(job.status) : 0;
  const segs = job?.before?.segments ?? [];
  const tlBefore = job?.before?.timeline;
  const tlAfter = job?.after?.timeline ?? null;
  const duration = job?.input?.duration_s ?? 5;
  const status = job ? STATUS[job.status] : undefined;
  const fixes = job?.remediation?.segments ?? [];

  const seconds = startedAt ? null : job?.stats?.worker_s;
  const afterStamp: [string, string] | null = !job?.before ? null
    : job.after ? [job.after.verdict, TONE[job.after.verdict] ?? 'na']
    : job.status === 'needs_approval' ? ['your call', 'warn']
    : job.status === 'no_hazards' ? ['unchanged', 'ok']
    : terminal ? ['-', 'na'] : ['…', 'na'];

  return (
    <article className="sf-card sf-check" aria-labelledby="sf-check-h">
      <header className="sf-check-head">
        <div>
          <p className="sf-label"><Reel spinning={!!job && !terminal} /> {example ? 'Now showing · a recorded run' : 'Now showing'}</p>
          <h2 id="sf-check-h">{label}</h2>
          <p className="sf-meta">
            {job?.policy === 'agent' ? 'Bedrock model' : 'Fixed policy'}
            {' · '}{job?.profile === 'broadcast' ? 'Broadcast (BT.1702)' : 'WCAG 2.3.1'}
          </p>
        </div>
        {(startedAt || seconds) && (
          <p className="sf-counter" aria-label="Time taken">
            <span className="sf-counter-n">{startedAt ? <Elapsed since={startedAt} stopped={terminal} /> : seconds!.toFixed(1)}</span>
            <span className="sf-counter-u">{startedAt ? 'seconds' : 's on AWS Lambda'}</span>
          </p>
        )}
      </header>
      {job?.notice && <p className="sf-notice" role="note">{job.notice}</p>}
      <p className="sr-only" role="status" aria-live="polite">{status ?? job?.progress?.detail ?? 'Starting'}</p>

      {!terminal && (
        <>
          <ol className="sf-strip" aria-label="Progress">
            {STEPS.map(([key, name], i) => (
              <li key={key} className={i < idx ? 'done' : i === idx ? 'now' : ''} aria-current={i === idx ? 'step' : undefined}>
                <span className="sf-strip-n" aria-hidden="true">{i < idx ? '✓' : i + 1}</span>
                <span className="sf-strip-name">{name}</span>
              </li>
            ))}
          </ol>
          <p className="sf-progress">
            {job?.progress?.detail ?? 'Starting…'}
          </p>
        </>
      )}
      {error && !job && <p className="alert" role="alert">{error}</p>}

      {job?.status === 'needs_approval' && <Approval job={job} onDecided={refresh} />}

      {job && (job.before || terminal) && (
        <div className="sf-result">
          {job.before && afterStamp && (
            <div className="sf-verdicts">
              <Stamp label="Before" verdict={job.before.verdict} tone={TONE[job.before.verdict] ?? 'na'} />
              <Icon name="arrow" />
              <Stamp label="After" verdict={afterStamp[0]} tone={afterStamp[1]} />
            </div>
          )}
          {job.status === 'error' && <p className="alert" role="alert">{job.error ?? 'The job failed.'}</p>}

          {tlBefore && segs.length > 0 && (
            <figure className="sf-chartbox">
              <figcaption className="sf-chart-head">
                <span className="sf-label">Flashes per second</span>
                <span className="sf-legend">
                  <span className="sf-key before">before</span>
                  {tlAfter && <span className="sf-key after">after</span>}
                  <span className="sf-key limit">limit 3</span>
                </span>
              </figcaption>
              <RateChart before={tlBefore} after={tlAfter} segments={segs} duration={duration} />
            </figure>
          )}
          {segs.length > 0 && (
            <div className="sf-finds">
              {segs.map((s) => {
                const fix = fixes.find((f) => f.segment_id === s.id);
                return (
                  <figure key={s.id} className="sf-find">
                    <img src={api.frameUrl(jobId, s.id)} width={240} height={180} loading="lazy"
                      alt={`Still frame from ${s.id} with the flagged region outlined`} />
                    <figcaption>
                      <strong>{s.peak_flash_rate_hz}<small> flashes/s</small></strong>
                      <span>{s.type === 'red' ? 'red · ' : ''}{where(s)} · {fmtRange(s.start_s, s.end_s)}</span>
                      {fix?.strategy && (
                        <span className="sf-fix" title={Object.keys(fix.params ?? {}).length ? paramsText(fix.params) : undefined}>
                          Fixed with {STRATEGY_NAME[fix.strategy] ?? fix.strategy}
                          {fix.quality?.ssim_inside != null ? <span className="sf-ssim">SSIM {fix.quality.ssim_inside.toFixed(2)}</span> : null}
                        </span>
                      )}
                    </figcaption>
                  </figure>
                );
              })}
            </div>
          )}
        </div>
      )}

      {records.length > 0 && (
        <details className="sf-log" open={!terminal}>
          <summary>
            <span className="sf-log-title">How it got there</span>
            <span className="sf-fine">{job?.policy === 'agent' ? 'the model and the analyzer, step by step' : 'the policy and the analyzer, step by step'}</span>
          </summary>
          <div className="sf-log-body" tabIndex={0} role="region" aria-label="What the planner did and what the analyzer answered">
            <Conversation records={records} live={!terminal} />
          </div>
        </details>
      )}

      {job && terminal && (
        <div className="sf-downloads">
          {job.downloads?.record && <DownloadButton jobId={jobId} kind="record" icon="stamp" label="Verification record" />}
          {job.downloads?.video && <DownloadButton jobId={jobId} kind="video" icon="play" label={job.status === 'no_hazards' ? 'Video' : 'Repaired video'} />}
          {job.downloads?.warnings && <DownloadButton jobId={jobId} kind="warnings" icon="captions" label="Warning track" />}
          {job.downloads?.report && <DownloadButton jobId={jobId} kind="report" icon="braces" label="JSON" />}
          <a className="sf-chip sf-chip-link" href={href(`/jobs/${jobId}`)} onClick={(e) => { e.preventDefault(); navigate(`/jobs/${jobId}`); }}>Full details <Icon name="arrow" /></a>
        </div>
      )}
    </article>
  );
}
