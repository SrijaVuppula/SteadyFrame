// Horizontal hazard timeline: per-second verdict strips (before and, when available, after)
// and one focusable block per segment coloured by hazard type. Colour is never the only
// carrier: every block has a text label and an aria-label, and the data table below repeats it.
import { HAZARD_LABEL, fmtRange } from '../format';
import type { AnalysisSummary, Segment } from '../types';

interface Props {
  duration: number;
  before: AnalysisSummary;
  after?: AnalysisSummary | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function pct(x: number, duration: number) {
  return `${Math.max(0, Math.min(100, (x / duration) * 100))}%`;
}

function tickValues(duration: number): number[] {
  const step = duration <= 12 ? 1 : duration <= 30 ? 5 : duration <= 90 ? 10 : 30;
  const out: number[] = [];
  for (let t = 0; t <= duration + 1e-6; t += step) out.push(+t.toFixed(2));
  return out;
}

function VerdictStrip({ summary, label, duration }: { summary: AnalysisSummary; label: string; duration: number }) {
  const n = Math.max(1, Math.ceil(duration));
  return (
    <div className="strip-row">
      <span className="strip-label">{label}</span>
      <ol className="strip" aria-label={`Per-second verdict, ${label}`}>
        {summary.per_second.map((s) => {
          const types = (['general', 'red', 'pattern'] as const).filter((t) => s[t] === 'fail');
          const text = `second ${s.second}: ${s.verdict}${types.length ? ` (${types.join(', ')}${s.max_flash_rate_hz ? `, ${s.max_flash_rate_hz} Hz` : ''})` : ''}`;
          return (
            <li
              key={s.second}
              className={`cell verdict-${s.verdict}`}
              style={{ width: `${100 / n}%` }}
              title={text}
              aria-label={text}
            />
          );
        })}
      </ol>
    </div>
  );
}

export function HazardTimeline({ duration, before, after, selectedId, onSelect }: Props) {
  const segments: Segment[] = before.segments;
  return (
    <div className="timeline">
      <div className="strip-row axis-row" aria-hidden="true">
        <span className="strip-label" />
        <div className="axis">
          {tickValues(duration).map((t) => (
            <span key={t} className="tick" style={{ left: pct(t, duration) }}>{t}s</span>
          ))}
        </div>
      </div>

      <VerdictStrip summary={before} label="before" duration={duration} />

      <div className="strip-row">
        <span className="strip-label">segments</span>
        <div className="segments-track" role="group" aria-label="Hazard segments; select one to inspect it">
          {segments.length === 0 && <span className="muted small">No segments</span>}
          {segments.map((s) => {
            const w = Math.max(1.5, ((s.end_s - s.start_s) / duration) * 100);
            const label = `Segment ${s.id}, ${HAZARD_LABEL[s.type]}, ${fmtRange(s.start_s, s.end_s)}, peak ${s.peak_flash_rate_hz} Hz, severity ${s.severity_score.toFixed(2)}`;
            return (
              <button
                key={s.id}
                type="button"
                className={`seg seg-${s.type}${selectedId === s.id ? ' selected' : ''}`}
                style={{ left: pct(s.start_s, duration), width: `${w}%` }}
                aria-pressed={selectedId === s.id}
                aria-label={label}
                title={label}
                onClick={() => onSelect(s.id)}
              >
                <span className="seg-text">{s.id}</span>
              </button>
            );
          })}
        </div>
      </div>

      {after && <VerdictStrip summary={after} label="after" duration={duration} />}

      <ul className="legend" aria-label="Legend">
        <li><span className="swatch verdict-pass" /> pass</li>
        <li><span className="swatch verdict-warn" /> warn</li>
        <li><span className="swatch verdict-fail" /> fail</li>
        <li><span className="swatch seg-general" /> general flash</li>
        <li><span className="swatch seg-red" /> red flash</li>
        <li><span className="swatch seg-pattern" /> spatial pattern</li>
      </ul>

      <details className="table-details">
        <summary>Per-second data table</summary>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Per-second data table, scrollable">
          <table className="data">
            <caption className="sr-only">Per-second verdicts before and after remediation</caption>
            <thead>
              <tr>
                <th scope="col">Second</th><th scope="col">Before</th><th scope="col">General</th>
                <th scope="col">Red</th><th scope="col">Pattern</th><th scope="col">Max rate (Hz)</th>
                <th scope="col">Max area</th>{after && <th scope="col">After</th>}
              </tr>
            </thead>
            <tbody>
              {before.per_second.map((s, i) => (
                <tr key={s.second}>
                  <th scope="row">{s.second}</th>
                  <td>{s.verdict}</td><td>{s.general}</td><td>{s.red}</td><td>{s.pattern ?? '–'}</td>
                  <td>{s.max_flash_rate_hz ?? '–'}</td><td>{s.max_area_fraction ?? '–'}</td>
                  {after && <td>{after.per_second[i]?.verdict ?? '–'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
