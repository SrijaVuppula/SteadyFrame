// The live demo: one page, like the product itself. Pick a test clip (or drop in your own) and
// watch the deployed AWS worker check it; the main card shows the current check, or before the
// first run a recorded one. Checks started here are listed under the picker.
import { useCallback, useEffect, useState } from 'react';
import { CheckView } from '../components/CheckView';
import { RunPanel } from '../components/RunPanel';
import { loadRecent, saveRecent, type RecentCheck } from '../recent';
import type { Policy } from '../types';

const EXAMPLE = { jobId: 'jd-live', label: 'Two flashing regions' };

const STATUS_LABEL: Record<string, string> = {
  passed: 'repaired',
  no_hazards: 'no hazards',
  failed_verification: 'not repaired',
  needs_approval: 'needs you',
  error: 'error',
};

export function DemoPage({ navigate }: { navigate: (p: string) => void }) {
  const [recent, setRecent] = useState<RecentCheck[]>(() => loadRecent());
  const [current, setCurrent] = useState<{ jobId: string; label: string; startedAt?: number } | null>(null);

  useEffect(() => {
    document.title = 'SteadyFrame · live demo';
  }, []);

  function started(jobId: string, label: string, policy: Policy) {
    const entry: RecentCheck = { jobId, label, policy, at: Date.now() };
    const next = [entry, ...recent.filter((r) => r.jobId !== jobId)];
    setRecent(next);
    saveRecent(next);
    setCurrent({ jobId, label, startedAt: entry.at });
    window.scrollTo({ top: 0 });
  }

  const onStatus = useCallback((jobId: string, status: string) => {
    setRecent((prev) => {
      if (!prev.some((r) => r.jobId === jobId && r.status !== status)) return prev;
      const next = prev.map((r) => (r.jobId === jobId ? { ...r, status } : r));
      saveRecent(next);
      return next;
    });
  }, []);

  const shown: { jobId: string; label: string; startedAt?: number } =
    current ?? (recent[0] ? { jobId: recent[0].jobId, label: recent[0].label } : EXAMPLE);
  const isExample = shown.jobId === EXAMPLE.jobId && !current;

  return (
    <div className="sf-demo">
      <section className="sf-hero" aria-labelledby="sf-hero-h">
        <div className="sf-hero-text">
          <h1 id="sf-hero-h">Find the flash. <em>Steady the frame.</em></h1>
          <p>A live flash-safety check on AWS. Pick a clip and press Run check. No video plays here.</p>
        </div>
        <dl className="sf-credits">
          <div><dt>planned by</dt><dd>Amazon Bedrock</dd></div>
          <div><dt>checked by</dt><dd>OpenCV 5</dd></div>
          <div><dt>approved by</dt><dd>you</dd></div>
        </dl>
      </section>

      <div className="sf-layout">
        <aside className="sf-side" aria-label="Run a check">
          <RunPanel onStarted={started} />

          {recent.length > 0 && (
            <section className="sf-card sf-recent-card" aria-labelledby="sf-recent-h">
              <h2 className="sf-label" id="sf-recent-h">Your checks</h2>
              <ul className="sf-recent">
                {recent.map((r) => (
                  <li key={r.jobId}>
                    <button type="button" className={`sf-recent-item${shown.jobId === r.jobId ? ' on' : ''}`}
                      aria-current={shown.jobId === r.jobId ? 'true' : undefined}
                      onClick={() => setCurrent({ jobId: r.jobId, label: r.label })}>
                      <span className={`sf-dot s-${r.status ?? 'running'}`} aria-hidden="true" />
                      <span className="sf-recent-name">{r.label}</span>
                      <span className="sf-recent-meta">{STATUS_LABEL[r.status ?? ''] ?? 'running'}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>

        <div className="sf-main">
          <CheckView
            key={shown.jobId}
            jobId={shown.jobId}
            label={shown.label}
            startedAt={shown.startedAt}
            example={isExample}
            navigate={navigate}
            onStatus={onStatus}
          />
        </div>
      </div>
    </div>
  );
}
