import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { Job } from '../types';
import { recallUpload } from '../uploadStore';

/**
 * Flash-safety rule 1: the original is never autoplayed. It sits behind an explicit
 * click-through, and when shown it is dimmed (brightness 0.4), at most 320 px wide, plays at
 * 0.25x, does not loop and has a stop button. Browsers reset playbackRate on some src changes,
 * so it is re-applied on every play event.
 */
export function OriginalPreview({ job }: { job: Job }) {
  const [shown, setShown] = useState(false);
  const [src, setSrc] = useState<string | null | undefined>(undefined); // undefined = not resolved
  const videoRef = useRef<HTMLVideoElement>(null);
  const failed = job.before?.verdict === 'fail' || job.before?.verdict === 'warn';

  useEffect(() => {
    if (!shown || src !== undefined) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    (async () => {
      const local = recallUpload(job.job_id);
      let url: string | null;
      if (local) {
        objectUrl = URL.createObjectURL(local);
        url = objectUrl;
      } else {
        url = await api.originalUrl(job.job_id);
      }
      if (!cancelled) setSrc(url);
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [shown, src, job.job_id]);

  const slow = () => {
    const v = videoRef.current;
    if (v) v.playbackRate = 0.25;
  };
  const stop = () => {
    const v = videoRef.current;
    if (v) { v.pause(); v.currentTime = 0; }
    setShown(false);
  };

  return (
    <div className="preview original">
      <h3>Original clip</h3>
      {!shown ? (
        <div className="warning-box">
          <p>
            <strong>Warning.</strong>{' '}
            {failed
              ? 'This clip failed photosensitivity checks against the selected thresholds. It contains flashing that some viewers may find harmful.'
              : 'This is the unmodified upload. It has not been altered in any way.'}{' '}
            If you choose to view it, it plays dimmed, at a quarter of its speed and at reduced size,
            with controls and no looping. Do not view it if you are sensitive to flashing images.
          </p>
          <button type="button" className="btn" onClick={() => setShown(true)}>
            I understand, show the original (dimmed, 0.25× speed)
          </button>
        </div>
      ) : (
        <div>
          {src === undefined && <p className="muted">Resolving preview source…</p>}
          {src === null && (
            <p className="muted">
              The original file is not available for preview on this job (the API exposes only the
              remediated output). Use the still frames and the luminance plot instead.
            </p>
          )}
          {src && (
            <video
              ref={videoRef}
              className="video-original"
              src={src}
              controls
              preload="metadata"
              playsInline
              disablePictureInPicture
              onLoadedMetadata={slow}
              onPlay={slow}
              onRateChange={(e) => { if (e.currentTarget.playbackRate > 0.25) slow(); }}
              aria-label="Original clip, dimmed and slowed to a quarter speed. Press play to view."
            >
              Your browser cannot play this video inline.
            </video>
          )}
          <p className="muted small">
            Shown at 320 px max, brightness 40%, 0.25× speed, no loop. No captions on this
            preview; the downloadable file keeps the input's tracks.
          </p>
          <button type="button" className="btn" onClick={stop}>Stop and hide</button>
        </div>
      )}
    </div>
  );
}
