/* The Watcher's "is generating" page probe (cdp_arena JS_IS_GENERATING) — live fix 2026-09-27.
 *
 * Owner report: "Generation timeout 677s limit 180s" forever — the generation had finished.
 * Any visible `div.animate-spin` counted; now only a spinner inside a response header row
 * (the site_adapter evidence: spinner beside "Response A") is a generation, and the probe
 * lists the page's [JOB-ID]s so the watcher can tell a NEW generation from the old one.
 */
import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const PY_GEN = 'import json\nfrom app.browser.cdp_arena.js_snippets import JS_IS_GENERATING as j\nprint(json.dumps(j))';

function findPython() {
  const cands = [process.env.PYTHON, path.join(ROOT, '.venv/bin/python'), path.join(ROOT, '.venv/Scripts/python.exe'),
    'python3', 'python'].filter(Boolean);
  for (const c of cands) {
    try { execFileSync(c, ['-c', 'import sys'], { stdio: 'ignore' }); return c; } catch { /* next */ }
  }
  return assert.fail('no Python interpreter found — set PYTHON=<path>');
}

let PROBE;
before(() => { PROBE = JSON.parse(execFileSync(findPython(), ['-c', PY_GEN], { cwd: ROOT, encoding: 'utf-8' })); });

/* jsdom has no layout: [hidden] (or inside it) = no offsetParent, everything else visible. */
function probe(html) {
  const w = new JSDOM(`<body>${html}</body>`, { runScripts: 'outside-only' }).window;
  const hidden = (el) => { for (let e = el; e; e = e.parentElement) if (e.hidden) return true; return false; };
  Object.defineProperty(w.HTMLElement.prototype, 'offsetParent', {
    get() { return hidden(this) ? null : this.ownerDocument.body; }, configurable: true });
  return w.eval(PROBE);
}

const ROW = (label, attrs = '') => `<div class="flex min-w-0 flex-1 items-center gap-2" ${attrs}>`
  + `<div class="h-5 w-5 flex-shrink-0 animate-spin"><canvas></canvas></div>`
  + `<span><span class="truncate">${label}</span></span></div>`;

describe('watcher generation probe', () => {
  test('a spinner in a response header row is a generation, labelled', () => {
    const r = probe(ROW('Response A'));
    assert.equal(r.isGenerating, true);
    assert.deepEqual(JSON.parse(JSON.stringify(r.details)), [{ label: 'Response A' }]);
  });

  test('any other animate-spin (sidebar, image loader) is NOT a generation', () => {
    const r = probe('<nav><div class="animate-spin"></div></nav><div class="img"><div class="animate-spin"></div></div>');
    assert.equal(r.isGenerating, false);
    assert.equal(r.spinCount, 0);
  });

  test('a hidden response spinner is not a generation', () => {
    assert.equal(probe(ROW('Response A', 'hidden')).isGenerating, false);
  });

  test('the page JOB-IDs are listed once each; look-alikes are ignored', () => {
    const r = probe('<p>[JOB-ID: abc123] x</p><p>[JOB-ID: def456]</p><p>[JOB-ID: abc123]</p>'
      + '<p>JOB-ID: nope (JOB-ID: y) [JOB ID: z]</p>');
    assert.deepEqual(Array.from(r.jobs), ['abc123', 'def456']);
  });
});
