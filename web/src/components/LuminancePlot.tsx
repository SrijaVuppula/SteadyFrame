// Inline-SVG plots of the analysis timelines. Two stacked panels sharing one time axis (never a
// dual y-axis): mean relative luminance, then flash rate with the profile threshold. Segments are
// shaded by hazard type. A crosshair readout follows the pointer and a range input for keyboards.
import { useId, useMemo, useState } from 'react';
import { HAZARD_LABEL, fmtNum } from '../format';
import type { Segment, Timeline } from '../types';

const W = 720;
const ML = 44;
const MR = 12;
const PW = W - ML - MR;

function pathFor(t: number[], v: number[], x: (t: number) => number, y: (v: number) => number): string {
  let d = '';
  for (let i = 0; i < t.length && i < v.length; i++) {
    if (!Number.isFinite(v[i])) continue;
    d += `${d ? 'L' : 'M'}${x(t[i]).toFixed(1)},${y(v[i]).toFixed(1)}`;
  }
  return d;
}

function nearestIndex(t: number[], target: number): number {
  let lo = 0;
  let hi = t.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (t[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(t[lo - 1] - target) < Math.abs(t[lo] - target)) return lo - 1;
  return lo;
}

function SegmentShade({ segments, x, y0, h }: { segments: Segment[]; x: (t: number) => number; y0: number; h: number }) {
  return (
    <g>
      {segments.map((s) => (
        <rect
          key={s.id}
          className={`shade shade-${s.type}`}
          x={x(s.start_s)}
          y={y0}
          width={Math.max(1, x(s.end_s) - x(s.start_s))}
          height={h}
        >
          <title>{`${s.id}: ${HAZARD_LABEL[s.type]}`}</title>
        </rect>
      ))}
    </g>
  );
}

interface Props {
  before: Timeline;
  after?: Timeline | null;
  segments: Segment[];
  duration: number;
  /** Flashes per second above which the profile fails a window (3 for WCAG and BT.1702). */
  thresholdHz?: number;
}

export function LuminancePlot({ before, after, segments, duration, thresholdHz = 3 }: Props) {
  const id = useId();
  const [cursor, setCursor] = useState<number | null>(null);

  const H1 = 150;
  const H2 = 110;
  const gap = 34;
  const top = 12;
  const H = top + H1 + gap + H2 + 30;

  const x = (t: number) => ML + (t / duration) * PW;
  const yL = (v: number) => top + H1 - v * H1;
  const maxRate = useMemo(() => {
    const all = [...before.general_rate_hz, ...before.red_rate_hz, ...(after?.general_rate_hz ?? []), thresholdHz];
    return Math.max(4, Math.ceil(Math.max(...all.filter(Number.isFinite)) + 0.5));
  }, [before, after, thresholdHz]);
  const y2top = top + H1 + gap;
  const yR = (v: number) => y2top + H2 - (v / maxRate) * H2;

  const paths = useMemo(
    () => ({
      Lb: pathFor(before.t, before.mean_L, x, yL),
      La: after ? pathFor(after.t, after.mean_L, x, yL) : '',
      Gb: pathFor(before.t, before.general_rate_hz, x, yR),
      Rb: pathFor(before.t, before.red_rate_hz, x, yR),
      Ga: after ? pathFor(after.t, after.general_rate_hz, x, yR) : '',
    }),
    // x/yL/yR are derived from duration, H1, H2 and maxRate which are all captured here
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [before, after, duration, maxRate],
  );

  const stats = useMemo(() => {
    const finite = before.mean_L.filter(Number.isFinite);
    const min = Math.min(...finite);
    const max = Math.max(...finite);
    const peak = Math.max(...before.general_rate_hz.filter(Number.isFinite), 0);
    const peakAfter = after ? Math.max(...after.general_rate_hz.filter(Number.isFinite), 0) : null;
    return { min, max, peak, peakAfter };
  }, [before, after]);

  const readout = useMemo(() => {
    if (cursor === null) return null;
    const i = nearestIndex(before.t, cursor);
    const j = after ? nearestIndex(after.t, cursor) : -1;
    return {
      t: before.t[i],
      Lb: before.mean_L[i],
      La: j >= 0 ? after!.mean_L[j] : null,
      Gb: before.general_rate_hz[i],
      Rb: before.red_rate_hz[i],
      Ga: j >= 0 ? after!.general_rate_hz[j] : null,
    };
  }, [cursor, before, after]);

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const t = ((px - ML) / PW) * duration;
    setCursor(Math.max(0, Math.min(duration, t)));
  };

  const desc = `Mean luminance ranges ${fmtNum(stats.min, 2)} to ${fmtNum(stats.max, 2)} before remediation; peak general flash rate ${fmtNum(stats.peak, 1)} Hz before${stats.peakAfter !== null ? ` and ${fmtNum(stats.peakAfter, 1)} Hz after` : ''}, threshold ${thresholdHz} Hz. ${segments.length} segment(s) shaded.`;

  return (
    <div className="plot">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="plot-svg"
        role="img"
        aria-labelledby={`${id}-title ${id}-desc`}
        onPointerMove={onMove}
        onPointerLeave={() => setCursor(null)}
      >
        <title id={`${id}-title`}>Mean luminance and flash rate over time, before and after remediation</title>
        <desc id={`${id}-desc`}>{desc}</desc>

        {/* panel 1: mean L */}
        <g className="axis-text">
          <text x={ML - 6} y={yL(1) + 4} textAnchor="end">1.0</text>
          <text x={ML - 6} y={yL(0.5) + 4} textAnchor="end">0.5</text>
          <text x={ML - 6} y={yL(0) + 4} textAnchor="end">0</text>
          <text x={ML} y={top - 2} className="panel-title">mean relative luminance L</text>
        </g>
        <line className="grid" x1={ML} x2={W - MR} y1={yL(0.5)} y2={yL(0.5)} />
        <line className="axis" x1={ML} x2={W - MR} y1={yL(0)} y2={yL(0)} />
        <SegmentShade segments={segments} x={x} y0={top} h={H1} />
        <path className="series before" d={paths.Lb} />
        {after && <path className="series after" d={paths.La} />}

        {/* panel 2: flash rate */}
        <g className="axis-text">
          <text x={ML - 6} y={yR(maxRate) + 4} textAnchor="end">{maxRate}</text>
          <text x={ML - 6} y={yR(thresholdHz) + 4} textAnchor="end">{thresholdHz}</text>
          <text x={ML - 6} y={yR(0) + 4} textAnchor="end">0</text>
          <text x={ML} y={y2top - 4} className="panel-title">flashes per second (Hz), threshold {thresholdHz}</text>
        </g>
        <line className="threshold" x1={ML} x2={W - MR} y1={yR(thresholdHz)} y2={yR(thresholdHz)} />
        <line className="axis" x1={ML} x2={W - MR} y1={yR(0)} y2={yR(0)} />
        <SegmentShade segments={segments} x={x} y0={y2top} h={H2} />
        <path className="series before" d={paths.Gb} />
        <path className="series red-series" d={paths.Rb} />
        {after && <path className="series after" d={paths.Ga} />}

        {/* time axis */}
        <g className="axis-text">
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <text key={f} x={x(f * duration)} y={H - 10} textAnchor={f === 0 ? 'start' : f === 1 ? 'end' : 'middle'}>
              {(f * duration).toFixed(1)} s
            </text>
          ))}
        </g>

        {readout && (
          <g className="crosshair" aria-hidden="true">
            <line x1={x(readout.t)} x2={x(readout.t)} y1={top} y2={y2top + H2} />
            <circle cx={x(readout.t)} cy={yL(readout.Lb)} r={4} className="dot before" />
            {readout.La !== null && <circle cx={x(readout.t)} cy={yL(readout.La)} r={4} className="dot after" />}
          </g>
        )}
      </svg>

      <div className="plot-footer">
        <ul className="legend" aria-label="Series">
          <li><span className="swatch line-before" /> before (mean L, general rate)</li>
          <li><span className="swatch line-red" /> before, red flash rate</li>
          {after && <li><span className="swatch line-after" /> after remediation</li>}
          <li><span className="swatch line-threshold" /> threshold {thresholdHz} Hz</li>
        </ul>
        <label className="inspect">
          Inspect time
          <input
            type="range"
            min={0}
            max={duration}
            step={Math.max(0.01, duration / 400)}
            value={cursor ?? 0}
            onChange={(e) => setCursor(Number(e.target.value))}
          />
        </label>
        <p className="readout" aria-live="off">
          {readout
            ? `t = ${fmtNum(readout.t, 2)} s · L before ${fmtNum(readout.Lb, 3)}${readout.La !== null ? `, after ${fmtNum(readout.La, 3)}` : ''} · general ${fmtNum(readout.Gb, 1)} Hz${readout.Ga !== null ? ` → ${fmtNum(readout.Ga, 1)} Hz` : ''} · red ${fmtNum(readout.Rb, 1)} Hz`
            : 'Move the pointer over the plot or use the slider to read values.'}
        </p>
      </div>
    </div>
  );
}

