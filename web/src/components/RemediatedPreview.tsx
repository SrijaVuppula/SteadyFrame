import { useState } from 'react';
import { api } from '../api';
import type { Job } from '../types';

/** Remediated output: controls, no autoplay, no loop. Loaded on request to keep the page light. */
export function RemediatedPreview({ job }: { job: Job }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!job.downloads?.video) return null;

  async function load() {
    try {
      const r = await api.downloadUrl(job.job_id, 'video');
      setSrc(r.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="preview remediated">
      <h3>Remediated clip</h3>
      <p className="muted small">
        Re-analysed verdict: <strong>{job.after?.verdict ?? 'unknown'}</strong>. Plays only when
        you press play, at normal speed with controls.
      </p>
      {!src ? (
        <button type="button" className="btn" onClick={load}>Load remediated preview</button>
      ) : (
        <video
          className="video-remediated"
          src={src}
          controls
          preload="metadata"
          playsInline
          aria-label="Remediated clip. Press play to view."
        >
          Your browser cannot play this video inline.
        </video>
      )}
      {error && <p className="alert" role="alert">{error}</p>}
    </div>
  );
}
