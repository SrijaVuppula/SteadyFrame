// Fixture-backed ApiClient. Used when VITE_MOCK_API=1 or ?fixture=1: `npm run a11y` and
// offline demos hit this instead of the network. Jobs started here walk through the real
// status sequence on a timer so the progress UI and live trace can be exercised.
import type { ApiClient } from './api';
import { ApiError } from './api';
import type { Job, JobStatus, Sample, SegmentsResponse, TraceRecord, TraceResponse } from './types';
import samplesJson from './fixtures/samples.json';
import jobPassed from './fixtures/job_passed.json';
import segmentsPassed from './fixtures/segments_passed.json';
import tracePassed from './fixtures/trace_passed.json';
import jobApproval from './fixtures/job_approval.json';
import segmentsApproval from './fixtures/segments_approval.json';
import traceApproval from './fixtures/trace_approval.json';
import jobRed from './fixtures/job_red.json';
import segmentsRed from './fixtures/segments_red.json';
import traceRed from './fixtures/trace_red.json';

interface Fixture {
  job: Job;
  segments: SegmentsResponse;
  trace: TraceResponse;
}

const FIXTURES: Record<string, Fixture> = {
  // JSON imports infer literal shapes (optional keys become `?: undefined`), so go via unknown.
  'fx-passed': { job: jobPassed as unknown as Job, segments: segmentsPassed as unknown as SegmentsResponse, trace: tracePassed as unknown as TraceResponse },
  'fx-approval': { job: jobApproval as unknown as Job, segments: segmentsApproval as unknown as SegmentsResponse, trace: traceApproval as unknown as TraceResponse },
  'fx-red': { job: jobRed as unknown as Job, segments: segmentsRed as unknown as SegmentsResponse, trace: traceRed as unknown as TraceResponse },
};

const SAMPLE_TO_FIXTURE: Record<string, string> = {
  sample_two_segments: 'fx-passed',
  sample_two_segments_agent: 'fx-approval',
  sample_red_strobe_region: 'fx-red',
};

/** Stages a simulated job walks through, with the seconds spent in each. */
const STAGES: Array<[JobStatus, number, string]> = [
  ['queued', 1.5, 'waiting for a worker'],
  ['analyzing', 3, 'FlashAnalyzer streaming frames'],
  ['remediating', 4, 'segment g000 attempt 1 (S1)'],
  ['rendering', 1.5, 'writing safe.mp4, remuxing audio'],
];
const SIM_TOTAL = STAGES.reduce((a, [, s]) => a + s, 0);

