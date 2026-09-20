import { STATUS_LABEL, fmtSeconds } from '../format';
import { TERMINAL_STATUSES, type Job } from '../types';

const TONE: Record<Job['status'], string> = {
  created: 'neutral', uploaded: 'neutral', queued: 'neutral', analyzing: 'neutral',
  remediating: 'neutral', rendering: 'neutral', passed: 'pass', no_hazards: 'pass',
  needs_approval: 'warn', failed_verification: 'fail', error: 'fail',
};

export function JobStatusPanel({ job, pollError }: { job: Job; pollError: string | null }) {
  const running = !TERMINAL_STATUSES.has(job.status);
  const frac = job.progress?.fraction ?? (running ? 0 : 1);
  const pct = Math.round(Math.min(1, Math.max(0, frac)) * 100);
  const detail = job.progress?.detail;
  const live = `${STATUS_LABEL[job.status]}${detail ? `: ${detail}` : ''}${running ? ` (${pct}%)` : ''}`;

  return (
    <section className="card" aria-labelledby="status-h">
      <div className="status-head">
        <h2 id="status-h">Status</h2>
        <span className={`badge badge-${TONE[job.status]}`}>{STATUS_LABEL[job.status]}</span>
      </div>
      {/* Screen readers get every status change once, politely. */}
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{live}</p>

      {running && (
        <div className="progress-row">
          <div
            className="progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
            aria-label={`Job progress, stage ${job.progress?.stage ?? job.status}`}
          >
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <p className="progress-text">
            <strong>{pct}%</strong> · {job.progress?.stage ?? job.status}
            {detail ? ` — ${detail}` : ''}
            <span className="muted"> · polling every 2 s</span>
          </p>
        </div>
      )}
      {job.status === 'error' && (
        <p className="alert" role="alert">Job failed: {job.error ?? 'unknown error'}</p>
      )}
      {job.status === 'failed_verification' && (
        <p className="alert">
          Some segments still exceed the thresholds after every strategy in the budget. The report
          lists what was tried; the output video is still available for review.
        </p>
      )}
      {pollError && <p className="alert">Cannot reach the API right now ({pollError}); retrying.</p>}

      <dl className="meta">
        <div><dt>Job</dt><dd><code>{job.job_id}</code></dd></div>
        <div><dt>File</dt><dd>{job.input?.filename ?? '–'}</dd></div>
        <div><dt>Video</dt><dd>
          {job.input?.width ? `${job.input.width}×${job.input.height} · ${job.input.fps} fps · ${fmtSeconds(job.input.duration_s ?? 0, 1)}` : '–'}
          {job.input?.has_audio === false ? ' · no audio' : job.input?.has_audio ? ' · audio' : ''}
        </dd></div>
        <div><dt>Profile</dt><dd>{job.profile}{job.conservative ? ' (conservative)' : ''}</dd></div>
        <div><dt>Policy</dt><dd>{job.policy}</dd></div>
        <div><dt>Engine</dt><dd>steadyframe {job.tool?.version} · OpenCV {job.tool?.opencv}</dd></div>
      </dl>
    </section>
  );
}
