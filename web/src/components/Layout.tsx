import { useEffect, useState, type ReactNode } from 'react';
import { api } from '../api';
import { MOCK_MODE, WHAT_IT_DOES } from '../config';
import { href } from '../hooks/useRoute';
import type { Health } from '../types';

export function Layout({ children, navigate }: { children: ReactNode; navigate: (p: string) => void }) {
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="site-header">
        <div className="wrap header-row">
          <a
            className="brand"
            href={href('/')}
            onClick={(e) => { e.preventDefault(); navigate('/'); }}
            aria-label="SteadyFrame, start page"
          >
            <span className="brand-mark" aria-hidden="true">▤</span> SteadyFrame
          </a>
          <p className="tagline">{`Analyzer and remediator that ${WHAT_IT_DOES}.`}</p>
        </div>
      </header>
      <main id="main" className="wrap" tabIndex={-1}>
        {MOCK_MODE && (
          <p className="notice" role="note">
            Fixture mode: this page is served from bundled sample outputs, not a live API. Jobs
            started here are simulated.
          </p>
        )}
        {children}
      </main>
      <footer className="site-footer">
        <div className="wrap">
          <p>
            <strong>Responsible use.</strong> SteadyFrame {WHAT_IT_DOES}. It is an engineering aid
            for content review, not a medical device, and a passing result is a threshold check,
            not a guarantee about any individual viewer. Uploaded files are deleted after one day.
          </p>
          <p className="muted">
            No tutorial media on this site. Video previews are shown on request only, never
            autoplayed; the original is dimmed, reduced and slowed. Captions and audio tracks of
            the input are carried into the remediated file unchanged.
          </p>
          <p className="muted">
            {health
              ? `API ${health.mode} mode · steadyframe ${health.version} · OpenCV ${health.opencv}`
              : 'API status unavailable'}
          </p>
        </div>
      </footer>
    </>
  );
}
