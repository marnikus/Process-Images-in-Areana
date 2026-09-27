/* Output check: the first READY image wins; the user's own message is never an output (I-70, 2026-09-27).
 *
 * Owner report (twice): the image was finished on the page, the overlay said "wait for finish
 * generation", the log stayed silent after Submit and the job ended "Timeout after 120000ms".
 * The check returned on the FIRST pooled candidate that was not complete (`not_complete`) or
 * broken (`zero_width`) — before looking at the next one — and both answers were silent and
 * never reached the fallback. One lazy / hidden / broken image in the pool masked the finished one.
 * The page below mirrors the saved Arena page (docs/research/Directly Chat…html): reverse `ol`,
 * sidebar + title bar carrying JOB-IDs, a user message holding the uploaded reference
 * thumbnail (`img.aspect-square.w-32.cursor-pointer`, an output selector match) and a
 * 4052-character prompt (over the marker scan's 2000-character limit).
 */
import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const JOB = '20260927-164730-0VCQ';
const R2 = 'https://x.r2.cloudflarestorage.com/';

function findPython() {
  const cands = [process.env.PYTHON, path.join(ROOT, '.venv/bin/python'), path.join(ROOT, '.venv/Scripts/python.exe'),
    'python3', 'python'].filter(Boolean);
  for (const c of cands) {
    try { execFileSync(c, ['-c', 'import sys'], { stdio: 'ignore' }); return c; } catch { /* next */ }
  }
  return assert.fail('no Python interpreter found — set PYTHON=<path>');
}

let CHECK;
before(() => {
  const py = `import json\nfrom app.browser.output_probes import build_check_js\nprint(json.dumps(build_check_js([], "${JOB}", [])))`;
  CHECK = JSON.parse(execFileSync(findPython(), ['-c', py], { cwd: ROOT, encoding: 'utf-8' }));
});

/* jsdom has no layout: data-top / data-w give boxes, data-nw the natural size, data-incomplete a load in flight. */
function run(html) {
  const w = new JSDOM(`<body>${html}</body>`, { runScripts: 'outside-only' }).window;
  const hidden = (el) => { for (let e = el; e; e = e.parentElement) if (e.hidden) return true; return false; };
  const num = (el, k, d) => (el.dataset[k] !== undefined ? Number(el.dataset[k]) : d);
  const def = (proto, k, get) => Object.defineProperty(proto, k, { get, configurable: true });
  def(w.HTMLElement.prototype, 'offsetParent', function () { return hidden(this) ? null : this.ownerDocument.body; });
  def(w.HTMLImageElement.prototype, 'naturalWidth', function () { return num(this, 'nw', 1024); });
  def(w.HTMLImageElement.prototype, 'naturalHeight', function () { return num(this, 'nw', 1024); });
  def(w.HTMLImageElement.prototype, 'complete', function () { return this.dataset.incomplete === undefined; });
  w.Element.prototype.getBoundingClientRect = function () {
    const top = num(this, 'top', 0); const width = num(this, 'w', 100);
    return { top, left: 0, width, height: 30, right: width, bottom: top + 30 };
  };
  return JSON.parse(JSON.stringify(w.eval(CHECK)));
}

const PROMPT = `[JOB-ID: ${JOB}] ` + 'Soft pastel 3D icon, mint green, coral, deep purple. '.repeat(80);
const SIDEBAR = '<div data-sidebar="sidebar"><ul>'
  + [JOB, '20260927-104400-AAAA', '20260927-090424-RLHW'].map((j, i) => `<li><a data-sidebar="menu-button" `
    + `data-top="${288 + 36 * i}"><span class="truncate">[JOB-ID: ${j}] Soft pastel</span></a></li>`).join('')
  + '</ul></div>';
const HEADER = (spinning) => '<div class="sticky top-0 flex w-full"><div class="flex min-w-0 flex-1 items-center gap-2">'
  + (spinning ? '<div class="h-5 w-5 flex-shrink-0 animate-spin"><canvas></canvas></div>' : '')
  + '<span><span class="truncate">Max</span></span></div></div>';
