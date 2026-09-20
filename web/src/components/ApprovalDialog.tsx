import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { fmtNum, fmtRange, paramsText, strategyLabel } from '../format';
import type { PendingApproval, Segment } from '../types';

interface Props {
  jobId: string;
  pending: PendingApproval;
  segment?: Segment;
  open: boolean;
  onClose: () => void;
  onDecided: (approved: boolean) => void;
}

/** Modal for a paused job. Uses the native <dialog> so focus trapping and Esc come for free. */
export function ApprovalDialog({ jobId, pending, segment, open, onClose, onDecided }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [candidate, setCandidate] = useState(pending.options[0]?.candidate_id ?? null);
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  async function decide(approved: boolean) {
    setBusy(approved ? 'approve' : 'reject');
    setError(null);
    try {
      await api.approve(jobId, { segment_id: pending.segment_id, approved, candidate_id: candidate });
      onDecided(approved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <dialog ref={ref} className="dialog" aria-labelledby="approval-h" onClose={onClose}>
      <form method="dialog" onSubmit={(e) => e.preventDefault()}>
        <h2 id="approval-h">Approval needed for segment {pending.segment_id}</h2>
        <p>
          <strong>Reason:</strong> {pending.reason}
          {pending.last_resort ? ' (last resort: every strategy in the budget was tried)' : ''}
        </p>
        {segment && (
          <p className="muted">
            {segment.type} flash, {fmtRange(segment.start_s, segment.end_s)}, peak{' '}
            {segment.peak_flash_rate_hz} Hz, area {fmtNum(segment.max_area_fraction, 2)}.
          </p>
        )}

        <fieldset className="options">
          <legend>Candidate fixes ({pending.options.length})</legend>
          {pending.options.map((o) => (
            <label key={o.candidate_id} className="option">
              <input
                type="radio"
                name="candidate"
                value={o.candidate_id}
                checked={candidate === o.candidate_id}
                onChange={() => setCandidate(o.candidate_id)}
              />
              <span className="option-body">
                <span className="option-title">
                  <code>{o.candidate_id}</code> · {strategyLabel(o.strategy)}
                  {o.passes === false && <span className="badge badge-fail">does not pass</span>}
                  {o.passes === true && <span className="badge badge-pass">passes thresholds</span>}
                </span>
                <span className="muted">params: {paramsText(o.params)}</span>
                <dl className="metrics">
                  <div><dt>SSIM overall</dt><dd>{fmtNum(o.quality?.ssim_overall)}</dd></div>
                  <div><dt>SSIM inside region</dt><dd>{fmtNum(o.quality?.ssim_inside)}</dd></div>
                  <div><dt>SSIM outside</dt><dd>{fmtNum(o.quality?.ssim_outside)}</dd></div>
                  <div><dt>Mean |ΔL| inside</dt><dd>{fmtNum(o.quality?.mean_abs_dL_inside)}</dd></div>
                </dl>
              </span>
            </label>
          ))}
        </fieldset>

        {error && <p className="alert" role="alert">{error}</p>}
        <p className="muted small">
          Approving accepts the selected candidate and resumes the job. Rejecting sends the job
          back to try the next strategy, or marks the segment unresolved if none is left.
        </p>
        <div className="actions">
          <button type="button" className="btn primary" disabled={busy !== null || !candidate} onClick={() => decide(true)}>
            {busy === 'approve' ? 'Approving…' : 'Approve selected'}
          </button>
          <button type="button" className="btn" disabled={busy !== null} onClick={() => decide(false)}>
            {busy === 'reject' ? 'Rejecting…' : 'Reject'}
          </button>
          <button type="button" className="btn ghost" onClick={onClose}>Decide later</button>
        </div>
      </form>
    </dialog>
  );
}
