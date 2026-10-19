// The live demo: one page, like the product itself. Run a check on a test clip or your own
// upload and watch it on the deployed AWS worker; the main card shows the current (or, before
// the first run, a recorded example) check, the sidebar starts new ones and lists recent ones.
import { useCallback, useEffect, useState } from 'react';
import { CheckView } from '../components/CheckView';
import { RunPanel } from '../components/RunPanel';
import { href } from '../hooks/useRoute';
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
      <h1 className="sr-only">SteadyFrame live demo</h1>
      <p className="sf-banner" role="note">
        <strong>This is a live demo on AWS.</strong> Pick a test clip and press <strong>Run check</strong> to
        watch SteadyFrame find the flashing that can trigger seizures, repair only that part, and re-check
        its own repair. Nothing on this page plays: hazards are shown as still frames and plots.
      </p>

      <div className="sf-layout">
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

        <aside className="sf-side" aria-label="Run and history">
          <RunPanel onStarted={started} />

          <section className="sf-card" aria-labelledby="sf-recent-h">
            <p className="sf-label" id="sf-recent-h">Recent checks</p>
            {recent.length === 0 ? (
              <p className="sf-fine">Checks you run appear here (kept in this browser only).</p>
            ) : (
              <ul className="sf-recent">
                {recent.map((r) => (
                  <li key={r.jobId}>
                    <button type="button" className={`sf-recent-item${shown.jobId === r.jobId ? ' on' : ''}`}
                      onClick={() => setCurrent({ jobId: r.jobId, label: r.label })}>
                      <span className={`sf-dot s-${r.status ?? 'running'}`} aria-hidden="true" />
                      <span className="sf-recent-name">{r.label}</span>
                      <span className="sf-recent-meta">{STATUS_LABEL[r.status ?? ''] ?? 'running'} · {r.policy === 'agent' ? 'model' : 'fixed'}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="sf-card" aria-labelledby="sf-how-h">
            <p className="sf-label" id="sf-how-h">Who decides what</p>
            <ul className="sf-how">
              <li><span className="sf-how-k">Model</span><span>picks the repair and its strength from the measurements; never sees pixels</span></li>
              <li><span className="sf-how-k">Analyzer</span><span>OpenCV 5 re-checks every candidate and the whole file; only it can pass a job</span></li>
              <li><span className="sf-how-k">You</span><span>approve or reject any repair that changes the picture a lot</span></li>
            </ul>
            <p className="sf-fine">
              <a href={href('/jobs/jd-adapt')} onClick={(e) => { e.preventDefault(); navigate('/jobs/jd-adapt'); }}>Recorded run where the model changes its plan</a>
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}