const OUTPUT = `<div class="no-scrollbar"><img class="h-full w-full object-contain" data-top="520" data-w="650" src="${R2}out.png"></div>`;
const USER_MSG = '<div class="mx-auto max-w-[800px] flex w-full justify-end">'
  + '<div class="group flex max-w-[min(768px,100%)] flex-col gap-1 self-end" data-top="-900"><div class="flex flex-col gap-4">'
  + '<div class="flex w-full flex-row items-center gap-2 ml-auto max-w-2xl flex-wrap justify-end"><div class="w-fit"><div class="relative">'
  + `<img alt="icon-location-pin.png" class="aspect-square w-32 cursor-pointer overflow-hidden rounded-lg object-cover" data-top="-950" data-w="128" src="${R2}ref.png">`
  + `</div></div></div><div class="rounded-xl"><p class="whitespace-pre-wrap" data-top="-880">${PROMPT}</p></div></div></div></div>`;
const PAGE = ({ output = OUTPUT, extra = '', spinning = false } = {}) => SIDEBAR
  + `<main><div class="sticky top-0 flex" data-top="90"><span>[JOB-ID: ${JOB}] Soft pastel</span></div>`
  + '<ol class="mt-8 flex w-full flex-col-reverse justify-end gap">'
  + `<div class="mx-auto max-w-[800px] w-full" data-top="480"><div class="relative flex w-full flex-col">${HEADER(spinning)}${output}${extra}</div></div>`
  + USER_MSG + '</ol></main>';

const LAZY_COPY = `<img loading="lazy" class="h-[50vh] w-auto" data-incomplete="1" data-nw="0" data-w="0" data-top="600" src="${R2}full.png">`;
const BROKEN = `<img class="h-full w-full" data-nw="0" data-top="700" data-w="650" src="${R2}broken.png">`;

describe('output check — a waiting image never masks the finished one', () => {
  test('control: the reported page with only the finished image → ready', () => {
    const r = run(PAGE());
    assert.equal(r.ready, true, r.reason);
    assert.equal(r.src, `${R2}out.png`);
  });

  test('long prompt marker is found without a broad ancestor text scan', () => {
    const r = run(PAGE());
    assert.equal(r.ready, true, r.reason);
    assert.equal(r.jobFound, true);
    assert.equal(r.associatedJobId, JOB);
    assert.equal(r.jobTop, 0, 'the active prompt marker beats its sidebar duplicate');
    assert.equal(CHECK.includes("querySelectorAll('div, span, p, pre')"), false);
  });

  test('finished image + a never-loading lazy copy → ready (was not_complete until the 120 s timeout)', () => {
    const r = run(PAGE({ extra: LAZY_COPY }));
    assert.equal(r.ready, true, r.reason);
    assert.equal(r.src, `${R2}out.png`);
  });

  test('finished image + a broken image → ready (was zero_width until the timeout)', () => {
    const r = run(PAGE({ extra: BROKEN }));
    assert.equal(r.ready, true, r.reason);
    assert.equal(r.src, `${R2}out.png`);
  });

  test('only a loading image → still waits (never downloads a half image)', () => {
    const r = run(PAGE({ output: '', extra: LAZY_COPY }));
    assert.equal(r.ready, false);
    assert.equal(r.reason, 'not_complete');
  });

  test('a response-row spinner still holds a ready image (generation not finished)', () => {
    const r = run(PAGE({ extra: LAZY_COPY, spinning: true }));
    assert.equal(r.ready, false);
    assert.equal(r.reason, 'generating_spinner_visible');
  });
});

describe('output check — the uploaded reference in the user message is never the output', () => {
  test('spinner gone, output not rendered yet: the thumbnail is filtered as user_message, nothing is taken', () => {
    const r = run(PAGE({ output: '' }));
    assert.equal(r.ready, false);
    assert.notEqual(r.src, `${R2}ref.png`);
    assert.ok(r.debugFiltered.some((f) => f.reason === 'user_message' && f.src.endsWith('ref.png')), JSON.stringify(r.debugFiltered));
  });
});
