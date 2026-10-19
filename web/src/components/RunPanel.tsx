// Start a check on a test clip, or drop in your own. Nothing here plays the clip; an uploaded
// file is only inspected for size and duration before it is sent.
import { useEffect, useState } from 'react';
import { api } from '../api';
import { ACCEPTED_EXTENSIONS, MAX_DURATION_S, MAX_UPLOAD_BYTES } from '../config';
import { fmtBytes } from '../format';
import type { Policy, Profile, Sample } from '../types';
import { CLIP_COPY, FALLBACK, clipName } from '../clips';
import { rememberUpload } from '../uploadStore';
import { ClipThumb } from './art';
import { Icon } from './tour';

function extensionOf(name: string): string {
  const m = name.toLowerCase().match(/\.([a-z0-9]+)$/);
  return m ? m[1] : '';
}

/** Read the duration from metadata only. Nothing is rendered or played. */
function probeDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const v = document.createElement('video');
    v.preload = 'metadata';
    v.muted = true;
    const done = (d: number | null) => {
      URL.revokeObjectURL(url);
      v.removeAttribute('src');
      resolve(d);
    };
    v.onloadedmetadata = () => done(Number.isFinite(v.duration) ? v.duration : null);
    v.onerror = () => done(null);
    v.src = url;
  });
}

interface Props {
  onStarted: (jobId: string, label: string, policy: Policy) => void;
}

export function RunPanel({ onStarted }: Props) {
  const [samples, setSamples] = useState<string[]>(FALLBACK);
  const [clip, setClip] = useState(FALLBACK[0]);
  const [policy, setPolicy] = useState<Policy>('agent');
  const [profile, setProfile] = useState<Profile>('wcag');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<{ f: File; problems: string[] } | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    api.listSamples()
      .then((list: Sample[]) => {
        const ids = list.map((s) => s.id).filter((id) => id in CLIP_COPY);
        if (ids.length) setSamples(FALLBACK.filter((id) => ids.includes(id)));
      })
      .catch(() => undefined); // the fallback list is the deployed one
  }, []);

  async function runSample() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.jobFromSample({ sample_id: clip, profile, policy, conservative: false });
      onStarted(r.job_id, clipName(clip), policy);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function choose(f: File | undefined) {
    setError(null);
    if (!f) return setFile(null);
    const problems: string[] = [];
    if (f.size > MAX_UPLOAD_BYTES) problems.push(`The file is ${fmtBytes(f.size)}; the limit is 100 MB.`);
    const ext = extensionOf(f.name);
    if (!ACCEPTED_EXTENSIONS.includes(ext)) problems.push(`.${ext || '?'} files are not accepted (${ACCEPTED_EXTENSIONS.join(', ')}).`);
    setFile({ f, problems });
    const d = await probeDuration(f);
    if (d !== null && d > MAX_DURATION_S) problems.push(`The clip is ${d.toFixed(0)} s; the limit is ${MAX_DURATION_S} s.`);
    setFile({ f, problems: [...problems] });
  }

  async function upload() {
    if (!file || file.problems.length) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createJob({
        filename: file.f.name, content_type: file.f.type || 'video/mp4', size_bytes: file.f.size,
        profile, policy, conservative: false,
      });
      setProgress(0);
      await api.upload(created.upload, file.f, (x) => setProgress(x));
      await api.startJob(created.job_id);
      rememberUpload(created.job_id, file.f);
      onStarted(created.job_id, file.f.name, policy);
      setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  const pick = (id: string) => () => setClip(id);
  return (
    <section className="sf-card sf-run" aria-labelledby="sf-run-h">
      <h2 className="sf-label" id="sf-run-h">Pick a clip</h2>
      <fieldset className="sf-clips">
        <legend className="sr-only">Test clip</legend>
        {samples.map((id) => (
          <label key={id} className={`sf-clip${clip === id ? ' on' : ''}`}>
            <input type="radio" name="clip" value={id} checked={clip === id} onChange={pick(id)} className="sr-only" />
            <ClipThumb id={id} />
            <span className="sf-clip-name">{CLIP_COPY[id][0]}</span>
            <span className="sf-clip-tag">{CLIP_COPY[id][1]}</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="sf-seg">
        <legend>Planner</legend>
        <div className="sf-seg-row">
          <label className={policy === 'agent' ? 'on' : ''}><input type="radio" name="policy" className="sr-only" checked={policy === 'agent'} onChange={() => setPolicy('agent')} />Bedrock model</label>
          <label className={policy === 'fixed' ? 'on' : ''}><input type="radio" name="policy" className="sr-only" checked={policy === 'fixed'} onChange={() => setPolicy('fixed')} />Fixed policy</label>
        </div>
      </fieldset>
      <fieldset className="sf-seg">
        <legend>Standard</legend>
        <div className="sf-seg-row">
          <label className={profile === 'wcag' ? 'on' : ''}><input type="radio" name="profile" className="sr-only" checked={profile === 'wcag'} onChange={() => setProfile('wcag')} />WCAG 2.3.1</label>
          <label className={profile === 'broadcast' ? 'on' : ''}><input type="radio" name="profile" className="sr-only" checked={profile === 'broadcast'} onChange={() => setProfile('broadcast')} />Broadcast</label>
        </div>
      </fieldset>

      <button type="button" className="sf-btn primary sf-go" disabled={busy} onClick={runSample}>
        <Icon name="clapper" />
        <span>{busy && !file ? 'Starting…' : 'Run check'}</span>
        <span className="sf-go-time">{policy === 'agent' ? '~25 s' : '~8 s'}</span>
      </button>

      <label
        className={`sf-drop${dragging ? ' dragging' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); if (!busy) void choose(e.dataTransfer.files?.[0]); }}
      >
        <input type="file" className="sr-only" accept="video/*,.mp4,.mov,.webm,.mkv,.gif" disabled={busy}
          onChange={(e) => void choose(e.target.files?.[0])} />
        <Icon name="upload" />
        <span className="sf-drop-main">{file ? file.f.name : 'Or drop your own clip'}</span>
        <span className="sf-drop-hint">up to 100 MB · 120 s · deleted in a day</span>
      </label>
      {file?.problems.map((p) => <p key={p} className="alert" role="alert">{p}</p>)}
      {file && !file.problems.length && (
        <button type="button" className="sf-btn sf-wide" disabled={busy} onClick={upload}>
          {progress !== null ? `Uploading ${Math.round(progress * 100)}%` : 'Upload and check'}
        </button>
      )}
      {error && <p className="alert" role="alert">{error}</p>}
    </section>
  );
}