/** Region luminance for one segment (GET /segments region_series), segment span shaded. */
export function RegionSeriesPlot({ series, segment }: { series: { t: number[]; L: number[] }; segment: Segment }) {
  const id = useId();
  const H = 120;
  const top = 8;
  const t0 = series.t.length ? series.t[0] : segment.start_s;
  const t1 = series.t.length ? series.t[series.t.length - 1] : segment.end_s;
  const span = Math.max(1e-6, t1 - t0);
  const x = (t: number) => ML + ((t - t0) / span) * PW;
  const y = (v: number) => top + H - Math.max(0, Math.min(1, v)) * H;
  const d = pathFor(series.t, series.L, x, y);
  const finite = series.L.filter(Number.isFinite);
  const desc = `Luminance inside the flagged region from ${fmtNum(t0, 2)} to ${fmtNum(t1, 2)} s, ranging ${fmtNum(Math.min(...finite), 2)} to ${fmtNum(Math.max(...finite), 2)}; ${series.t.length} samples.`;
  if (!series.t.length) return <p className="muted small">No region series for this segment.</p>;
  return (
    <svg viewBox={`0 0 ${W} ${H + 36}`} className="plot-svg small-plot" role="img" aria-labelledby={`${id}-t ${id}-d`}>
      <title id={`${id}-t`}>Region luminance over time for segment {segment.id}</title>
      <desc id={`${id}-d`}>{desc}</desc>
      <g className="axis-text">
        <text x={ML - 6} y={y(1) + 4} textAnchor="end">1.0</text>
        <text x={ML - 6} y={y(0) + 4} textAnchor="end">0</text>
        <text x={ML} y={H + 30} textAnchor="start">{fmtNum(t0, 1)} s</text>
        <text x={W - MR} y={H + 30} textAnchor="end">{fmtNum(t1, 1)} s</text>
      </g>
      <rect className={`shade shade-${segment.type}`} x={x(segment.start_s)} y={top} width={Math.max(1, x(segment.end_s) - x(segment.start_s))} height={H} />
      <line className="axis" x1={ML} x2={W - MR} y1={y(0)} y2={y(0)} />
      <path className="series before" d={d} />
    </svg>
  );
}
