// One check, live or finished: progress, what the planner and the analyzer did, the result,
// an inline approval when the job waits for a person, and the downloads. Nothing plays; the
// clip itself is never shown, only its measurements, still frames and plots.
import { useEffect, useState } from 'react';
import { api } from '../api';
import { fmtRange, paramsText, strategyLabel } from '../format';
import { useJob, useTrace } from '../hooks/useJob';
import { href } from '../hooks/useRoute';
import { flashRate, peak, where } from '../tourData';
import { TERMINAL_STATUSES, type DownloadKind, type Job } from '../types';
import { Conversation, RateChart } from './tour';

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

const STATUS: Record<string, [string, string]> = {
  passed: ['Repaired · passes', 'ok'],
  no_hazards: ['No hazards', 'ok'],
  failed_verification: ['Could not repair', 'bad'],
  needs_approval: ['Needs your decision', 'warn'],
  error: ['Error', 'bad'],
};

/** Seconds since `since`, ticking until `stopped`; then it keeps the last value. */
function Elapsed({ since, stopped }: { since: number; stopped: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (stopped) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [stopped]);
  return <span className="sf-elapsed">{Math.max(0, (now - since) / 1000).toFixed(1)} s</span>;
}

function DownloadButton({ jobId, kind, label }: { jobId: string; kind: DownloadKind; label: string }) {
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
      {label}
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
      <p id="sf-approval-h" className="sf-label">Your decision</p>
      <p className="sf-approval-q">
        The only repair that passes changes the picture a lot. Accept it?
      </p>
      <dl className="sf-facts">
        <div><dt>segment</dt><dd>{pending.segment_id}</dd></div>
        {option && <div><dt>repair</dt><dd>{strategyLabel(option.strategy)}</dd></div>}
        {ssim != null && <div><dt>picture kept</dt><dd>SSIM {ssim.toFixed(3)} (auto-accept needs 0.75)</dd></div>}
      </dl>
      <div className="sf-actions">
        <button type="button" className="sf-btn primary" disabled={busy} onClick={() => decide(true)}>Approve</button>
        <button type="button" className="sf-btn" disabled={busy} onClick={() => decide(false)}>Reject</button>
      </div>
      <p className="sf-fine">Approve resumes the paused job from its saved state. Reject makes it try the next strategy and ask again.</p>
      {error && <p className="alert" role="alert">{error}</p>}
    </div>
  );
}

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

  return (
    <article className="sf-card sf-check" aria-labelledby="sf-check-h">
      <header className="sf-check-head">
        <div>
          <p className="sf-label">{example ? 'Example check (recorded)' : 'Current check'}</p>
          <h2 id="sf-check-h">{label}</h2>
          <p className="sf-meta">
            {job?.policy === 'agent' ? 'Planned by an Amazon Bedrock model' : 'Fixed policy'}
            {' · '}{job?.profile === 'broadcast' ? 'ITU-R BT.1702 / Ofcom' : 'WCAG 2.3.1'}
            {startedAt && <> · <Elapsed since={startedAt} stopped={terminal} /></>}
            {job?.stats?.worker_s ? ` · ${job.stats.worker_s.toFixed(1)} s on the AWS Lambda worker` : ''}
          </p>
        </div>
        {status ? (
          <span className={`sf-status sf-${status[1]}`}>{status[0]}</span>
        ) : (
          <span className="sf-status sf-run">Running</span>
        )}
      </header>

      {!terminal && (
        <>
          <ol className="sf-steps" aria-label="Progress">
            {STEPS.map(([key, name], i) => (
              <li key={key} className={i < idx ? 'done' : i === idx ? 'now' : ''} aria-current={i === idx ? 'step' : undefined}>
                <span className="sf-step-dot" aria-hidden="true">{i < idx ? '✓' : i + 1}</span>{name}
              </li>
            ))}
          </ol>
          <p className="sf-progress" role="status" aria-live="polite">
            {job?.progress?.detail ?? 'Starting…'}
            {job?.status === 'queued' && ' · a worker starts within seconds, up to a minute after a quiet spell'}
          </p>
        </>
      )}
      {error && !job && <p className="alert" role="alert">{error}</p>}

      {job?.status === 'needs_approval' && <Approval job={job} onDecided={refresh} />}

      {job && (job.before || terminal) && (
        <div className="sf-result">
          {job.before && (
            <div className="sf-verdicts" aria-label="Verdicts">
              <span className={`sf-verdict v-${job.before.verdict}`}>Before: {job.before.verdict}</span>
              <span aria-hidden="true">→</span>
              <span className={`sf-verdict v-${job.after?.verdict ?? 'na'}`}>
                After: {job.after?.verdict ?? (job.status === 'needs_approval' ? 'waiting' : terminal ? '–' : '…')}
              </span>
            </div>
          )}
          {job.status === 'no_hazards' && <p className="sf-note">Nothing in this clip breaks the thresholds, so it passes unchanged.</p>}
          {job.status === 'error' && <p className="alert" role="alert">{job.error ?? 'The job failed.'}</p>}

          {tlBefore && segs.length > 0 && (
            <div className="sf-chartbox">
              <p className="sf-label">Flashes per second</p>
              <RateChart before={tlBefore} after={tlAfter} segments={segs} duration={duration} />
              <p className="sf-legend">
                <span className="sf-key before">before</span>
                {tlAfter && <span className="sf-key after">after</span>}
                <span>peak {peak(flashRate(tlBefore)).toFixed(0)}{tlAfter ? ` → ${peak(flashRate(tlAfter)).toFixed(1)}` : ''} · limit 3</span>
              </p>
            </div>
          )}
          {segs.length > 0 && (
            <>
              <p className="sf-label sf-gap">Where and when</p>
              <div className="sf-finds">
                {segs.map((s) => {
                  const fix = fixes.find((f) => f.segment_id === s.id);
                  return (
                    <figure key={s.id} className="sf-find">
                      <img src={api.frameUrl(jobId, s.id)} width={240} height={180} loading="lazy"
                        alt={`Still frame from ${s.id} with the flagged region outlined`} />
                      <figcaption>
                        <strong>{s.peak_flash_rate_hz} flashes/s</strong>
                        <span>{s.type === 'red' ? 'red flash' : 'flash'} · swing {s.max_delta_L.toFixed(2)} · {where(s)}</span>
                        <span>{fmtRange(s.start_s, s.end_s)}</span>
                        {fix?.strategy && (
                          <span className="sf-fix">
                            Repair: {strategyLabel(fix.strategy)}{Object.keys(fix.params ?? {}).length ? `, ${paramsText(fix.params)}` : ''}
                            {fix.quality?.ssim_inside != null ? ` · picture kept ${fix.quality.ssim_inside.toFixed(2)}` : ''}
                          </span>
                        )}
                      </figcaption>
                    </figure>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}

      {records.length > 0 && (
        <details className="sf-log" open={!terminal || job?.policy === 'agent'}>
          <summary><span className="sf-label">What happened</span> <span className="sf-fine">{records.length} trace records</span></summary>
          <div className="sf-log-body" tabIndex={0} role="region" aria-label="What the planner did and what the analyzer answered">
            <Conversation records={records} live={!terminal} />
          </div>
        </details>
      )}

      {job && terminal && (
        <div className="sf-downloads">
          {job.downloads?.record && <DownloadButton jobId={jobId} kind="record" label="Verification record" />}
          {job.downloads?.video && <DownloadButton jobId={jobId} kind="video" label={job.status === 'no_hazards' ? 'Output video' : 'Repaired video'} />}
          {job.downloads?.warnings && <DownloadButton jobId={jobId} kind="warnings" label="Viewer warning track" />}
          {job.downloads?.report && <DownloadButton jobId={jobId} kind="report" label="Report (JSON)" />}
          <a className="sf-chip" href={href(`/jobs/${jobId}`)} onClick={(e) => { e.preventDefault(); navigate(`/jobs/${jobId}`); }}>Full details</a>
        </div>
      )}
    </article>
  );
}
