// Types mirroring docs/API.md. Keep this file in sync with the API doc; the mock client
// in mock.ts and the fixtures under fixtures/ are checked against these shapes by tsc.

export type Profile = 'wcag' | 'broadcast';
export type Policy = 'fixed' | 'agent';
export type Verdict = 'pass' | 'warn' | 'fail';
export type HazardType = 'general' | 'red' | 'pattern';

export type JobStatus =
  | 'created'
  | 'uploaded'
  | 'queued'
  | 'analyzing'
  | 'remediating'
  | 'rendering'
  | 'passed'
  | 'failed_verification'
  | 'needs_approval'
  | 'no_hazards'
  | 'error';

/** Statuses after which the job no longer changes on its own (needs_approval waits for us). */
export const TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  'passed',
  'failed_verification',
  'needs_approval',
  'no_hazards',
  'error',
]);

export type DownloadKind = 'video' | 'report' | 'analysis' | 'trace' | 'plot' | 'summary';

export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** analysis.json segment (steadyframe/schema.py SEGMENT). */
export interface Segment {
  id: string;
  type: HazardType;
  verdict: Verdict;
  start_frame: number;
  end_frame: number;
  start_s: number;
  end_s: number;
  peak_flash_rate_hz: number;
  max_area_fraction: number;
  max_delta_L: number;
  regions: Region[];
  severity_score: number;
}

export interface PerSecond {
  second: number;
  verdict: Verdict;
  general: Verdict;
  red: Verdict;
  pattern?: Verdict;
  max_flash_rate_hz?: number;
  max_area_fraction?: number;
}

/** Per-frame series; all arrays share the length of `t`. */
export interface Timeline {
  t: number[];
  mean_L: number[];
  general_rate_hz: number[];
  red_rate_hz: number[];
  general_area?: number[];
  red_area?: number[];
}

export interface AnalysisSummary {
  verdict: Verdict;
  per_second: PerSecond[];
  segments: Segment[];
  timeline?: Timeline;
}

/** Quality metrics from steadyframe/remediate/quality.py. Keys vary by strategy. */
export interface Quality {
  ssim_overall?: number | null;
  ssim_inside?: number | null;
  ssim_outside?: number | null;
  psnr_outside_db?: number | null;
  psnr_outside_is_lossless?: boolean;
  mean_abs_dL_inside?: number | null;
  temporal_step_before?: number | null;
  temporal_step_after?: number | null;
  temporal_smoothness_gain?: number | null;
  frames?: number;
  [k: string]: number | boolean | null | undefined;
}

export type Params = Record<string, number | string | boolean>;

export interface AttemptVerified {
  passes_for_type: boolean;
  verdict: Verdict;
  ssim_overall: number | null;
  requires_approval: boolean;
}

export interface Attempt {
  candidate_id: string;
  strategy: string;
  params: Params;
  verified?: AttemptVerified | null;
}

export type SegmentOutcome = 'accepted' | 'unresolved' | 'pending_approval' | 'open' | string;

export interface ApprovalDecision {
  approved: boolean;
  candidate_id?: string | null;
  by?: string;
}

export interface ApprovalRecord {
  segment_id: string;
  reason: string;
  options: ApprovalOption[];
  last_resort?: boolean;
  requested_at?: number;
  decision?: ApprovalDecision | null;
}

export interface RemediationSegment {
  segment_id: string;
  type: HazardType;
  start_s?: number;
  end_s?: number;
  outcome: SegmentOutcome;
  strategy: string | null;
  params: Params;
  attempts: Attempt[];
  approval?: ApprovalRecord | null;
  quality: Quality | null;
}

export interface Remediation {
  status: JobStatus | string;
  iterations: number;
  runtime_s: number;
  quality: Quality | null;
  segments: RemediationSegment[];
}

export interface ApprovalOption {
  candidate_id: string;
  strategy: string;
  params: Params;
  quality: Quality | null;
  passes?: boolean | null;
}

export interface PendingApproval {
  segment_id: string;
  reason: string;
  options: ApprovalOption[];
  last_resort?: boolean;
}

export interface JobInput {
  filename: string;
  width?: number;
  height?: number;
  fps?: number;
  duration_s?: number;
  has_audio?: boolean;
}

export interface JobProgress {
  stage: string;
  detail?: string;
  fraction: number;
}

export interface ToolInfo {
  version: string;
  opencv: string;
}

export interface Job {
  job_id: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  profile: Profile;
  policy: Policy;
  conservative: boolean;
  input: JobInput | null;
  progress: JobProgress | null;
  before: AnalysisSummary | null;
  after: AnalysisSummary | null;
  remediation: Remediation | null;
  pending_approvals: PendingApproval[];
  downloads: Record<DownloadKind, boolean>;
  error: string | null;
  tool: ToolInfo;
}

/** GET /jobs/{id}/segments item. */
export interface SegmentDetail extends Segment {
  /** null until the worker has the per-frame series for this job (service/core.py). */
  region_series: { t: number[]; L: number[] } | null;
  remediation: RemediationSegment | null;
}

export type TraceKind = 'tool_call' | 'tool_result' | 'decision' | 'model' | 'error' | 'job' | 'warning';

/** One line of trace.jsonl (steadyframe/agent/trace.py). Extra fields vary per record. */
export interface TraceRecord {
  seq: number;
  job_id: string;
  t_rel_s: number;
  ts: string;
  kind: TraceKind;
  name: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string | null;
  iteration?: number | null;
  by?: string;
  [k: string]: unknown;
}

export interface TraceResponse {
  records: TraceRecord[];
  complete: boolean;
}

export interface Sample {
  id: string;
  name: string;
  description: string;
  hazard_types: HazardType[];
  duration_s: number;
  warning: boolean;
}

export interface Health {
  ok: boolean;
  opencv: string;
  version: string;
  mode: 'aws' | 'local';
}

export interface CreateJobRequest {
  filename: string;
  content_type: string;
  size_bytes: number;
  profile: Profile;
  policy: Policy;
  conservative: boolean;
}

export interface UploadTarget {
  method: 'PUT';
  url: string;
  headers: Record<string, string>;
}

export interface CreateJobResponse {
  job_id: string;
  upload: UploadTarget;
}

export interface JobFromSampleRequest {
  sample_id: string;
  profile: Profile;
  policy: Policy;
  conservative?: boolean;
}

export interface JobRef {
  job_id: string;
  status: JobStatus;
}

export interface ApproveRequest {
  segment_id: string;
  approved: boolean;
  candidate_id: string | null;
}

export interface DownloadResponse {
  url: string;
  kind: DownloadKind;
}

export interface SegmentsResponse {
  segments: SegmentDetail[];
}
