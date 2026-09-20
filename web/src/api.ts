// Typed client for docs/API.md. One interface, two implementations: HTTP and fixtures.
import { API_BASE, MOCK_MODE } from './config';
import { createMockClient } from './mock';
import type {
  ApproveRequest,
  CreateJobRequest,
  CreateJobResponse,
  DownloadKind,
  DownloadResponse,
  Health,
  Job,
  JobFromSampleRequest,
  JobRef,
  Sample,
  SegmentsResponse,
  TraceResponse,
  UploadTarget,
} from './types';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface ApiClient {
  health(): Promise<Health>;
  listSamples(): Promise<Sample[]>;
  createJob(req: CreateJobRequest): Promise<CreateJobResponse>;
  /** PUT the file to the upload target from createJob. onProgress gets 0..1. */
  upload(target: UploadTarget, file: File, onProgress?: (fraction: number) => void): Promise<void>;
  startJob(jobId: string): Promise<JobRef>;
  jobFromSample(req: JobFromSampleRequest): Promise<JobRef>;
  getJob(jobId: string): Promise<Job>;
  getSegments(jobId: string): Promise<SegmentsResponse>;
  getTrace(jobId: string, after?: number): Promise<TraceResponse>;
  approve(jobId: string, body: ApproveRequest): Promise<JobRef>;
  downloadUrl(jobId: string, kind: DownloadKind): Promise<DownloadResponse>;
  /** URL of the server-rendered still (regions outlined). A plain <img> src, never animated. */
  frameUrl(jobId: string, segmentId: string): string;
  /**
   * URL of the original input for the click-through preview, or null when the API does not
   * expose it. docs/API.md has no such endpoint; we try `download?kind=input` and accept a 4xx.
   */
  originalUrl(jobId: string): Promise<string | null>;
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { error?: string };
    if (body && typeof body.error === 'string') return body.error;
  } catch {
    // not JSON
  }
  return `${res.status} ${res.statusText}`;
}

export function createHttpClient(base: string): ApiClient {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(base + path, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new ApiError(res.status, await readError(res));
    return (await res.json()) as T;
  }

  // Local mode returns a path like /jobs/{id}/upload; AWS returns an absolute presigned URL.
  const resolveUrl = (url: string) => (/^https?:\/\//.test(url) ? url : base + url);

  return {
    health: () => call<Health>('GET', '/health'),
    listSamples: () => call<Sample[]>('GET', '/samples'),
    createJob: (req) => call<CreateJobResponse>('POST', '/jobs', req),
    upload: (target, file, onProgress) =>
      new Promise<void>((resolve, reject) => {
        // XHR rather than fetch: we want upload progress for files up to 100 MB.
        const xhr = new XMLHttpRequest();
        xhr.open(target.method || 'PUT', resolveUrl(target.url));
        for (const [k, v] of Object.entries(target.headers ?? {})) xhr.setRequestHeader(k, v);
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
        };
        xhr.onload = () =>
          xhr.status >= 200 && xhr.status < 300
            ? resolve()
            : reject(new ApiError(xhr.status, `upload failed: ${xhr.status} ${xhr.statusText}`));
        xhr.onerror = () => reject(new ApiError(0, 'upload failed: network error'));
        xhr.send(file);
      }),
    startJob: (id) => call<JobRef>('POST', `/jobs/${encodeURIComponent(id)}/start`),
    jobFromSample: (req) => call<JobRef>('POST', '/jobs/from-sample', req),
    getJob: (id) => call<Job>('GET', `/jobs/${encodeURIComponent(id)}`),
    getSegments: (id) => call<SegmentsResponse>('GET', `/jobs/${encodeURIComponent(id)}/segments`),
    getTrace: (id, after) =>
      call<TraceResponse>(
        'GET',
        `/jobs/${encodeURIComponent(id)}/trace${after !== undefined ? `?after=${after}` : ''}`,
      ),
    approve: (id, body) => call<JobRef>('POST', `/jobs/${encodeURIComponent(id)}/approve`, body),
    downloadUrl: (id, kind) =>
      call<DownloadResponse>('GET', `/jobs/${encodeURIComponent(id)}/download?kind=${kind}`),
    frameUrl: (id, segmentId) =>
      `${base}/jobs/${encodeURIComponent(id)}/frames/${encodeURIComponent(segmentId)}.png`,
    originalUrl: async (id) => {
      try {
        const r = await call<DownloadResponse>(
          'GET',
          `/jobs/${encodeURIComponent(id)}/download?kind=input`,
        );
        return r.url || null;
      } catch {
        return null;
      }
    },
  };
}

export const api: ApiClient = MOCK_MODE ? createMockClient() : createHttpClient(API_BASE);
