import { fmtNum, fmtRange, paramsText, strategyLabel } from '../format';
import type { Job } from '../types';

const OUTCOME_TONE: Record<string, string> = {
  accepted: 'pass', unresolved: 'fail', pending_approval: 'warn', open: 'neutral',
};

export function RemediationSummary({ job }: { job: Job }) {
  const r = job.remediation;
  if (!r) return <p className="muted">No remediation has run for this job.</p>;
  return (
    <div>
      <dl className="meta">
        <div><dt>Outcome</dt><dd>{r.status}</dd></div>
        <div><dt>Iterations</dt><dd>{r.iterations}</dd></div>
        <div><dt>Runtime</dt><dd>{fmtNum(r.runtime_s, 1)} s</dd></div>
        <div><dt>SSIM overall / outside / inside</dt><dd>
          {fmtNum(r.quality?.ssim_overall)} / {fmtNum(r.quality?.ssim_outside)} / {fmtNum(r.quality?.ssim_inside)}
        </dd></div>
        <div><dt>Mean |ΔL| inside regions</dt><dd>{fmtNum(r.quality?.mean_abs_dL_inside)}</dd></div>
        <div><dt>Engine</dt><dd>steadyframe {job.tool.version} · OpenCV {job.tool.opencv}</dd></div>
      </dl>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Per-segment remediation table, scrollable">
        <table className="data">
          <caption className="sr-only">Per-segment remediation: strategy, parameters, attempts and quality</caption>
          <thead>
            <tr>
              <th scope="col">Segment</th><th scope="col">Type</th><th scope="col">Range</th>
              <th scope="col">Outcome</th><th scope="col">Strategy</th><th scope="col">Params</th>
              <th scope="col">Attempts</th><th scope="col">SSIM overall</th><th scope="col">SSIM inside</th>
            </tr>
          </thead>
          <tbody>
            {r.segments.map((s) => (
              <tr key={s.segment_id}>
                <th scope="row"><code>{s.segment_id}</code></th>
                <td>{s.type}</td>
                <td>{s.start_s !== undefined && s.end_s !== undefined ? fmtRange(s.start_s, s.end_s) : '–'}</td>
                <td><span className={`badge badge-${OUTCOME_TONE[s.outcome] ?? 'neutral'}`}>{s.outcome.replace('_', ' ')}</span></td>
                <td>{strategyLabel(s.strategy)}</td>
                <td>{paramsText(s.params)}</td>
                <td>
                  {s.attempts.length}
                  {s.attempts.length > 0 && (
                    <ul className="attempts">
                      {s.attempts.map((a) => (
                        <li key={a.candidate_id}>
                          {a.strategy} {paramsText(a.params)} →{' '}
                          {a.verified ? (a.verified.passes_for_type ? 'pass' : 'still fails') : 'not verified'}
                          {a.verified?.requires_approval ? ', needs approval' : ''}
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td>{fmtNum(s.quality?.ssim_overall)}</td>
                <td>{fmtNum(s.quality?.ssim_inside)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
