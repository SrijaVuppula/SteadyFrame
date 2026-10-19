// Pure helpers for the /judge tour components: screen-position words, short sentences, flash
// rates from a timeline, and the conversation (planner and analyzer turns) built from a trace.
import { paramsText } from './format';
import type { Segment, Timeline, TraceRecord } from './types';

export function where(s: Segment): string {
  const r = s.regions;
  if (!r.length) return 'on screen';
  const x0 = Math.min(...r.map((q) => q.x)), y0 = Math.min(...r.map((q) => q.y));
  const x1 = Math.max(...r.map((q) => q.x + q.w)), y1 = Math.max(...r.map((q) => q.y + q.h));
  if ((x1 - x0) * (y1 - y0) >= 0.8) return 'whole screen';
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const col = cx < 1 / 3 ? 'left' : cx > 2 / 3 ? 'right' : '';
  const row = cy < 1 / 3 ? 'top' : cy > 2 / 3 ? 'bottom' : '';
  return !col && !row ? 'centre' : `${row}${row && col ? '-' : ''}${col}`;
}

/** First n sentences, for chat bubbles; the full text is one click away in the trace. */
export function brief(text: string, n = 2): string {
  // split only where a sentence ends and the next begins, never inside "0.955" or "S4."
  const parts = text.replace(/\s+/g, ' ').trim().split(/(?<=[.!?])\s+(?=[A-Z"'(])/);
  const out = parts.slice(0, n).join(' ').trim();
  return parts.length > n ? `${out} …` : out;
}

export const peak = (xs: number[] | undefined) => (xs && xs.length ? Math.max(...xs) : 0);

/** Per-frame flash rate, general or red, whichever is higher. */
export function flashRate(tl: Timeline): number[] {
  return tl.general_rate_hz.map((g, i) => Math.max(g ?? 0, tl.red_rate_hz?.[i] ?? 0));
}

// ---------------------------------------------------------------- conversation

export interface Bubble {
  key: number;
  who: 'model' | 'policy' | 'analyzer' | 'pipeline';
  text: string;
  action?: string;
  tone?: 'pass' | 'fail';
  pivot?: boolean;
}

export function conversation(records: TraceRecord[]): Bubble[] {
  const out: Bubble[] = [];
  let lastVerifyFailed = false;
  for (const r of records) {
    const res = (r.result ?? {}) as Record<string, unknown>;
    const args = (r.args ?? {}) as Record<string, unknown>;
    if (r.kind === 'model') {
      const calls = (Array.isArray(r.tool_calls) ? r.tool_calls : []) as { name?: string; input?: Record<string, unknown> }[];
      const c = calls[0];
      const text = typeof r.text === 'string' ? r.text.trim() : '';
      if (!text) continue; // bare "verify" / "finalize" turns: the analyzer bubble says it
      const action = c?.name === 'apply_remediation'
        ? `apply ${String(c.input?.strategy)}${c.input?.params ? ` · ${paramsText(c.input.params as Record<string, unknown>)}` : ''}`
        : c?.name ? c.name.replace(/_/g, ' ') : undefined;
      out.push({ key: r.seq, who: 'model', text: brief(text), action, pivot: lastVerifyFailed && c?.name === 'apply_remediation' });
      if (c?.name === 'apply_remediation') lastVerifyFailed = false;
    } else if (r.kind === 'tool_call' && r.name === 'apply_remediation' && r.by !== 'model') {
      out.push({ key: r.seq, who: 'policy', text: lastVerifyFailed ? `${String(args.segment_id)} did not pass, so try the next, stronger strategy.` : `${String(args.segment_id)}: try the least invasive strategy for this hazard.`,
        action: `apply ${String(args.strategy)}${args.params && Object.keys(args.params as object).length ? ` · ${paramsText(args.params as Record<string, unknown>)}` : ''}`,
        pivot: lastVerifyFailed });
      lastVerifyFailed = false;
    } else if (r.kind === 'tool_result' && r.name === 'verify_candidate' && !r.error) {
      const passes = res.passes_for_type === true;
      lastVerifyFailed = !passes;
      out.push({ key: r.seq, who: 'analyzer', tone: passes ? 'pass' : 'fail',
        text: passes
          ? `Re-analysed the candidate: no hazard left in this segment${res.requires_approval ? ', but it changes the picture a lot, so a person has to approve it' : ''}.`
          : `Re-analysed the candidate: ${String(res.reason ?? 'still failing')}.` });
    } else if (r.kind === 'decision' && r.name === 'paused') {
      out.push({ key: r.seq, who: 'pipeline', text: `Paused for a person: ${String(r.reason ?? '')}.` });
    } else if (r.kind === 'decision' && r.name === 'finalize') {
      out.push({ key: r.seq, who: 'pipeline', tone: r.after_verdict === 'pass' ? 'pass' : 'fail',
        text: `Whole file re-verified: ${r.after_verdict === 'pass' ? 'passes' : 'fails'} · ${String(r.frames_out)} frames · audio and timing kept.` });
    }
  }
  return out;
}

