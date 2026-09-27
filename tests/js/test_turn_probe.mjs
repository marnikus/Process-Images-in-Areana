/* Turn probe (2026-09-27 D-1) — the REAL _TURN_JS payload on a geometry stub.
   RULE 8: extracts the payload from app/browser/turn_probe.py and runs it.
   The stub gives every node a screen rect, because the probe decides by
   visual order, not DOM order.
   The same payload was run in real Chromium on the saved arena Direct-mode
   page (design §5); this file locks those behaviours without a browser.
   Selectors below are placeholders with the site_adapter shape;
   tests/test_turn_poll.py proves the real lists are wired. */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.resolve(__dirname, '../../app/browser/turn_probe.py'), 'utf-8');
const m = src.match(/_TURN_JS = r"""\n([\s\S]*?)\n"""/);
assert.ok(m, '_TURN_JS not found in turn_probe.py');
const PAYLOAD = m[1];

const CHROME = ['[data-sidebar="sidebar"]', 'body nav', 'body aside', 'body header', 'body form'];
const SPINNER = 'div.animate-spin';
const GEN = { sels: ['main p', 'main span'], text: 'Generating image' };
const JOB = '20260927-090424-RLHW';

/* ── stub DOM: nodes with rects; kinds answer the three selector queries ── */
function node(kind, props = {}) {
  const n = { kind, children: [], parentElement: null, chrome: false, textContent: '', ...props };
  n.getBoundingClientRect = () => {
    const r = n.rect || { left: 0, top: 0, width: 0, height: 0 };
    return { ...r, right: r.left + r.width, bottom: r.top + r.height };
  };
  n.closest = () => (chromeOf(n) ? n : null);
  return n;
}
function chromeOf(n) {
  for (let cur = n; cur; cur = cur.parentElement) if (cur.chrome) return true;
  return false;
}
const R = (top, w = 600, h = 20, left = 300) => ({ left, top, width: w, height: h });

function page(items) {
  const body = node('body', { rect: R(0, 1200, 3000, 0) });
  const texts = [];
  const all = [];
  for (const it of items) {
    const el = node(it.kind, it);
    el.parentElement = it.parent || body;
    if (it.text !== undefined) {
      el.textContent = it.text;
      texts.push({ nodeValue: it.text, parentElement: el });
    }
    all.push(el);
  }
  const doc = {
    body,
    createTreeWalker: () => {
      let i = -1;
      return { nextNode: () => (++i < texts.length ? texts[i] : null) };
    },
    querySelectorAll: (sel) => all.filter((n) =>
      (sel === SPINNER && n.kind === 'spinner') ||
      (sel === GEN.sels.join(',') && n.kind === 'status') ||
      (sel === 'img' && n.kind === 'img')),
  };
  return doc;
}

function run(doc, jobId = JOB) {
  const sandbox = {
    document: doc,
    NodeFilter: { SHOW_TEXT: 4 },
    getComputedStyle: (el) => ({ opacity: String(el.opacity ?? 1) }),
  };
  vm.createContext(sandbox);
  const call = `;(${PAYLOAD.trim()})(${[jobId, CHROME, SPINNER, GEN, 200].map((a) => JSON.stringify(a)).join(', ')})`;
  return JSON.parse(JSON.stringify(vm.runInContext(call, sandbox)));  // plain objects (cross-realm arrays)
}

const sidebar = node('div', { chrome: true, rect: R(0, 230, 1000, 0) });
const prompt = (top, id = JOB, extra = '') => ({ kind: 'p', text: `[JOB-ID: ${id}]\n${extra}icon prompt`, rect: R(top) });
const img = (top, props = {}) => ({ kind: 'img', src: 'blob:https://arena.ai/9f1c', naturalWidth: 1024,
  naturalHeight: 1024, complete: true, rect: R(top, 640, 640), ...props });
const thumb = (top) => ({ kind: 'img', src: 'https://r2/att/thumb.png', naturalWidth: 1024, naturalHeight: 768,
  complete: true, rect: R(top, 128, 96) });

