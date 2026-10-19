// /judge: a stranger's 90-second path through the product. It opens with a live run on the
// deployed worker (components/LiveDemo.tsx); everything below it is a recording of the worker's
// own outputs (eval/judge_bundle.py) or a number read from the frozen evaluation results.
//
// Flash safety: nothing on this page moves on its own. No animation, no video autoplay, no
// blinking state; hazards appear only as still frames and plots.
import { useEffect, useState, type ReactNode } from 'react';
import { HazardTimeline } from '../components/HazardTimeline';
import { LiveDemo } from '../components/LiveDemo';
import { Conversation, Icon } from '../components/tour';
import { fmtRange } from '../format';
import { href } from '../hooks/useRoute';
import { where } from '../tourData';
import { REPO_URL, VIDEO_URL, judgeFile, loadIndex, loadJudgeJob, type JudgeIndex, type JudgeJob, type JudgeResult } from '../judge';

interface Props {
  navigate: (path: string) => void;
}

function JobLink({ id, navigate, className, children }: { id: string; navigate: (p: string) => void; className?: string; children: ReactNode }) {
  return (
    <a className={className} href={href(`/jobs/${id}`)} onClick={(e) => { e.preventDefault(); navigate(`/jobs/${id}`); }}>
      {children}
    </a>
  );
}

const keyOf = (r: JudgeResult) => (r as JudgeResult & { key?: string }).key;

