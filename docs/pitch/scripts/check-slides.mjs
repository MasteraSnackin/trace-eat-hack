#!/usr/bin/env node
/**
 * Audit every slide with HyperFrames' official checker.
 *
 * HyperFrames 0.8.114 derives its check duration from the first top-level
 * composition. This deck uses eight top-level slideshow scenes, so checking
 * composition/ alone does not sweep every slide. Each temporary fixture below
 * keeps the source CSS, scene DOM, assets and GSAP statements, with absolute
 * times translated to zero. The standalone navigation bridge is intentionally
 * excluded: browser acceptance must cover that separate integration.
 */
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const version = '0.8.114';
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourceDir = path.join(project, 'composition');
const html = await readFile(path.join(sourceDir, 'index.html'), 'utf8');
const args = process.argv.slice(2);
const options = {};
for (let i = 0; i < args.length; i += 2) {
  if (!['--output', '--only'].includes(args[i]) || !args[i + 1]) {
    throw new Error('Usage: node scripts/check-slides.mjs [--output temporary-directory] [--only scene-id]');
  }
  options[args[i].slice(2)] = args[i + 1];
}
const output = options.output
  ? path.resolve(options.output)
  : await mkdtemp(path.join(tmpdir(), 'trace-pitch-check-'));
await mkdir(output, { recursive: true });
const runId = `trace-pitch-${randomUUID()}`;
const head = html.match(/^[\s\S]*?<body>/)?.[0];
const slideMatches = [...html.matchAll(/<section id="scene-([a-z][a-z0-9-]*)"[\s\S]*?<\/section>/g)];
const metadataText = html.match(/<script type="application\/hyperframes-slideshow\+json">([\s\S]*?)<\/script>/)?.[1];
if (!head || !metadataText || !slideMatches.length) throw new Error('Unrecognised slideshow source structure.');
const metadata = JSON.parse(metadataText);
if (metadata.slides.length !== slideMatches.length) throw new Error('Scene and metadata counts differ.');
if (options.only && !slideMatches.some(([, id]) => id === options.only)) throw new Error('Unknown --only scene-id.');
const rounded = (value) => Number(value.toFixed(6));

