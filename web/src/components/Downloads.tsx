import { useState } from 'react';
import { api } from '../api';
import type { DownloadKind, Job } from '../types';

const KINDS: Array<{ kind: DownloadKind; label: string; file: string }> = [
  { kind: 'video', label: 'Remediated video', file: 'safe.mp4' },
  { kind: 'report', label: 'Remediation report', file: 'report.json' },
  { kind: 'analysis', label: 'Analysis', file: 'analysis.json' },
  { kind: 'trace', label: 'Agent trace', file: 'trace.jsonl' },
  { kind: 'plot', label: 'Luminance plot', file: 'plot.png' },
  { kind: 'summary', label: 'Summary page', file: 'summary.html' },
];

export function Downloads({ job }: { job: Job }) {
  const [links, setLinks] = useState<Partial<Record<DownloadKind, string>>>({});
  const [busy, setBusy] = useState<DownloadKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const available = KINDS.filter((k) => job.downloads?.[k.kind]);

  async function fetchLink(kind: DownloadKind) {
    setBusy(kind);
    setError(null);
    try {
      const r = await api.downloadUrl(job.job_id, kind);
      setLinks((l) => ({ ...l, [kind]: r.url }));
      // Browsers may block a window opened after an await; the link below is the fallback.
      window.open(r.url, '_blank', 'noopener');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (!available.length) return <p className="muted">Nothing to download yet.</p>;
  return (
    <div>
      <ul className="download-list">
        {available.map(({ kind, label, file }) => (
          <li key={kind}>
            <button type="button" className="btn" disabled={busy !== null} onClick={() => fetchLink(kind)}>
              {busy === kind ? 'Fetching link…' : `Get ${label}`}
            </button>
            <span className="muted"> {file}</span>
            {links[kind] && (
              <>
                {' '}· <a href={links[kind]} target="_blank" rel="noopener noreferrer" download={file}>
                  Open {file}
                </a>
              </>
            )}
          </li>
        ))}
      </ul>
      <p className="sr-only" role="status" aria-live="polite">
        {Object.keys(links).length ? `${Object.keys(links).length} download link(s) ready` : ''}
      </p>
      {error && <p className="alert" role="alert">{error}</p>}
      <p className="muted small">Links are valid for 15 minutes. The remediated video plays at normal speed; review it before publishing.</p>
    </div>
  );
}