export function JudgePage({ navigate }: Props) {
  const [index, setIndex] = useState<JudgeIndex | null>(null);
  const [jobs, setJobs] = useState<Record<string, JudgeJob>>({});
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<'jd-adapt' | 'jd-live'>('jd-adapt');

  useEffect(() => {
    document.title = 'SteadyFrame · live demo';
    loadIndex()
      .then(async (ix) => {
        setIndex(ix);
        const loaded = await Promise.all(ix.cases.map(async (c) => [c.id, await loadJudgeJob(c.id)] as const));
        setJobs(Object.fromEntries(loaded));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    return () => { document.title = 'SteadyFrame'; };
  }, []);

  const live = jobs['jd-live'];
  const adapt = jobs['jd-adapt'];
  const appr = jobs['jd-approval'];
  const g = index?.guardrails ?? null;
  const R = index?.results ?? [];
  const stat = (key: string) => R.find((r) => keyOf(r) === key)?.text ?? '–';
  const pending = appr?.job.pending_approvals[0];
  const pendingQ = pending?.options?.[0]?.quality as { ssim_overall?: number } | undefined;

  return (
    <div className="jx">
      {/* ---------------------------------------------------------------- hero + live demo */}
      <header className="jx-hero">
        <p className="jx-eyebrow">OpenCV AI Competition 2026 · live demo</p>
        <h1>
          Find the flashing that can trigger seizures.
          <span className="jx-h1-2"> Fix only that spot. Prove the fix.</span>
        </h1>
        <p className="jx-lede">
          Other checkers answer pass or fail for the whole video. SteadyFrame says <strong>when</strong> and
          <strong> where</strong> the hazard is, repairs just that region, and re-runs the same check on its own repair.
        </p>
        <ul className="jx-pills" aria-label="How decisions are split">
          <li><Icon name="wrench" /> The model picks the fix</li>
          <li><Icon name="eye" /> The analyzer decides if it worked</li>
          <li><Icon name="stamp" /> A person signs off on anything drastic</li>
        </ul>
        <LiveDemo navigate={navigate} />
        <div className="jx-cta jx-hero-links">
          {VIDEO_URL && <a className="jx-btn" href={VIDEO_URL}>Watch the video</a>}
          <a className="jx-btn" href={REPO_URL}>View the code</a>
          <a className="jx-btn" href={href('/')} onClick={(e) => { e.preventDefault(); navigate('/'); }}>Upload your own clip</a>
        </div>
      </header>

      {/* ---------------------------------------------------------------- stats */}
      {index && (
        <section className="jx-stats" aria-label="Headline results">
          {[
            ['clips', 'synthetic clips judged right'],
            ['iris', "of EA IRIS's own verdicts matched"],
            ['controls', 'seconds of real footage falsely flagged'],
            ['fixed', 'hazards fixed and re-verified'],
            ['guardrails', 'attacks on the agent held'],
          ].map(([k, label]) => (
            <div key={k} className="jx-stat">
              <span className="jx-stat-value">{k === 'guardrails' ? stat(k).split(' ')[0] : stat(k)}</span>
              <span className="jx-stat-label">{label}</span>
            </div>
          ))}
        </section>
      )}

      <nav className="jx-nav" aria-label="Page sections">
        {[['find', 'Find'], ['decide', 'Decide'], ['ask', 'Ask a person'], ['keep', 'Keep'], ['measured', 'Measured'], ['break', 'Break it'], ['try', 'Run locally']].map(([id, label], i) => (
          <a key={id} href={`#${id}`}><span>{String(i + 1).padStart(2, '0')}</span> {label}</a>
        ))}
      </nav>

      {error && <p className="alert" role="alert">The recorded examples did not load ({error}); the live demo above does not need them.</p>}
      {index && (
        <p className="jx-recorded">
          Below the live demo, the examples are recordings of the same worker code
          (<code>python -m eval.judge_bundle</code>, recorded {index.generated_at.slice(0, 10)}, OpenCV {index.opencv}
          {index.offline ? ', offline planner' : ', live model on Amazon Bedrock'}), kept so a full-screen red strobe and a
          paused job can be inspected without waiting for them.
        </p>
      )}

      {/* ---------------------------------------------------------------- 01 find */}
      {live && (
        <section id="find" className="jx-section" aria-labelledby="find-h">
          <div className="jx-section-head">
            <span className="jx-step">01 · Find</span>
            <h2 id="find-h">Not "fail". Where, when, and how bad.</h2>
            <p>OpenCV 5 measures every frame on a 64×48 grid: luminance swing, flash rate in a sliding one-second window, the area rule, red flashes, and the region on screen.</p>
          </div>
          <div className="jx-finds">
            {(live.job.before?.segments ?? []).map((s) => (
              <article key={s.id} className="jx-find">
                <img src={judgeFile('jd-live', `stills/${s.id}.png`)} width={320} height={240} loading="lazy"
                  alt={`Still frame from ${s.id} with the flagged region outlined`} />
                <div className="jx-find-body">
                  <p className="jx-find-rate"><strong>{s.peak_flash_rate_hz}</strong> flashes / s</p>
                  <dl>
                    <div><dt>swing</dt><dd>{s.max_delta_L.toFixed(2)}</dd></div>
                    <div><dt>where</dt><dd>{where(s)}</dd></div>
                    <div><dt>when</dt><dd>{fmtRange(s.start_s, s.end_s)}</dd></div>
                  </dl>
                </div>
              </article>
            ))}
          </div>
          <div className="jx-panel">
            <HazardTimeline duration={live.job.input?.duration_s ?? 10} before={live.job.before!} after={live.job.after} selectedId={null} onSelect={() => undefined} />
          </div>
          <p className="jx-more"><JobLink id="jd-live" navigate={navigate}>Open the full job page →</JobLink></p>
        </section>
      )}

      {/* ---------------------------------------------------------------- 02 decide */}
      {live && adapt && (
        <section id="decide" className="jx-section" aria-labelledby="decide-h">
          <div className="jx-section-head">
            <span className="jx-step">02 · Decide</span>
            <h2 id="decide-h">The model plans. The analyzer checks. Watch it change its mind.</h2>
            <p>The model never sees a pixel, only the analyzer's numbers. Each candidate fix goes back through the same analyzer that found the problem, and only a verified candidate can be accepted.</p>
          </div>
          <div className="jx-tabs" role="group" aria-label="Choose a recorded run">
            <button type="button" aria-pressed={run === 'jd-adapt'} onClick={() => setRun('jd-adapt')}>Red full-screen strobe: changes its plan</button>
            <button type="button" aria-pressed={run === 'jd-live'} onClick={() => setRun('jd-live')}>Two regions: right first time</button>
          </div>
          <div className="jx-panel jx-convo-panel">
            <Conversation records={(run === 'jd-adapt' ? adapt : live).trace.records} />
          </div>
          <p className="jx-more"><JobLink id={run} navigate={navigate}>See every tool call in the full trace →</JobLink></p>
        </section>
      )}

      {/* ---------------------------------------------------------------- 03 ask */}
      {appr && (
        <section id="ask" className="jx-section jx-split" aria-labelledby="ask-h">
          <div className="jx-section-head">
            <span className="jx-step">03 · Ask a person</span>
            <h2 id="ask-h">When a fix changes the picture too much, it stops and asks.</h2>
            <p>The job pauses with its state saved. Approve, and it resumes and passes. Reject, and it tries the next strategy and asks again. Both outcomes are real recordings.</p>
          </div>
          {pending && (
            <div className="jx-dialog" role="group" aria-label="The recorded approval request">
              <p className="jx-dialog-title">Approval needed · segment {pending.segment_id}</p>
              <p className="jx-dialog-reason">{pending.reason}</p>
              {pendingQ?.ssim_overall !== undefined && (
                <div className="jx-meter" aria-hidden="true">
                  <div className="jx-meter-fill" style={{ width: `${Math.round(pendingQ.ssim_overall * 100)}%` }} />
                  <div className="jx-meter-mark" style={{ left: '75%' }} />
                </div>
              )}
              <p className="jx-dialog-note">Picture kept (SSIM) {pendingQ?.ssim_overall?.toFixed(3)} · automatic acceptance needs 0.75</p>
              <JobLink id="jd-approval" navigate={navigate} className="jx-btn primary">Open it and decide →</JobLink>
            </div>
          )}
        </section>
      )}

      {/* ---------------------------------------------------------------- 04 keep */}
      {live && (
        <section id="keep" className="jx-section" aria-labelledby="keep-h">
          <div className="jx-section-head">
            <span className="jx-step">04 · Keep</span>
            <h2 id="keep-h">Proof you can hand to a broadcaster, and re-check yourself.</h2>
          </div>
          <div className="jx-tiles">
            <a className="jx-tile" href={judgeFile('jd-live', 'record.html')}>
              <Icon name="doc" /><strong>Verification record</strong>
              <span>File hashes, every threshold applied, each fix and any human decision, plus the UK DPP AS-11 photosensitivity fields.</span>
            </a>
            <div className="jx-tile jx-tile-code">
              <Icon name="terminal" /><strong>Re-check it anywhere</strong>
              <code>steadyframe verify safe.mp4 --record record.json</code>
              <span>Re-hashes the file and re-runs the analyzer. <a href={judgeFile('jd-live', 'record.json')}>Get record.json</a></span>
            </div>
            <a className="jx-tile" href={judgeFile('jd-live', 'hazards.vtt')}>
              <Icon name="captions" /><strong>Viewer warning track</strong>
              <span>WebVTT cues before and during each hazard, for players that show the original.</span>
            </a>
            <a className="jx-tile" href={judgeFile('jd-live', 'safe.mp4')}>
              <Icon name="play" /><strong>The repaired video</strong>
              <span>Verified to pass. Opens in your player; nothing plays here.</span>
            </a>
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- 05 measured */}
      {index && (
        <section id="measured" className="jx-section" aria-labelledby="measured-h">
          <div className="jx-section-head">
            <span className="jx-step">05 · Measured</span>
            <h2 id="measured-h">Every number comes from a script, and the failures are published too.</h2>
          </div>
          <div className="jx-results">
            {R.filter((r) => keyOf(r) !== 'guardrails').map((r) => (
              <a key={r.label} className="jx-result" href={`${REPO_URL}/blob/main/${r.source}`}>
                <span className="jx-result-value">{keyOf(r) === 'cost' ? `$${r.text}` : r.text}</span>
                <span className="jx-result-label">{r.label}</span>
                <span className="jx-result-src">{r.source.split('/').pop()}</span>
              </a>
            ))}
          </div>
          <p className="jx-note">The live agent did worse than the fixed policy on two red clips (more attempts, longer runtime); the report lists every case where it did worse.</p>
        </section>
      )}

      {/* ---------------------------------------------------------------- 06 break */}
      {g && (
        <section id="break" className="jx-section" aria-labelledby="break-h">
          <div className="jx-section-head">
            <span className="jx-step">06 · Try to break it</span>
            <h2 id="break-h">A hostile planner tried every shortcut. None got through.</h2>
            <p>Same tools as the model, one attack per run, including instructions hidden in the file name and metadata.</p>
          </div>
          <div className="jx-score">
            <div><span className="jx-score-big">{g.summary.held}/{g.summary.runs}</span><span>attacks held</span></div>
            <div><span className="jx-score-big">{g.summary.false_pass}</span><span>false passes</span></div>
            <div><span className="jx-score-big">{g.summary.refused_calls}</span><span>hostile calls refused</span></div>
          </div>
          <ul className="jx-attacks">
            {g.rows.map((r) => (
              <li key={r.attack} className={r.held ? 'held' : 'broken'}>
                <Icon name={r.held ? 'shield' : 'cross'} />
                <span className="jx-attack-what">{r.what}</span>
                <span className="jx-attack-out">
                  {r.held ? 'Held' : 'NOT HELD'} · {r.status === 'passed'
                    ? 'the open hazard was then fixed properly'
                    : r.status === 'needs_approval' ? 'the job waited for a person' : `job ${r.status.replace('_', ' ')}`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ---------------------------------------------------------------- 07 run locally */}
      <section id="try" className="jx-section" aria-labelledby="try-h">
        <div className="jx-section-head">
          <span className="jx-step">07 · Run locally</span>
          <h2 id="try-h">The same loop on your laptop, in three commands.</h2>
        </div>
        <div className="jx-try">
          <div className="jx-try-card">
            <h3>No credentials, no cloud account</h3>
            <pre className="jx-term" tabIndex={0} aria-label="Commands to run it locally"><code>{`git clone ${REPO_URL}.git
cd SteadyFrame
make install
make demo`}</code></pre>
            <p className="jx-fine">Renders three sample clips, then analyzes, fixes and verifies them in seconds.</p>
          </div>
          <div className="jx-try-card">
            <h3>How the live demo runs</h3>
            <p>CloudFront → API Gateway + Lambda → SQS → a Lambda worker on Graviton (arm64) running OpenCV 5, with Amazon Bedrock for planning, S3 and DynamoDB for state, and an ECS Fargate fallback. All defined in AWS CDK; idle cost about zero.</p>
          </div>
        </div>
        <ul className="jx-stack" aria-label="Built with">
          {['OpenCV 5', 'Amazon Bedrock', 'AWS Lambda (Graviton)', 'ECS Fargate', 'API Gateway', 'S3 + CloudFront', 'SQS', 'DynamoDB', 'CloudWatch', 'AWS CDK', 'React'].map((t) => <li key={t}>{t}</li>)}
        </ul>
      </section>

      {/* ---------------------------------------------------------------- limits */}
      {index && (
        <section className="jx-section jx-limits" aria-labelledby="limits-h">
          <h2 id="limits-h">What it does not do</h2>
          <ul>{index.limits.map((l) => <li key={l}>{l}</li>)}</ul>
          <p className="jx-links">
            <a href={`${REPO_URL}/blob/main/docs/report/REPORT.md`}>Technical report</a>
            <a href={`${REPO_URL}/blob/main/docs/JUDGES.md`}>Rubric → evidence map</a>
            <a href={href('/')} onClick={(e) => { e.preventDefault(); navigate('/'); }}>Upload your own clip</a>
          </p>
        </section>
      )}
    </div>
  );
}
