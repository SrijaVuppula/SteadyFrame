#!/usr/bin/env node
// Accessibility check: build, serve dist/ locally, run @axe-core/cli against the start page and
// two job pages rendered from fixtures (?fixture=1), write a11y-report.json, exit 1 on any
// violation of impact serious or critical.
//
// Browser: CHROME_PATH, else the Playwright chromium under PLAYWRIGHT_BROWSERS_PATH
// (/opt/pw-browsers by default), else whatever chromedriver finds.
// Driver: CHROMEDRIVER_PATH, else the pinned chromedriver package's binary. That package's
// postinstall is skipped in .npmrc (its version lookup host is blocked on some networks), so
// on first run we install the driver that matches the detected Chrome major version straight
// from the Chrome-for-Testing bucket via the package's own installer.
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync, rmSync } from 'node:fs';
import { extname, join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const args = new Set(process.argv.slice(2));
const PORT = Number(process.env.A11Y_PORT || 4173);
const PAGES = ['/?fixture=1', '/jobs/fx-passed?fixture=1', '/jobs/fx-approval?fixture=1'];
const FAIL_IMPACTS = new Set(['serious', 'critical']);

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.txt': 'text/plain',
};

function run(cmd, cmdArgs, opts = {}) {
  const r = spawnSync(cmd, cmdArgs, { stdio: 'inherit', cwd: root, ...opts });
  if (r.status !== 0) throw new Error(`${cmd} ${cmdArgs.join(' ')} exited with ${r.status}`);
}

function findChrome() {
  if (process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH)) return process.env.CHROME_PATH;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH || '/opt/pw-browsers';
  if (existsSync(base)) {
    const dirs = readdirSync(base).filter((d) => /^chromium-\d+$/.test(d)).sort().reverse();
    for (const d of dirs) {
      for (const rel of ['chrome-linux/chrome', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium', 'chrome-win/chrome.exe']) {
        const p = join(base, d, rel);
        if (existsSync(p)) return p;
      }
    }
  }
  return null;
}

function chromeVersion(chrome) {
  const r = spawnSync(chrome, ['--version'], { encoding: 'utf8' });
  const m = (r.stdout || '').match(/(\d+)\.(\d+)\.(\d+)\.(\d+)/);
  return m ? m[0] : null;
}

function findChromedriver(chrome) {
  if (process.env.CHROMEDRIVER_PATH && existsSync(process.env.CHROMEDRIVER_PATH)) return process.env.CHROMEDRIVER_PATH;
  const pkgBin = join(root, 'node_modules', 'chromedriver', 'lib', 'chromedriver', process.platform === 'win32' ? 'chromedriver.exe' : 'chromedriver');
  const installer = join(root, 'node_modules', 'chromedriver', 'install.js');
  const version = chrome ? chromeVersion(chrome) : null;
  const driverOk = (bin) => {
    if (!existsSync(bin)) return false;
    if (!version) return true;
    const r = spawnSync(bin, ['--version'], { encoding: 'utf8' });
    return (r.stdout || '').includes(`ChromeDriver ${version.split('.')[0]}.`);
  };
  if (driverOk(pkgBin)) return pkgBin;
  if (version && existsSync(installer)) {
    console.log(`[a11y] fetching chromedriver ${version} to match ${chrome}`);
    const r = spawnSync(process.execPath, [installer], {
      stdio: 'inherit', cwd: root,
      env: {
        ...process.env,
        CHROMEDRIVER_SKIP_DOWNLOAD: 'false',
        CHROMEDRIVER_VERSION: version,
        CHROMEDRIVER_CDNBINARIESURL: process.env.CHROMEDRIVER_CDNBINARIESURL || 'https://storage.googleapis.com/chrome-for-testing-public',
      },
    });
    if (r.status === 0 && driverOk(pkgBin)) return pkgBin;
    console.warn('[a11y] chromedriver download failed; falling back to PATH');
  }
  return null; // let axe/selenium find one on PATH
}

function serve() {
  const server = createServer((req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
    let file = join(dist, decodeURIComponent(url.pathname));
    if (!file.startsWith(dist) || !existsSync(file) || statSync(file).isDirectory()) file = join(dist, 'index.html'); // SPA fallback
    res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' });
    res.end(readFileSync(file));
  });
  return new Promise((ok) => server.listen(PORT, '127.0.0.1', () => ok(server)));
}

function runAxe(url, outDir, index, chrome, driver) {
  const axeBin = join(root, 'node_modules', '.bin', process.platform === 'win32' ? 'axe.cmd' : 'axe');
  const file = `axe-${index}.json`;
  const a = [url, '--save', file, '--dir', outDir, '--load-delay', '1200', '--timeout', '120',
    '--tags', 'wcag2a,wcag2aa,wcag21a,wcag21aa,wcag22aa,best-practice',
    '--chrome-options', 'no-sandbox,disable-gpu,disable-dev-shm-usage,window-size=1280,900'];
  if (chrome) a.push('--chrome-path', chrome);
  if (driver) a.push('--chromedriver-path', driver);
  return new Promise((ok, fail) => {
    const p = spawn(axeBin, a, { cwd: root, stdio: 'inherit', env: { ...process.env, ...(chrome ? { CHROME_PATH: chrome } : {}) } });
    p.on('exit', (code) => {
      const out = join(outDir, file);
      if (!existsSync(out)) return fail(new Error(`axe produced no output for ${url} (exit ${code})`));
      ok(JSON.parse(readFileSync(out, 'utf8')));
    });
    p.on('error', fail);
  });
}

async function main() {
  if (!args.has('--no-build')) run('npm', ['run', 'build']);
  const chrome = findChrome();
  const driver = findChromedriver(chrome);
  console.log(`[a11y] chrome: ${chrome ?? '(default)'}  chromedriver: ${driver ?? '(PATH)'}`);
  const outDir = join(root, '.cache', 'axe');
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  const server = await serve();
  const results = [];
  try {
    for (const [i, page] of PAGES.entries()) {
      const url = `http://127.0.0.1:${PORT}${page}`;
      console.log(`\n[a11y] auditing ${url}`);
      const r = await runAxe(url, outDir, i, chrome, driver);
      results.push(...(Array.isArray(r) ? r : [r]));
    }
  } finally {
    server.close();
  }

  const summary = results.map((r) => ({
    url: r.url,
    violations: r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length, targets: v.nodes.slice(0, 5).map((n) => n.target.join(' ')) })),
    passes: r.passes.length,
    incomplete: r.incomplete.length,
  }));
  const blocking = summary.flatMap((s) => s.violations.filter((v) => FAIL_IMPACTS.has(v.impact)).map((v) => ({ url: s.url, ...v })));
  const report = {
    tool: 'axe-core via @axe-core/cli', axe_version: results[0]?.testEngine?.version, generated_at: new Date().toISOString(),
    pages: summary, blocking_count: blocking.length, passed: blocking.length === 0,
  };
  writeFileSync(join(root, 'a11y-report.json'), JSON.stringify(report, null, 2) + '\n');

  console.log('\n[a11y] summary');
  for (const s of summary) {
    console.log(`  ${s.url}: ${s.violations.length} violation(s), ${s.passes} rules passed, ${s.incomplete} needs review`);
    for (const v of s.violations) console.log(`    - [${v.impact}] ${v.id}: ${v.help} (${v.nodes} node(s)) ${v.targets.join(' | ')}`);
  }
  console.log(`[a11y] report written to a11y-report.json; ${blocking.length} serious/critical violation(s)`);
  process.exit(blocking.length ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(2);
});
