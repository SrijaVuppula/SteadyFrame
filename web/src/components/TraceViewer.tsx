// Agent trace viewer. Pairs tool_call/tool_result records into steps and highlights every
// verify result that changed what happened next. That highlight is the award evidence: an
// OpenCV measurement (the re-analysis) altering a later tool call.
import { useMemo, useState } from 'react';
import { fmtNum, paramsText } from '../format';
import { PERCEPTION, buildSteps, type Step } from '../traceSteps';
import type { TraceRecord } from '../types';
import { JsonBlock } from './JsonBlock';

function summarise(step: Step): string {
  const r = step.rec;
  const a = (r.args ?? {}) as Record<string, unknown>;
  const res = (step.result?.result ?? {}) as Record<string, unknown>;
  switch (r.name) {
    case 'analyze_video':
      return res.verdict ? `verdict ${String(res.verdict)}, ${Array.isArray(res.segments) ? res.segments.length : '?'} segment(s)` : 'analysing…';
    case 'get_segment_detail':
      return res.type
        ? `${String(res.type)} ${String(res.peak_flash_rate_hz)} Hz, area ${String(res.max_area_fraction)}, ΔL ${String(res.max_delta_L)}, ${String(res.iterations_left_for_segment ?? '?')} iteration(s) left`
        : `segment ${String(a.segment_id)}`;
    case 'apply_remediation': {
      const q = res.quality as Record<string, number> | undefined;
      return `${String(a.strategy)} on ${String(a.segment_id)}${res.candidate_id ? ` → ${String(res.candidate_id)}, params ${paramsText(res.params as Record<string, unknown>)}, SSIM ${fmtNum(q?.ssim_overall)}` : ''}`;
    }
    case 'verify_candidate':
      return res.reason ? String(res.reason) : `candidate ${String(a.candidate_id)}`;
    case 'accept_candidate':
      return `${String(a.candidate_id)}${res.strategy ? ` (${String(res.strategy)})` : ''}`;
    case 'request_human_approval':
      return `${String(a.reason ?? '')} · ${Array.isArray(a.options) ? a.options.length : 0} option(s)`;
    case 'finalize':
      return res.status ? `${String(res.status)}, ${String(res.frames_out)} frames, sync ${res.sync_ok ? 'ok' : 'off'}` : 'rendering…';
    default:
      return '';
  }
}

function ModelTurn({ r }: { r: TraceRecord }) {
  // the worker's trace writes `tool_calls: [{name, input}]` (steadyframe/agent/loop.py);
  // older fixtures used a single `tool_use`. Accept both.
  const calls = (Array.isArray(r.tool_calls) ? r.tool_calls : r.tool_use ? [r.tool_use] : []) as {
    name?: string;
    input?: unknown;
  }[];
  const tool = calls[0];
  return (
    <div>
      {typeof r.text === 'string' && <p className="model-text">{r.text}</p>}
      {tool?.name && (
        <p className="muted small">
          → calls <code>{calls.map((c) => c.name).join(', ')}</code>
          {typeof r.input_tokens === 'number' ? ` · ${r.input_tokens} in / ${String(r.output_tokens)} out tokens` : ''}
          {typeof r.model === 'string' ? ` · ${r.model}` : ''}
        </p>
      )}
    </div>
  );
}

export function TraceViewer({ records, complete }: { records: TraceRecord[]; complete: boolean }) {
  const [showPerception, setShowPerception] = useState(true);
  const [expandAll, setExpandAll] = useState(false);
  const steps = useMemo(() => buildSteps(records), [records]);
  const visible = showPerception ? steps : steps.filter((s) => !PERCEPTION.has(s.rec.name));

  const nCalls = steps.filter((s) => s.rec.kind === 'tool_call').length;
  const nModel = steps.filter((s) => s.rec.kind === 'model').length;
  const nVerify = steps.filter((s) => s.rec.name === 'verify_candidate').length;
  const nChanged = steps.filter((s) => s.rec.name === 'verify_candidate' && s.highlight && s.highlight.tone !== 'ok').length;

  if (!records.length) {
    return <p className="muted">{complete ? 'The trace is empty.' : 'Waiting for the first trace records…'}</p>;
  }

  return (
    <div className="trace">
      <p className="trace-summary">
        {nCalls} tool calls · {nVerify} verifications · {nModel} model turns ·{' '}
        <strong>{nChanged}</strong> verify result{nChanged === 1 ? '' : 's'} that changed the next action
        {complete ? '' : ' · still running'}
      </p>
      <div className="trace-controls">
        <label><input type="checkbox" checked={showPerception} onChange={(e) => setShowPerception(e.target.checked)} /> Show perception calls (analyze_video, get_segment_detail)</label>
        <label><input type="checkbox" checked={expandAll} onChange={(e) => setExpandAll(e.target.checked)} /> Expand all JSON</label>
      </div>
      <ol className="trace-list" aria-label="Trace records in order">
        {visible.map((s) => {
          const r = s.rec;
          const kindClass = r.kind === 'tool_call' ? (PERCEPTION.has(r.name) ? 'perceive' : 'act') : r.kind;
          return (
            <li key={s.key} className={`trace-step kind-${kindClass}${s.highlight ? ` hl-${s.highlight.tone}` : ''}`}>
              <div className="trace-head">
                <span className="trace-seq" aria-label={`record ${r.seq}`}>#{r.seq}</span>
                <span className="trace-time">{fmtNum(r.t_rel_s, 2)} s</span>
                <span className="trace-kind">{r.kind === 'tool_call' ? 'tool' : r.kind}</span>
                <strong className="trace-name">{r.name}</strong>
                {typeof r.iteration === 'number' && <span className="muted">iter {r.iteration}</span>}
                {r.by && <span className="muted">by {r.by}</span>}
                {r.kind === 'tool_call' && !s.result && <span className="muted">pending…</span>}
              </div>
              {r.kind === 'model' ? <ModelTurn r={r} /> : summarise(s) && <p className="trace-line">{summarise(s)}</p>}
              {s.highlight && <p className={`trace-highlight tone-${s.highlight.tone}`}>{s.highlight.text}</p>}
              {r.kind === 'decision' && (
                <p className="trace-line muted">
                  {Object.entries(r).filter(([k]) => !['seq', 'job_id', 't_rel_s', 'ts', 'kind', 'name'].includes(k))
                    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(' · ')}
                </p>
              )}
              <div className="trace-json">
                {r.args !== undefined && <JsonBlock label="args" value={r.args} open={expandAll} />}
                {s.result && <JsonBlock label={s.result.error ? 'result (error)' : 'result'} value={s.result.error ? { error: s.result.error, ...s.result.result } : s.result.result} open={expandAll} />}
                {r.kind !== 'tool_call' && r.kind !== 'decision' && <JsonBlock label="record" value={r} open={expandAll} />}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
