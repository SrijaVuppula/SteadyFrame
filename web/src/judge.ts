// Recorded jobs for the judge page. `python -m eval.judge_bundle` runs the worker's own code
// on three clips and writes their real outputs to public/judge/; nothing here is computed in
// the browser and nothing is hand-written.
import type { Job, SegmentsResponse, TraceResponse } from './types';

export const REPO_URL = 'https://github.com/SrijaVuppula/SteadyFrame';
/** Filled in once the video is public. Empty hides the link. */
export const VIDEO_URL = '';

export interface JudgeCase {
  id: string;
  clip: string;
  title: string;
  blurb: string;
  policy: string;
  planner: string | null;
  status: string;
  verdict_before: string | null;
  verdict_after: string | null;
  segments: number;
  iterations: number | null;
  model_turns: number | null;
  files: string[];
}

export interface JudgeResult {
  label: string;
  text: string;
  source: string;
}

export interface GuardrailRow {
  attack: string;
  what: string;
  refused: string;
  fallback: string;
  status: string;
  fresh_verdict: string;
  held: boolean;
  false_pass: boolean;
}

export interface JudgeIndex {
  generated_at: string;
  git: string;
  opencv: string;
  offline: boolean;
  cases: JudgeCase[];
  results: JudgeResult[];
  guardrails: { summary: { runs: number; held: number; false_pass: number; refused_calls: number }; rows: GuardrailRow[] } | null;
  limits: string[];
}

export interface JudgeJob {
  job: Job;
  segments: SegmentsResponse;
  trace: TraceResponse;
}

export const isJudgeJob = (id: string) => id.startsWith('jd-');
export const judgeFile = (id: string, name: string) => `/judge/${encodeURIComponent(id)}/${name}`;

/** CloudFront answers a missing path with index.html (SPA routing), so check the type. */
async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  const type = res.headers.get('content-type') ?? '';
  if (!res.ok || !type.includes('json')) throw new Error(`${url}: not available`);
  return (await res.json()) as T;
}

let indexPromise: Promise<JudgeIndex> | null = null;
export function loadIndex(): Promise<JudgeIndex> {
  indexPromise ??= getJson<JudgeIndex>('/judge/index.json').catch((e) => {
    indexPromise = null;
    throw e;
  });
  return indexPromise;
}

const jobs = new Map<string, Promise<JudgeJob>>();
export function loadJudgeJob(id: string): Promise<JudgeJob> {
  let p = jobs.get(id);
  if (!p) {
    p = Promise.all([
      getJson<Job>(judgeFile(id, 'job.json')),
      getJson<SegmentsResponse>(judgeFile(id, 'segments.json')),
      getJson<TraceResponse>(judgeFile(id, 'trace.json')),
    ]).then(([job, segments, trace]) => ({ job, segments, trace }));
    p.catch(() => jobs.delete(id));
    jobs.set(id, p);
  }
  return p;
}

/** File name in the bundle for each download kind. */
export const BUNDLED_FILE: Record<string, string> = {
  video: 'safe.mp4',
  report: 'report.json',
  trace: 'trace.jsonl',
  plot: 'plot.png',
  summary: 'summary.html',
  record: 'record.html',
  record_json: 'record.json',
  warnings: 'hazards.vtt',
};
