// Shared pieces of the /judge tour: the before/after flash-rate chart, the model/analyzer
// conversation built from a trace, and a few line icons. Nothing here animates.
import { useMemo, type ReactNode } from 'react';
import { type Bubble, conversation, flashRate, peak } from '../tourData';
import type { Segment, Timeline, TraceRecord } from '../types';

export type IconName = 'doc' | 'terminal' | 'captions' | 'play' | 'cross' | 'shield' | 'eye' | 'wrench' | 'stamp' | 'bolt';

export function Icon({ name }: { name: IconName }) {
  const p: Record<IconName, ReactNode> = {
    doc: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>,
    terminal: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M12 15h5" /></>,
    captions: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 13h4M13 13h4M7 16h10" /></>,
    play: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M10 9l5 3-5 3z" /></>,
    cross: <path d="M6 6l12 12M18 6L6 18" />,
    shield: <><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></>,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>,
    wrench: <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" />,
    stamp: <><path d="M9 3h6v6l2 3H7l2-3z" /><path d="M5 15h14v3H5zM7 21h10" /></>,
    bolt: <path d="M13 3L5 13h6l-1 8 8-10h-6z" />,
  };
  return (
    <svg className="jx-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {p[name]}
    </svg>
  );
}

// ---------------------------------------------------------------- before/after chart

export function RateChart({ before, after, segments, duration }: { before: Timeline; after: Timeline | null; segments: Segment[]; duration: number }) {
  const W = 960, H = 280, ML = 40, MR = 16, MT = 16, MB = 34;
  const rb = flashRate(before);
  const ra = after ? flashRate(after) : null;
  const ymax = Math.max(4, Math.ceil(peak(rb) + 1));
  const x = (t: number) => ML + (t / Math.max(duration, 1e-6)) * (W - ML - MR);
  const y = (v: number) => MT + (1 - v / ymax) * (H - MT - MB);
  const path = (tl: Timeline | null, r: number[] | null) => {
    if (!tl || !r) return '';
    let d = '';
    for (let i = 0; i < tl.t.length; i++) d += `${d ? 'L' : 'M'}${x(tl.t[i]).toFixed(1)},${y(r[i] ?? 0).toFixed(1)}`;
    return d;
  };
  const ticks = Array.from({ length: Math.floor(duration) + 1 }, (_, i) => i).filter((t) => duration <= 12 || t % 2 === 0);
  // the label goes in the middle of the widest stretch without a hazard, clear of the lines
  const edges = [0, ...[...segments].sort((a, b) => a.start_s - b.start_s).flatMap((s) => [s.start_s, s.end_s]), duration];
  let quietMid = duration / 2, widest = -1;
  for (let i = 0; i + 1 < edges.length; i += 2) {
    if (edges[i + 1] - edges[i] > widest) { widest = edges[i + 1] - edges[i]; quietMid = (edges[i] + edges[i + 1]) / 2; }
  }
  return (
    <svg className="jx-chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Flashes per second over ${duration.toFixed(0)} seconds: before the fix the peak is ${peak(rb).toFixed(0)}; after it, ${peak(ra ?? []).toFixed(1)}; the limit is 3.`}>
      {segments.map((s) => (
        <rect key={s.id} className="jx-chart-seg" x={x(s.start_s)} y={MT} width={Math.max(2, x(s.end_s) - x(s.start_s))} height={H - MT - MB} rx="6" />
      ))}
      {[0, Math.round(ymax / 2), ymax].map((v) => (
        <g key={v}>
          <line className="jx-chart-grid" x1={ML} x2={W - MR} y1={y(v)} y2={y(v)} />
          <text className="jx-chart-label" x={ML - 8} y={y(v) + 4} textAnchor="end">{v}</text>
        </g>
      ))}
      {ticks.map((t) => (
        <text key={t} className="jx-chart-label" x={x(t)} y={H - 10} textAnchor="middle">{t}s</text>
      ))}
      <line className="jx-chart-limit" x1={ML} x2={W - MR} y1={y(3)} y2={y(3)} />
      <text className="jx-chart-limit-label" x={x(quietMid)} y={y(3) - 8} textAnchor="middle">limit: 3 flashes a second</text>
      <path className="jx-chart-before" d={path(before, rb)} />
      {after && <path className="jx-chart-after" d={path(after, ra)} />}
    </svg>
  );
}

const WHO: Record<Bubble['who'], [string, string]> = {
  model: ['M', 'Model · Amazon Bedrock'],
  policy: ['F', 'Fixed policy'],
  analyzer: ['A', 'Analyzer · OpenCV 5'],
  pipeline: ['P', 'Pipeline'],
};

export function Conversation({ records, live }: { records: TraceRecord[]; live?: boolean }) {
  const items = useMemo(() => conversation(records), [records]);
  return (
    <ol className="jx-convo" aria-label="What the planner did and what the analyzer answered, in order" aria-live={live ? 'polite' : undefined}>
      {items.map((b) => (
        <li key={b.key} className={`jx-msg jx-${b.who}${b.tone ? ` tone-${b.tone}` : ''}${b.pivot ? ' pivot' : ''}`}>
          <span className="jx-avatar" aria-hidden="true">{WHO[b.who][0]}</span>
          <div className="jx-bubble">
            <span className="jx-who">{WHO[b.who][1]}</span>
            {b.pivot && <span className="jx-pivot">Changed its plan because of the failed check</span>}
            <p>{b.text}</p>
            {b.action && <code className="jx-action">→ {b.action}</code>}
          </div>
        </li>
      ))}
    </ol>
  );
}