describe('turn probe — finds THIS job\'s finished image', () => {
  test('blob output under our prompt is ready; the attachment thumbnail is only a ref', () => {
    const d = run(page([thumb(200), prompt(320), img(420)]));
    assert.equal(d.ready, true);
    assert.equal(d.src, 'blob:https://arena.ai/9f1c');
    assert.deepEqual([d.width, d.height, d.selector, d.associatedJobId], [1024, 1024, 'job_turn', JOB]);
    assert.deepEqual(d.refs, ['https://r2/att/thumb.png']);
    assert.equal(d.candidates.length, 1);
  });

  test('https and data outputs are accepted the same way', () => {
    for (const s of ['https://x.r2.cloudflarestorage.com/o.png', 'data:image/png;base64,iVBOR']) {
      const d = run(page([prompt(100), img(200, { src: s })]));
      assert.equal(d.ready, true);
      assert.equal(d.src, s);
    }
  });

  test('a thumbnail alone is never the output', () => {
    const d = run(page([prompt(100), thumb(200)]));
    assert.equal(d.ready, false);
    assert.equal(d.reason, 'turn_no_image');
    assert.equal(d.turn_found, true);
  });

  test('a 2000+ character prompt is still found (text node, no length cap)', () => {
    const d = run(page([prompt(100, JOB, '## 7. Composition & Camera Angles '.repeat(80)), img(900)]));
    assert.equal(d.ready, true);
  });

  test('sidebar chat titles carrying our JOB-ID are ignored', () => {
    const title = { kind: 'span', text: `[JOB-ID: ${JOB}] Icon style guide.`, rect: R(2500, 200), parent: sidebar };
    const d = run(page([title, prompt(100), img(200)]));
    assert.equal(d.jobTop, 100, 'anchor is the chat prompt, not the (lower) sidebar title');
    assert.equal(d.ready, true);
  });

  test('only the sidebar has our JOB-ID → turn_not_found (the v4 check decides)', () => {
    const title = { kind: 'span', text: `[JOB-ID: ${JOB}] x`, rect: R(40, 200), parent: sidebar };
    const d = run(page([title, img(200)]));
    assert.deepEqual([d.turn_found, d.ready, d.reason], [false, false, 'turn_not_found']);
  });

  test('a revival resends the same id: the lowest (latest) prompt is the anchor', () => {
    const d = run(page([prompt(100), img(200, { src: 'blob:old' }), prompt(900), { kind: 'status', text: 'Generating image...', rect: R(1000) }]));
    assert.equal(d.jobTop, 900);
    assert.deepEqual([d.ready, d.generating, d.reason], [false, true, 'turn_generating']);
    assert.equal(d.candidates.length, 0, 'the old answer above our latest prompt is not ours');
  });

  test('the next prompt bounds the region: a later job\'s image is not ours', () => {
    const d = run(page([prompt(100), prompt(300, '20260927-091000-ZZZZ'), img(400)]));
    assert.equal(d.nextTop, 300);
    assert.deepEqual([d.ready, d.reason], [false, 'turn_no_image']);
  });

  test('a spinner in our answer means generating; a sidebar spinner does not', () => {
    const inAnswer = run(page([prompt(100), { kind: 'spinner', rect: R(150, 20, 20) }, img(200)]));
    assert.deepEqual([inAnswer.ready, inAnswer.generating, inAnswer.spinning], [false, true, true]);
    const other = run(page([prompt(100), { kind: 'spinner', rect: R(150, 16, 16), parent: sidebar }, img(200)]));
    assert.deepEqual([other.ready, other.generating], [true, false]);
  });

  test('"Generating image" status in the answer means generating (Direct mode has no placeholder)', () => {
    const d = run(page([prompt(100), { kind: 'status', text: 'Generating image...', rect: R(160) }]));
    assert.equal(d.reason, 'turn_generating');
    const hidden = run(page([prompt(100), { kind: 'status', text: 'Generating image...', rect: R(160, 0, 0) }]));
    assert.equal(hidden.generating, false, 'an invisible status does not count');
  });

  test('still loading or faded out → turn_image_loading', () => {
    for (const p of [{ complete: false }, { naturalWidth: 0 }, { opacity: 0 }]) {
      const d = run(page([prompt(100), img(200, p)]));
      assert.deepEqual([d.ready, d.reason], [false, 'turn_image_loading'], JSON.stringify(p));
    }
  });

  test('two finished images: the largest wins', () => {
    const d = run(page([prompt(100), img(200, { src: 'blob:small', naturalWidth: 512, naturalHeight: 512 }),
      img(900, { src: 'blob:big', naturalWidth: 2048, naturalHeight: 2048 })]));
    assert.equal(d.src, 'blob:big');
  });

  test('no job id / no token → turn_not_found; a throwing DOM → turn_error', () => {
    assert.equal(run(page([prompt(100), img(200)]), '').reason, 'turn_not_found');
    assert.equal(run(page([{ kind: 'p', text: 'plain chat', rect: R(100) }, img(200)])).reason, 'turn_not_found');
    const broken = page([prompt(100)]);
    broken.querySelectorAll = () => { throw new Error('boom'); };
    const d = run(broken);
    assert.deepEqual([d.reason, d.ready], ['turn_error', false]);
    assert.match(d.error, /boom/);
  });

  test('job ids with regex metacharacters are matched literally', () => {
    const d = run(page([prompt(100, 'a.b+c'), img(200)]), 'a.b+c');
    assert.equal(d.ready, true);
    const other = run(page([prompt(100, 'aXb+c'), img(200)]), 'a.b+c');
    assert.equal(other.turn_found, false);
  });
});
