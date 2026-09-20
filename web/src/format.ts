// Small formatting helpers shared by the components.
import type { HazardType, JobStatus } from './types';

export const fmtSeconds = (s: number, digits = 2) => `${s.toFixed(digits)} s`;

export const fmtRange = (a: number, b: number) => `${a.toFixed(2)}–${b.toFixed(2)} s`;

export function fmtNum(x: number | null | undefined, digits = 3): string {
  if (x === null || x === undefined || Number.isNaN(x)) return '–';
  return x.toFixed(digits);
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export const HAZARD_LABEL: Record<HazardType, string> = {
  general: 'general flash',
  red: 'red flash',
  pattern: 'spatial pattern',
};

/** Strategy catalogue (steadyframe/remediate/registry.py). Names shown next to the id. */
export const STRATEGY_NAME: Record<string, string> = {
  S1: 'temporal low-pass',
  S2: 'luminance swing compression',
  S3: 'red desaturation',
  S4: 'global smoothing',
  S5: 'frame hold rate limit',
  S6: 'static warning card',
};

export const strategyLabel = (id: string | null | undefined) =>
  id ? `${id} ${STRATEGY_NAME[id] ? `(${STRATEGY_NAME[id]})` : ''}`.trim() : '–';

export const STATUS_LABEL: Record<JobStatus, string> = {
  created: 'Created',
  uploaded: 'Uploaded',
  queued: 'Queued',
  analyzing: 'Analyzing',
  remediating: 'Remediating',
  rendering: 'Rendering',
  passed: 'Remediated: passes thresholds',
  failed_verification: 'Could not remediate within budget',
  needs_approval: 'Waiting for your approval',
  no_hazards: 'No hazards found',
  error: 'Error',
};

export function paramsText(params: Record<string, unknown> | undefined | null): string {
  if (!params) return '–';
  const entries = Object.entries(params);
  if (!entries.length) return 'defaults';
  return entries.map(([k, v]) => `${k}=${typeof v === 'number' ? +v.toFixed(4) : String(v)}`).join(', ');
}
