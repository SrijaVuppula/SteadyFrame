import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { ACCEPTED_EXTENSIONS, MAX_DURATION_S, MAX_UPLOAD_BYTES, MOCK_MODE, WHAT_IT_DOES } from '../config';
import { fmtBytes } from '../format';
import type { Policy, Profile, Sample } from '../types';
import { rememberUpload } from '../uploadStore';

interface Props {
  navigate: (path: string) => void;
}

interface FileInfo {
  file: File;
  duration: number | null;
  problems: string[];
}

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

export function HomePage({ navigate }: Props) {
  const [profile, setProfile] = useState<Profile>('wcag');
  const [policy, setPolicy] = useState<Policy>('fixed');
  const [conservative, setConservative] = useState(false);
  const [info, setInfo] = useState<FileInfo | null>(null);
  const [dragging, setDragging] = useState(false);
  const [step, setStep] = useState<string>('');
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [samplesOpen, setSamplesOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function chooseFile(file: File | undefined) {
    setError(null);
    if (!file) {
      setInfo(null);
      return;
    }
    const problems: string[] = [];
    if (file.size > MAX_UPLOAD_BYTES) problems.push(`File is ${fmtBytes(file.size)}; the limit is 100 MB.`);
    const ext = extensionOf(file.name);
    if (!ACCEPTED_EXTENSIONS.includes(ext)) problems.push(`Container .${ext || '?'} is not accepted (${ACCEPTED_EXTENSIONS.join(', ')}).`);
    setInfo({ file, duration: null, problems });
    const duration = await probeDuration(file);
    if (duration !== null && duration > MAX_DURATION_S) problems.push(`Clip is ${duration.toFixed(1)} s; the limit is ${MAX_DURATION_S} s.`);
    setInfo({ file, duration, problems: [...problems] });
  }

  async function submit() {
    if (!info || info.problems.length) return;
    setBusy(true);
    setError(null);
    try {
      setStep('Creating job…');
      const created = await api.createJob({
        filename: info.file.name,
        content_type: info.file.type || 'video/mp4',
        size_bytes: info.file.size,
        profile,
        policy,
        conservative,
      });
      setStep('Uploading…');
      setProgress(0);
      await api.upload(created.upload, info.file, (f) => setProgress(f));
      setStep('Starting analysis…');
      await api.startJob(created.job_id);
      rememberUpload(created.job_id, info.file);
      setStep('Job started. Opening job page.');
      navigate(`/jobs/${created.job_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStep('');
      setProgress(null);
    } finally {
      setBusy(false);
    }
  }

  async function openSamples() {
    setSamplesOpen(true);
    if (samples) return;
    try {
      setSamples(await api.listSamples());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function runSample(sample: Sample) {
    setBusy(true);
    setError(null);
    try {
      setStep(`Starting sample "${sample.name}"…`);
      const ref = await api.jobFromSample({ sample_id: sample.id, profile, policy, conservative });
      navigate(`/jobs/${ref.job_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStep('');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    // Enter on the drop zone opens the picker; the visible <input> is the real control.
    const el = inputRef.current;
    if (el && info === null) el.value = '';
  }, [info]);

  const canSubmit = !!info && info.problems.length === 0 && !busy;

  return (
    <>
      <section className="card intro">
        <h1>Check and remediate a clip</h1>
        <p>
          SteadyFrame {WHAT_IT_DOES}. Flagged segments are localised in time and space, then
          remediated with the least invasive strategy that passes re-analysis. Every decision is
          logged in a trace you can read on the job page.
        </p>
        <p className="muted">Limits: 100 MB, 120 s, containers {ACCEPTED_EXTENSIONS.join(', ')}. Uploads are deleted after one day.</p>
      </section>

      <div className="two-col">
        <section className="card" aria-labelledby="upload-h">
          <h2 id="upload-h">1. Choose a clip</h2>
          <div
            className={`dropzone${dragging ? ' dragging' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); void chooseFile(e.dataTransfer.files?.[0]); }}
          >
            <label htmlFor="file" className="dropzone-label">Drop a video here, or choose a file</label>
            <input
              ref={inputRef}
              id="file"
              type="file"
              accept="video/*,.mp4,.mov,.webm,.mkv,.gif"
              onChange={(e) => void chooseFile(e.target.files?.[0])}
              disabled={busy}
            />
            <p className="muted small">Nothing plays here. The clip is only inspected for size and duration.</p>
          </div>
          {info && (
            <dl className="meta">
              <div><dt>File</dt><dd>{info.file.name}</dd></div>
              <div><dt>Size</dt><dd>{fmtBytes(info.file.size)}</dd></div>
              <div><dt>Duration</dt><dd>{info.duration === null ? 'reading…' : `${info.duration.toFixed(1)} s`}</dd></div>
            </dl>
          )}
          {info?.problems.map((p) => <p key={p} className="alert" role="alert">{p}</p>)}
        </section>

        <section className="card" aria-labelledby="options-h">
          <h2 id="options-h">2. Options</h2>
          <fieldset>
            <legend>Threshold profile</legend>
            <label className="radio"><input type="radio" name="profile" value="wcag" checked={profile === 'wcag'} onChange={() => setProfile('wcag')} /> <span><strong>wcag</strong> — WCAG 2.3.1 general and red flash thresholds, 1024×768 viewport area rule</span></label>
            <label className="radio"><input type="radio" name="profile" value="broadcast" checked={profile === 'broadcast'} onChange={() => setProfile('broadcast')} /> <span><strong>broadcast</strong> — ITU-R BT.1702 / Ofcom guidance</span></label>
          </fieldset>
          <fieldset>
            <legend>Remediation policy</legend>
            <label className="radio"><input type="radio" name="policy" value="fixed" checked={policy === 'fixed'} onChange={() => setPolicy('fixed')} /> <span><strong>fixed</strong> — deterministic strategy order, no model</span></label>
            <label className="radio"><input type="radio" name="policy" value="agent" checked={policy === 'agent'} onChange={() => setPolicy('agent')} /> <span><strong>agent</strong> — a model picks strategies and parameters from the analyzer's measurements; may ask you for approval</span></label>
          </fieldset>
          <label className="check">
            <input type="checkbox" checked={conservative} onChange={(e) => setConservative(e.target.checked)} />
            <span>Conservative: tighten every threshold slightly and treat warnings as failures</span>
          </label>
        </section>
      </div>

      <section className="card" aria-labelledby="go-h">
        <h2 id="go-h">3. Run</h2>
        <div className="actions">
          <button type="button" className="btn primary" disabled={!canSubmit} onClick={submit}>
            {busy ? 'Working…' : 'Upload and analyze'}
          </button>
          <button type="button" className="btn" disabled={busy} onClick={openSamples} aria-expanded={samplesOpen} aria-controls="samples">
            Try a sample clip
          </button>
        </div>
        {progress !== null && busy && (
          <div className="progress-row">
            <div className="progress" role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
              <div className="progress-fill" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
            <p className="progress-text">Upload {Math.round(progress * 100)}%</p>
          </div>
        )}
        <p role="status" aria-live="polite" className={step ? '' : 'sr-only'}>{step}</p>
        {error && <p className="alert" role="alert">{error}</p>}

        {samplesOpen && (
          <div id="samples" className="samples">
            <h3>Sample clips</h3>
            <p className="muted small">
              Synthetic test clips that fail the thresholds on purpose. They are never shown here;
              the job page shows still frames and plots, and any preview of the original sits
              behind a warning.{MOCK_MODE ? ' In fixture mode these start simulated jobs.' : ''}
            </p>
            {!samples && !error && <p className="muted">Loading samples…</p>}
            {samples && samples.length === 0 && <p className="muted">No samples are configured on this API.</p>}
            <ul className="sample-list">
              {samples?.map((s) => (
                <li key={s.id} className="sample">
                  <div>
                    <strong>{s.name}</strong>
                    {s.warning && <span className="badge badge-warn">contains flashing</span>}
                    <p className="muted small">{s.description}</p>
                    <p className="muted small">{s.duration_s} s · {s.hazard_types.join(', ')}</p>
                  </div>
                  <button type="button" className="btn" disabled={busy} onClick={() => runSample(s)} aria-label={`Run sample ${s.name}`}>
                    Run
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </>
  );
}
