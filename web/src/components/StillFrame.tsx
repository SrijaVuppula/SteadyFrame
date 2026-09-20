import { useState } from 'react';
import { api } from '../api';
import type { Segment } from '../types';

/** Server-rendered still from the middle of the segment, regions outlined. Never animated. */
export function StillFrame({ jobId, segment }: { jobId: string; segment: Segment }) {
  const [failed, setFailed] = useState(false);
  const mid = ((segment.start_s + segment.end_s) / 2).toFixed(2);
  const alt = `Still frame from segment ${segment.id} at about ${mid} s with ${segment.regions.length} flagged region${segment.regions.length === 1 ? '' : 's'} outlined`;
  return (
    <figure className="still">
      {failed ? (
        <div className="still-missing" role="img" aria-label={alt}>Still frame not available</div>
      ) : (
        <img
          key={segment.id}
          src={api.frameUrl(jobId, segment.id)}
          alt={alt}
          width={320}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
        />
      )}
      <figcaption className="muted small">
        Single still frame at ~{mid} s, regions outlined by the analyzer. Not animated.
      </figcaption>
    </figure>
  );
}
