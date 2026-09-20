import { useEffect, useMemo, useState } from 'react';
import type { RemediationSegment, Segment, SegmentDetail } from '../types';
import { ApprovalDialog } from '../components/ApprovalDialog';
import { Downloads } from '../components/Downloads';
import { HazardTimeline } from '../components/HazardTimeline';
import { JobStatusPanel } from '../components/JobStatusPanel';
import { LuminancePlot } from '../components/LuminancePlot';
import { OriginalPreview } from '../components/OriginalPreview';
import { RemediatedPreview } from '../components/RemediatedPreview';
import { RemediationSummary } from '../components/RemediationSummary';
import { SegmentInspector } from '../components/SegmentInspector';
import { TraceViewer } from '../components/TraceViewer';
import { useJob, useSegments, useTrace } from '../hooks/useJob';
import { href } from '../hooks/useRoute';

interface Props {
  jobId: string;
  navigate: (path: string) => void;
}

export function JobPage({ jobId, navigate }: Props) {
  const { job, error, refresh } = useJob(jobId);
  const segments = useSegments(jobId, job?.status, !!job?.before);
  const { records, complete } = useTrace(jobId, job?.status);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dialogDismissed, setDialogDismissed] = useState(false);

  const beforeSegments = useMemo(() => job?.before?.segments ?? [], [job]);
  // first segment is selected until the user picks another
  const effectiveId = selectedId ?? beforeSegments[0]?.id ?? null;

  const selected = useMemo<Segment | SegmentDetail | null>(() => {
    if (!effectiveId) return null;
    return segments?.find((s) => s.id === effectiveId) ?? beforeSegments.find((s) => s.id === effectiveId) ?? null;
  }, [effectiveId, segments, beforeSegments]);
  const isDetail = (s: Segment | SegmentDetail): s is SegmentDetail => 'region_series' in s;
  const selectedRemediation: RemediationSegment | null =
    (selected && isDetail(selected) ? selected.remediation : null) ??
    job?.remediation?.segments.find((s) => s.segment_id === effectiveId) ??
    null;

  const pending = job?.pending_approvals?.[0];
  const duration = job?.input?.duration_s ?? (job?.before?.per_second.length || 1);

  useEffect(() => {
    document.title = job ? `SteadyFrame · job ${job.job_id} · ${job.status}` : 'SteadyFrame · job';
    return () => { document.title = 'SteadyFrame'; };
  }, [job]);

  if (!job) {
    return (
      <section className="card">
        <h1>Job {jobId}</h1>
        {error ? (
          <p className="alert" role="alert">Could not load this job: {error}. <a href={href('/')} onClick={(e) => { e.preventDefault(); navigate('/'); }}>Back to start</a>.</p>
        ) : (
          <p role="status" aria-live="polite">Loading job…</p>
        )}
      </section>
    );
  }

  return (
    <>
      <nav aria-label="Breadcrumb" className="crumbs">
        <a href={href('/')} onClick={(e) => { e.preventDefault(); navigate('/'); }}>Start</a> › Job {job.job_id}
      </nav>
      <h1>Job {job.job_id}</h1>

      <JobStatusPanel job={job} pollError={error} />

      {pending && (
        <>
          <section className="card approval-banner" aria-labelledby="approval-banner-h">
            <h2 id="approval-banner-h">Your decision is needed</h2>
            <p>
              Segment <code>{pending.segment_id}</code>: {pending.reason}. The job is paused until
              you approve or reject a candidate.
            </p>
            <button type="button" className="btn primary" onClick={() => setDialogDismissed(false)}>Review candidates</button>
          </section>
          <ApprovalDialog
            key={pending.segment_id}
            jobId={job.job_id}
            pending={pending}
            segment={beforeSegments.find((s) => s.id === pending.segment_id)}
            open={!dialogDismissed}
            onClose={() => setDialogDismissed(true)}
            onDecided={() => { setDialogDismissed(true); refresh(); }}
          />
        </>
      )}

      {job.before ? (
        <section className="card" aria-labelledby="timeline-h">
          <h2 id="timeline-h">Hazard timeline</h2>
          <p className="muted small">
            Verdict before: <strong>{job.before.verdict}</strong>
            {job.after ? <> · after: <strong>{job.after.verdict}</strong></> : null}
            {' '}· {beforeSegments.length} segment{beforeSegments.length === 1 ? '' : 's'} flagged.
          </p>
          <HazardTimeline duration={duration} before={job.before} after={job.after} selectedId={effectiveId} onSelect={setSelectedId} />
        </section>
      ) : (
        <section className="card"><h2>Hazard timeline</h2><p className="muted">Available once analysis finishes.</p></section>
      )}

      {job.before?.timeline && (
        <section className="card" aria-labelledby="plot-h">
          <h2 id="plot-h">Luminance and flash rate</h2>
          <LuminancePlot before={job.before.timeline} after={job.after?.timeline ?? null} segments={beforeSegments} duration={duration} />
        </section>
      )}

      {selected && (
        <section className="card" aria-labelledby="segment-h">
          <h2 id="segment-h">Segment {selected.id}</h2>
          <SegmentInspector jobId={job.job_id} segment={selected} remediation={selectedRemediation} />
        </section>
      )}

      <section className="card" aria-labelledby="remediation-h">
        <h2 id="remediation-h">Remediation</h2>
        <RemediationSummary job={job} />
      </section>

      <section className="card" aria-labelledby="downloads-h">
        <h2 id="downloads-h">Downloads</h2>
        <Downloads job={job} />
      </section>

      <section className="card" aria-labelledby="preview-h">
        <h2 id="preview-h">Previews</h2>
        <p className="muted small">Nothing on this page plays on its own. Still frames and plots above are the primary way to inspect hazards.</p>
        <div className="two-col">
          <OriginalPreview job={job} />
          <RemediatedPreview job={job} />
        </div>
      </section>

      <section className="card" aria-labelledby="trace-h">
        <h2 id="trace-h">Agent trace</h2>
        <p className="muted small">
          Every tool call, result, model turn and decision, in order. Highlighted rows are
          verification results (an OpenCV re-analysis) that changed what the agent did next.
        </p>
        <TraceViewer records={records} complete={complete} />
      </section>
    </>
  );
}
