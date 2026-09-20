// Job polling (GET /jobs/{id} every POLL_MS until terminal) plus the two dependent fetches.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { POLL_MS } from '../config';
import { TERMINAL_STATUSES, type Job, type SegmentDetail, type TraceRecord } from '../types';

export function useJob(jobId: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const poll = async () => {
      try {
        const j = await api.getJob(jobId);
        if (cancelled) return;
        failures = 0;
        setJob(j);
        setError(null);
        if (!TERMINAL_STATUSES.has(j.status)) timer = setTimeout(poll, POLL_MS);
      } catch (e) {
        if (cancelled) return;
        failures += 1;
        setError(e instanceof Error ? e.message : String(e));
        // keep trying, but back off a little so a dead API does not hammer the browser
        if (failures < 30) timer = setTimeout(poll, POLL_MS * Math.min(failures, 5));
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, tick]);

  return { job, error, refresh };
}

/** Segment details refetch whenever the job status changes (analysis appears, remediation lands). */
export function useSegments(jobId: string, status: Job['status'] | undefined, hasAnalysis: boolean) {
  const [segments, setSegments] = useState<SegmentDetail[] | null>(null);
  useEffect(() => {
    if (!hasAnalysis) return;
    let cancelled = false;
    api
      .getSegments(jobId)
      .then((r) => {
        if (!cancelled) setSegments(r.segments);
      })
      .catch(() => {
        if (!cancelled) setSegments(null);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, status, hasAnalysis]);
  return segments;
}

/** Incremental trace: GET /trace?after=<seq> while the job is running, one final fetch after. */
export function useTrace(jobId: string, status: Job['status'] | undefined) {
  // records are tagged with the job they belong to, so switching jobs needs no reset effect
  const [state, setState] = useState<{ forJob: string; records: TraceRecord[]; complete: boolean }>({
    forJob: jobId,
    records: [],
    complete: false,
  });
  const lastSeq = useRef({ job: jobId, seq: 0 });
  const running = status !== undefined && !TERMINAL_STATUSES.has(status);

  useEffect(() => {
    if (status === undefined) return;
    if (lastSeq.current.job !== jobId) lastSeq.current = { job: jobId, seq: 0 };
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const fetchMore = async () => {
      try {
        const r = await api.getTrace(jobId, lastSeq.current.seq);
        if (cancelled) return;
        setState((prev) => {
          const base = prev.forJob === jobId ? prev.records : [];
          const seen = new Set(base.map((x) => x.seq));
          const merged = [...base, ...r.records.filter((x) => !seen.has(x.seq))].sort((a, b) => a.seq - b.seq);
          lastSeq.current = { job: jobId, seq: merged.length ? merged[merged.length - 1].seq : 0 };
          return { forJob: jobId, records: merged, complete: r.complete };
        });
        if (running && !r.complete) timer = setTimeout(fetchMore, POLL_MS);
      } catch {
        if (!cancelled && running) timer = setTimeout(fetchMore, POLL_MS * 2);
      }
    };
    void fetchMore();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, status, running]);

  const current = state.forJob === jobId;
  return { records: current ? state.records : [], complete: current ? state.complete : false };
}
