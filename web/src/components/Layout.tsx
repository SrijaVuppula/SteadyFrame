import { useEffect, useState, type ReactNode } from 'react';
import { api } from '../api';
import { MOCK_MODE, WHAT_IT_DOES } from '../config';
import { href } from '../hooks/useRoute';
import { REPO_URL } from '../judge';
import type { Health } from '../types';
import { Logo } from './art';

export function Layout({ children, navigate }: { children: ReactNode; navigate: (p: string) => void }) {
  const [health, setHealth] = useState<Health | null | undefined>(undefined);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);
  const live = !!health && health.ok;

  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="site-header">
        <div className="wrap header-row">
          <a
            className="brand"
            href={href('/')}
            onClick={(e) => { e.preventDefault(); navigate('/'); }}
            aria-label="SteadyFrame, live demo"
          >
            <Logo /> SteadyFrame
          </a>
          <div className="site-actions">
            <span className={`sf-live${live ? '' : ' off'}`} title={health ? `OpenCV ${health.opencv} · ${health.mode}` : undefined}>
              <span aria-hidden="true" className="sf-live-dot" /> {health === undefined ? 'Connecting' : live ? 'Live' : 'Offline'}
            </span>
            <a className="site-link" href={REPO_URL}>Code</a>
            <a className="site-link wide" href={`${REPO_URL}/blob/main/docs/report/REPORT.md`}>Report</a>
          </div>
        </div>
      </header>
      <main id="main" className="wrap" tabIndex={-1}>
        {MOCK_MODE && (
          <p className="notice" role="note">
            Fixture mode: this page is served from bundled sample outputs, not a live API.
          </p>
        )}
        {children}
      </main>
      <footer className="site-footer">
        <div className="wrap footer-row">
          <p>
            SteadyFrame {WHAT_IT_DOES}. Not a medical device: a pass means the thresholds were met,
            not that a clip is safe for every viewer.
          </p>
          <a href={href('/jobs/jd-adapt')} onClick={(e) => { e.preventDefault(); navigate('/jobs/jd-adapt'); }}>
            Recorded run: the model changes its plan
          </a>
        </div>
      </footer>
    </>
  );
}
