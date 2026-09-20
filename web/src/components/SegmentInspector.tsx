import { HAZARD_LABEL, fmtNum, fmtRange, paramsText, strategyLabel } from '../format';
import type { RemediationSegment, Segment, SegmentDetail } from '../types';
import { RegionSeriesPlot } from './LuminancePlot';
import { StillFrame } from './StillFrame';

interface Props {
  jobId: string;
  segment: Segment | SegmentDetail;
  remediation?: RemediationSegment | null;
}

export function SegmentInspector({ jobId, segment, remediation }: Props) {
  const detail = 'region_series' in segment ? segment : null;
  return (
    <div className="inspector">
      <div className="inspector-grid">
        <dl className="meta">
          <div><dt>Segment</dt><dd><code>{segment.id}</code> · {HAZARD_LABEL[segment.type]} · verdict {segment.verdict}</dd></div>
          <div><dt>Range</dt><dd>{fmtRange(segment.start_s, segment.end_s)} (frames {segment.start_frame}–{segment.end_frame})</dd></div>
          <div><dt>Peak flash rate</dt><dd>{segment.peak_flash_rate_hz} Hz</dd></div>
          <div><dt>Max area fraction</dt><dd>{fmtNum(segment.max_area_fraction, 2)} of the analysis window</dd></div>
          <div><dt>Max ΔL</dt><dd>{fmtNum(segment.max_delta_L, 3)}</dd></div>
          <div><dt>Severity</dt><dd>{fmtNum(segment.severity_score, 2)}</dd></div>
          <div><dt>Regions</dt><dd>
            {segment.regions.map((r, i) => (
              <span key={i} className="region">x {r.x.toFixed(2)}, y {r.y.toFixed(2)}, w {r.w.toFixed(2)}, h {r.h.toFixed(2)}</span>
            ))}
          </dd></div>
          {remediation && (
            <>
              <div><dt>Remediation</dt><dd>{remediation.outcome.replace('_', ' ')} · {strategyLabel(remediation.strategy)}</dd></div>
              <div><dt>Params</dt><dd>{paramsText(remediation.params)}</dd></div>
              <div><dt>Attempts</dt><dd>{remediation.attempts.length}</dd></div>
              {remediation.quality && (
                <div><dt>Quality</dt><dd>
                  SSIM overall {fmtNum(remediation.quality.ssim_overall)}, inside {fmtNum(remediation.quality.ssim_inside)}, outside {fmtNum(remediation.quality.ssim_outside)}; mean |ΔL| inside {fmtNum(remediation.quality.mean_abs_dL_inside)}
                </dd></div>
              )}
            </>
          )}
        </dl>
        <StillFrame jobId={jobId} segment={segment} />
      </div>
      <h3>Luminance inside the region</h3>
      {detail?.region_series ? (
        <RegionSeriesPlot series={detail.region_series} segment={segment} />
      ) : (
        <p className="muted small">Region series loads from the segments endpoint once analysis is available.</p>
      )}
    </div>
  );
}