interface SimJob {
  target: string; // fixture id whose terminal state we end in
  startedAt: number | null; // null until POST /start
  filename: string;
  profile: Job['profile'];
  policy: Job['policy'];
  conservative: boolean;
  decided?: 'approved' | 'rejected'; // after POST /approve
  decidedAt?: number;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export function createMockClient(): ApiClient {
  const sims = new Map<string, SimJob>();
  let counter = 0;

  function simState(id: string, sim: SimJob): Job {
    const fx = FIXTURES[sim.target];
    const base = clone(fx.job);
    base.job_id = id;
    base.input = { ...base.input!, filename: sim.filename };
    base.profile = sim.profile;
    base.policy = sim.policy;
    base.conservative = sim.conservative;
    const now = Date.now();
    base.created_at = new Date(now).toISOString();
    base.updated_at = base.created_at;

    if (sim.decided) {
      // after an approval decision the job re-queues briefly and then finishes
      const dt = (now - (sim.decidedAt ?? now)) / 1000;
      if (dt < 3) {
        return { ...base, status: 'queued', pending_approvals: [], after: null,
          progress: { stage: 'queued', detail: 'resuming from work.tar', fraction: 0.85 } };
      }
      if (sim.decided === 'approved') {
        const done = clone(FIXTURES['fx-passed'].job);
        done.job_id = id; done.policy = sim.policy; done.profile = sim.profile; done.input = base.input;
        done.remediation!.segments[1] = { ...done.remediation!.segments[1], strategy: 'S5',
          params: { max_rate_hz: 2 }, attempts: base.remediation!.segments[1].attempts,
          approval: { ...base.remediation!.segments[1].approval!, decision: { approved: true, candidate_id: 'g001-c3', by: 'human' } } };
        return done;
      }
      return { ...base, status: 'failed_verification', pending_approvals: [],
        progress: { stage: 'done', detail: 'segment g001 unresolved after human rejection', fraction: 1 },
        remediation: { ...base.remediation!, status: 'failed_verification',
          segments: base.remediation!.segments.map((s) => s.segment_id === 'g001' ? { ...s, outcome: 'unresolved' } : s) },
        downloads: { ...base.downloads, report: true } };
    }

    if (sim.startedAt === null) {
      return { ...base, status: 'created', progress: null, before: null, after: null, remediation: null,
        pending_approvals: [], downloads: { video: false, report: false, analysis: false, trace: false, plot: false, summary: false } };
    }
    const elapsed = (now - sim.startedAt) / 1000;
    if (elapsed >= SIM_TOTAL) return base;
    let acc = 0;
    for (const [status, dur, detail] of STAGES) {
      if (elapsed < acc + dur) {
        const analysed = status !== 'queued' && status !== 'analyzing';
        return { ...base, status, after: null, remediation: null, pending_approvals: [],
          before: analysed ? base.before : null,
          progress: { stage: status, detail, fraction: +(elapsed / SIM_TOTAL).toFixed(2) },
          downloads: { video: false, report: false, analysis: analysed, trace: analysed, plot: false, summary: false } };
      }
      acc += dur;
    }
    return base;
  }

  function resolveJob(id: string): Job {
    const sim = sims.get(id);
    if (sim) return simState(id, sim);
    const fx = FIXTURES[id];
    if (!fx) throw new ApiError(404, `unknown job ${id}`);
    return clone(fx.job);
  }

  function fixtureFor(id: string): Fixture {
    const sim = sims.get(id);
    const fx = FIXTURES[sim ? sim.target : id];
    if (!fx) throw new ApiError(404, `unknown job ${id}`);
    return fx;
  }

  function blobUrl(kind: string, id: string): string {
    const fx = fixtureFor(id);
    let text: string;
    let type = 'application/json';
    if (kind === 'analysis') text = JSON.stringify({ ...fx.job.before, tool: fx.job.tool }, null, 1);
    else if (kind === 'report') text = JSON.stringify(fx.job.remediation, null, 1);
    else if (kind === 'trace') { text = fx.trace.records.map((r) => JSON.stringify(r)).join('\n'); type = 'application/x-ndjson'; }
    else { text = `${kind} is not bundled in fixture mode (binary output of the worker).`; type = 'text/plain'; }
    return URL.createObjectURL(new Blob([text], { type }));
  }

  return {
    health: async () => ({ ok: true, opencv: '5.0.0', version: '0.1.0', mode: 'local' }),
    listSamples: async () => { await sleep(150); return samplesJson as Sample[]; },
    createJob: async (req) => {
      await sleep(150);
      const id = `fx-run-${++counter}`;
      sims.set(id, { target: 'fx-passed', startedAt: null, filename: req.filename,
        profile: req.profile, policy: req.policy, conservative: req.conservative });
      return { job_id: id, upload: { method: 'PUT', url: `/jobs/${id}/upload`, headers: { 'Content-Type': req.content_type } } };
    },
    upload: async (_target, _file, onProgress) => {
      for (let i = 1; i <= 5; i++) { await sleep(120); onProgress?.(i / 5); }
    },
    startJob: async (id) => {
      const sim = sims.get(id);
      if (!sim) throw new ApiError(404, `unknown job ${id}`);
      sim.startedAt = Date.now();
      return { job_id: id, status: 'queued' };
    },
    jobFromSample: async (req) => {
      await sleep(150);
      const target = SAMPLE_TO_FIXTURE[req.sample_id];
      if (!target) throw new ApiError(404, `unknown sample ${req.sample_id}`);
      const id = `fx-run-${++counter}`;
      sims.set(id, { target, startedAt: Date.now(), filename: FIXTURES[target].job.input!.filename,
        profile: req.profile, policy: req.policy, conservative: !!req.conservative });
      return { job_id: id, status: 'queued' };
    },
    getJob: async (id) => { await sleep(80); return resolveJob(id); },
    getSegments: async (id) => {
      const job = resolveJob(id);
      if (!job.before) return { segments: [] };
      return clone(fixtureFor(id).segments);
    },
    getTrace: async (id, after = 0) => {
      const job = resolveJob(id);
      const all = fixtureFor(id).trace.records as TraceRecord[];
      const sim = sims.get(id);
      let visible = all;
      let complete = true;
      if (sim && sim.startedAt !== null && !sim.decided) {
        // reveal records in step with the simulated progress
        const elapsed = (Date.now() - sim.startedAt) / 1000;
        const frac = Math.min(1, Math.max(0, (elapsed - STAGES[0][1]) / (SIM_TOTAL - STAGES[0][1])));
        visible = all.slice(0, Math.floor(all.length * frac));
        complete = job.status !== 'queued' && job.status !== 'analyzing' && job.status !== 'remediating' && job.status !== 'rendering';
      } else if (job.status === 'created') {
        visible = [];
        complete = false;
      }
      return { records: clone(visible.filter((r) => r.seq > after)), complete };
    },
    approve: async (id, body) => {
      const sim = sims.get(id);
      if (!sim) {
        // a bare fixture id: make it behave like a started simulation so the decision shows
        sims.set(id, { target: id, startedAt: 0, filename: FIXTURES[id]?.job.input?.filename ?? 'clip.mp4',
          profile: 'wcag', policy: 'agent', conservative: false });
      }
      const s = sims.get(id)!;
      s.decided = body.approved ? 'approved' : 'rejected';
      s.decidedAt = Date.now();
      return { job_id: id, status: 'queued' };
    },
    downloadUrl: async (id, kind) => ({ url: blobUrl(kind, id), kind }),
    frameUrl: (_id, segmentId) => `/fixtures/${encodeURIComponent(segmentId)}.png`,
    originalUrl: async () => null,
  };
}