function runCheck(directory, times) {
  return new Promise((resolve, reject) => {
    const child = spawn('npx', ['--yes', `hyperframes@${version}`, 'check', directory,
      '--at', times.join(','), '--snapshots', '--strict', '--json'], {
      cwd: project,
      env: { ...process.env, HYPERFRAMES_RUN_ID: runId },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '', stderr = '';
    child.stdout.on('data', (data) => { stdout += data; });
    child.stderr.on('data', (data) => { stderr += data; });
    child.once('error', reject);
    child.once('close', async (exitCode) => {
      try {
        await writeFile(path.join(directory, 'check.json'), stdout);
        await writeFile(path.join(directory, 'check.stderr.log'), stderr);
        resolve({ exitCode, audit: JSON.parse(stdout) });
      } catch (error) { reject(error); }
    });
  });
}

const results = [];
for (const [sourceScene, id] of slideMatches) {
  if (options.only && options.only !== id) continue;
  const start = Number(sourceScene.match(/data-start="([\d.]+)"/)?.[1]);
  const duration = Number(sourceScene.match(/data-duration="([\d.]+)"/)?.[1]);
  if (!Number.isFinite(start) || !Number.isFinite(duration) || duration <= 1) {
    throw new Error(`Invalid timing for ${id}.`);
  }
  const slideMetadata = metadata.slides.find((slide) => slide.sceneId === id);
  if (!slideMetadata) throw new Error(`Missing metadata for ${id}.`);
  const timelinePattern = new RegExp(`const ${id} = gsap[\\s\\S]*?window\\.__timelines\\['${id}'\\] = ${id};`);
  const sourceTimeline = html.match(timelinePattern)?.[0];
  if (!sourceTimeline) throw new Error(`Unrecognised timeline for ${id}; update the fixture parser.`);
  let replaced = 0;
  const timeline = sourceTimeline.replace(/, ([\d.]+)\);\n/, (_, time) => {
    replaced += 1;
    return `, ${rounded(Number(time) - start)});\n`;
  });
  if (replaced !== 1) throw new Error(`Cannot normalise the entrance timeline for ${id}.`);
  const scene = sourceScene.replace(`data-start="${start}"`, 'data-start="0"')
    .replace(/data-reveal-at="([\d.]+)"/g, (_, time) => `data-reveal-at="${rounded(Number(time) - start)}"`);
  const reveals = [...scene.matchAll(/data-reveal-at="([\d.]+)"/g)].map((match) => Number(match[1]));
  const fragments = (slideMetadata.fragments ?? []).map((time) => rounded(time - start));
  // Entrances, each presenter fragment endpoint, and the fully settled slide.
  const times = [...new Set([0.15, 0.35, 0.6, 0.9, 1, ...fragments, duration - 0.5])]
    .filter((time) => time > 0 && time < duration).sort((a, b) => a - b);
  const assertions = [
    { kind: 'appearsBy', selector: `#scene-${id} .eyebrow`, bySec: 1 },
    { kind: 'staysInFrame', selector: `#scene-${id} h1, #scene-${id} h2` },
    ...reveals.flatMap((time) => [
      { kind: 'appearsBy', selector: `[data-reveal-at="${time}"]`, bySec: rounded(time + 0.4) },
      { kind: 'staysInFrame', selector: `[data-reveal-at="${time}"]` },
    ]),
  ];
  for (let i = 1; i < reveals.length; i += 1) {
    assertions.push({ kind: 'before', a: `[data-reveal-at="${reveals[i - 1]}"]`, b: `[data-reveal-at="${reveals[i]}"]` });
  }
  const directory = path.join(output, id);
  await mkdir(directory, { recursive: true });
  await cp(path.join(sourceDir, 'assets'), path.join(directory, 'assets'), { recursive: true });
  await writeFile(path.join(directory, 'index.html'),
    `${head}\n${scene}\n<script>window.__timelines = {};\n${timeline}</script>\n</body></html>\n`);
  await writeFile(path.join(directory, 'index.motion.json'), JSON.stringify({ duration, assertions }, null, 2));
  const { exitCode, audit } = await runCheck(directory, times);
  results.push({
    sceneId: id, sourceStart: start, duration, exitCode,
    ok: exitCode === 0 && audit.ok === true && audit.browserSkipped === false,
    browserSkipped: audit.browserSkipped,
    samples: audit.layout?.samples ?? [],
    sections: Object.fromEntries(['lint', 'runtime', 'layout', 'motion', 'contrast'].map((section) => [section, {
      errorCount: audit[section]?.errorCount ?? null,
      warningCount: audit[section]?.warningCount ?? null,
      infoCount: audit[section]?.infoCount ?? null,
    }])),
    motionAssertions: assertions.length,
    motionSamples: audit.motion?.samples ?? 0,
    contrastChecked: audit.contrast?.checked ?? 0,
    snapshots: (audit.snapshots?.files ?? []).map((file) => `${id}/${file}`),
    auditFile: `${id}/check.json`,
  });
  const result = results.at(-1);
  process.stdout.write(`${id}: ${result.ok ? 'PASS' : 'FAIL'}; ${result.samples.length} sampled times; ${result.contrastChecked} contrast checks\n`);
}

const report = {
  schemaVersion: 1,
  cliVersion: version,
  source: 'composition/index.html',
  sourceSha256: createHash('sha256').update(html).digest('hex'),
  ok: results.every((result) => result.ok),
  sceneCount: results.length,
  sampledTimes: results.reduce((total, result) => total + result.samples.length, 0),
  contrastChecks: results.reduce((total, result) => total + result.contrastChecked, 0),
  motionSamples: results.reduce((total, result) => total + result.motionSamples, 0),
  limitations: [
    'Per-slide fixtures preserve the scene DOM, CSS and GSAP statements, with absolute times normalised to zero.',
    'The standalone navigation bridge and presenter/audience integration require a separate browser acceptance check.',
    'Sampled checks are not continuous-frame validation. No MP4 was rendered.',
  ],
  results,
};
await writeFile(path.join(output, 'validation.json'), `${JSON.stringify(report, null, 2)}\n`);
process.stdout.write(`Audit and frames: ${output}\n`);
process.exitCode = report.ok ? 0 : 1;
