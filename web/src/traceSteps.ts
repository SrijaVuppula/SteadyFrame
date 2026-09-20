// Pure trace analysis for the viewer: pair tool_call/tool_result into steps and mark every
// verify result that changed what happened next (the award-evidence highlight).
import { paramsText } from './format';
import type { TraceRecord } from './types';

export type Tone = 'fail' | 'approval' | 'ok' | 'error' | 'info';

export interface Step {
  key: string;
  rec: TraceRecord; // the primary record (tool_call for tools)
  result?: TraceRecord;
  highlight?: { tone: Tone; text: string };
}

export const PERCEPTION = new Set(['analyze_video', 'get_segment_detail']);

function describeCall(r: TraceRecord | undefined): string {
  if (!r) return 'end of trace';
  const a = (r.args ?? {}) as Record<string, unknown>;
  switch (r.name) {
    case 'apply_remediation':
      return `try ${String(a.strategy)} on ${String(a.segment_id)}${Object.keys((a.params as object) ?? {}).length ? ` (${paramsText(a.params as Record<string, unknown>)})` : ''}`;
    case 'request_human_approval':
      return `ask a human about ${String(a.segment_id)}`;
    case 'accept_candidate':
      return `accept ${String(a.candidate_id)}`;
    case 'verify_candidate':
      return `verify ${String(a.candidate_id)}`;
    case 'finalize':
      return 'finalize the output';
    default:
      return r.name;
  }
}

export function buildSteps(records: TraceRecord[]): Step[] {
  const steps: Step[] = [];
  for (const r of records) {
    if (r.kind === 'tool_result') {
      // attach to the most recent unanswered call of the same name
      for (let i = steps.length - 1; i >= 0; i--) {
        const s = steps[i];
        if (s.rec.kind === 'tool_call' && s.rec.name === r.name && !s.result) {
          s.result = r;
          break;
        }
      }
      continue;
    }
    steps.push({ key: `${r.seq}`, rec: r });
  }
  // second pass: highlights that need to look ahead
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    const nextCall = steps.slice(i + 1).find((x) => x.rec.kind === 'tool_call')?.rec;
    if (s.rec.kind === 'tool_call' && s.rec.name === 'verify_candidate' && s.result) {
      const res = (s.result.result ?? {}) as Record<string, unknown>;
      if (s.result.error) s.highlight = { tone: 'error', text: `verify errored → next: ${describeCall(nextCall)}` };
      else if (res.passes_for_type === false)
        s.highlight = { tone: 'fail', text: `verify: still failing → next: ${describeCall(nextCall)}` };
      else if (res.requires_approval)
        s.highlight = { tone: 'approval', text: `verify: passes but needs approval → next: ${describeCall(nextCall)}` };
      else s.highlight = { tone: 'ok', text: `verify: passes → next: ${describeCall(nextCall)}` };
    } else if (s.rec.kind === 'decision') {
      const note = typeof s.rec.note === 'string' ? s.rec.note : '';
      if (s.rec.name === 'paused') s.highlight = { tone: 'approval', text: 'paused for human approval' };
      else if (/escalat|still fail|rejected/i.test(note)) s.highlight = { tone: 'fail', text: note };
      else if (s.rec.name === 'accept') s.highlight = { tone: 'ok', text: `accepted ${String(s.rec.candidate_id)} (${String(s.rec.strategy)})` };
      else if (s.rec.name === 'finalize') s.highlight = { tone: 'info', text: `finalize: ${String(s.rec.status)}, after verdict ${String(s.rec.after_verdict)}` };
      else if (s.rec.name === 'human_approval') {
        const d = s.rec.decision as { approved?: boolean; candidate_id?: string } | undefined;
        s.highlight = { tone: d?.approved ? 'ok' : 'fail', text: `human ${d?.approved ? 'approved' : 'rejected'} ${d?.candidate_id ?? ''}` };
      }
    } else if (s.rec.kind === 'error' || (s.result && s.result.error)) {
      s.highlight = { tone: 'error', text: String(s.rec.error ?? s.result?.error ?? 'error') };
    }
  }
  return steps;
}

