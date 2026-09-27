/* Output + processing probes: only a response-row spinner means "generating" (I-69, 2026-09-27).
 *
 * Owner report: the image was on the page under its [JOB-ID] prompt, yet the wait ended
 * "Timeout after 120000ms" and nothing was saved. The saved page
 * (docs/research/Directly Chat…html) shows why: the sidebar history puts a
 * `div.animate-spin` beside every chat that is still generating — with several workers on one
 * account that is almost always true — and the output probe counted ANY visible
 * `div.animate-spin`, so it answered `generating_spinner_visible` until the timeout.
 * I-66 fixed the Watcher; these probes kept the old rule. The page below is built from the
 * saved HTML's own elements (sidebar link + spinner, response header row, output image).
 */
import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const JOB = '20260927-090424-RLHW';
const PY = [
  'import json',
  'from app.browser.output_probes import build_baseline_js, build_check_js',
  'from app.browser.processing_probe import build_processing_probe',
  `print(json.dumps({"check": build_check_js([], "${JOB}", []), "base": build_baseline_js(),`,
  '                  "proc": build_processing_probe("", "")}))',
].join('\n');

function findPython() {
  const cands = [process.env.PYTHON, path.join(ROOT, '.venv/bin/python'), path.join(ROOT, '.venv/Scripts/python.exe'),
    'python3', 'python'].filter(Boolean);
  for (const c of cands) {
    try { execFileSync(c, ['-c', 'import sys'], { stdio: 'ignore' }); return c; } catch { /* next */ }
  }
  return assert.fail('no Python interpreter found — set PYTHON=<path>');
}

let JS;
before(() => { JS = JSON.parse(execFileSync(findPython(), ['-c', PY], { cwd: ROOT, encoding: 'utf-8' })); });

/* jsdom has no layout: [hidden] (or inside it) = no offsetParent, every box 100×30; images report a loaded 1024². */
function run(html, payload) {
  const w = new JSDOM(`<body>${html}</body>`, { runScripts: 'outside-only' }).window;
  const hidden = (el) => { for (let e = el; e; e = e.parentElement) if (e.hidden) return true; return false; };
  Object.defineProperty(w.HTMLElement.prototype, 'offsetParent', {
    get() { return hidden(this) ? null : this.ownerDocument.body; }, configurable: true });
  for (const k of ['naturalWidth', 'naturalHeight']) {
    Object.defineProperty(w.HTMLImageElement.prototype, k, { get: () => 1024, configurable: true });
  }
  Object.defineProperty(w.HTMLImageElement.prototype, 'complete', { get: () => true, configurable: true });
  w.Element.prototype.getBoundingClientRect = () => ({ top: 0, left: 0, width: 100, height: 30, right: 100, bottom: 30 });
  const out = w.eval(payload);
  return typeof out === 'string' ? JSON.parse(out) : out;
}

const SIDEBAR_SPIN = '<nav data-sidebar="content"><a data-sidebar="menu-button" href="https://arena.ai/c/other">'
  + '<div class="ml-[1px] h-4 w-4 flex-none animate-spin"><canvas></canvas></div>'
  + '<span class="body-sm truncate">another worker\'s chat, still generating</span></a></nav>';
const HEADER = (spinning) => '<div class="flex min-w-0 flex-1 items-center gap-2">'
  + (spinning ? '<div class="h-5 w-5 flex-shrink-0 animate-spin"><canvas></canvas></div>' : '')
  + '<span><span class="truncate">Max</span></span></div>';
const PAGE = ({ sidebar = false, spinning = false, image = true } = {}) => (sidebar ? SIDEBAR_SPIN : '')
  + '<main><ol>'
  + `<li><div class="flex min-w-0 flex-1 flex-col items-end"><p>[JOB-ID: ${JOB}] Keep aspect ratio</p></div></li>`
  + `<li><div class="group flex flex-col">${HEADER(spinning)}`
  + (image ? '<div class="no-scrollbar"><img class="aspect-square cursor-pointer" src="https://b.r2.cloudflarestorage.com/out.png"></div>' : '')
  + '</div></li></ol></main>';

describe('output wait — a sidebar spinner is not this page generating', () => {
  test('control: finished image under the prompt, no spinner anywhere → ready', () => {
    const r = run(PAGE(), JS.check);
    assert.equal(r.ready, true, JSON.stringify({ reason: r.reason }));
  });

  test('the reported page: finished image + another chat spinning in the sidebar → ready (was generating_spinner_visible)', () => {
    const r = run(PAGE({ sidebar: true }), JS.check);
    assert.equal(r.ready, true, JSON.stringify({ reason: r.reason, spinning: r.spinning }));
    assert.equal(r.spinning, false);
  });

  test('a spinner in THIS response header still means generating (never download a half image)', () => {
    const r = run(PAGE({ sidebar: true, spinning: true }), JS.check);
    assert.equal(r.ready, false);
    assert.equal(r.reason, 'generating_spinner_visible');
    assert.equal(r.spinCount, 1);
    assert.deepEqual(JSON.parse(JSON.stringify(r.spinDetails)), [{ label: 'Max', visible: true }]);
  });

  test('no image yet: sidebar spinner alone is "no_new", a header spinner is "generating_no_new_yet"', () => {
    assert.equal(run(PAGE({ sidebar: true, image: false }), JS.check).reason, 'no_new');
    assert.equal(run(PAGE({ spinning: true, image: false }), JS.check).reason, 'generating_no_new_yet');
  });

  test('baseline: the sidebar spinner does not mark the page as spinning', () => {
    assert.equal(run(PAGE({ sidebar: true, image: false }), JS.base).spinning, false);
    assert.equal(run(PAGE({ spinning: true, image: false }), JS.base).spinning, true);
  });
});

describe('AWAIT_PROCESSING_IMAGE — the same rule', () => {
  test('a sidebar spinner alone is idle; a response-row spinner is processing', () => {
    assert.equal(run(PAGE({ sidebar: true, image: false }), JS.proc).processing, false);
    assert.equal(run(PAGE({ spinning: true, image: false }), JS.proc).processing, true);
  });
});
