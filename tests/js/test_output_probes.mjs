/* Tier A — output probes (Node.js, no browser).
   RULE 8: extracts the REAL JS_BASELINE_V3 / JS_CHECK_NEW_OUTPUT_V3
   templates from app/browser/output_probes.py and executes them against a
   stub document. Locks the v4 behaviour (strict JOB-ID verification,
   below-prompt ordering, spinner wait, mismatch error) before/after any
   payload refactor.
   RULE 21: __PLACEHOLDER__ tokens are filled with representative
   selectors, exactly like the app does at import; the real selector lists
   are proven wired by tests/test_probe_selectors.py. */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const probesPy = fs.readFileSync(
  path.resolve(__dirname, '../../app/browser/output_probes.py'), 'utf-8');

function extract(name) {
  const m = probesPy.match(new RegExp(name + ' = [^"]*"""\\n([\\s\\S]*?)\\n"""'));
  assert.ok(m, `${name} not found in output_probes.py`);
  // The Python triple-quoted string unescapes \\ -> \ at import; the only
  // escaped sequence in these payloads is the JOB-ID regex, so mirror it.
  return m[1].replaceAll('\\\\', '\\');
}

const SELECTORS = ['img.aspect-square.cursor-pointer'];
const SPINNER = 'div.animate-spin';
const MODEL_ROW = 'div.flex.min-w-0.flex-1.items-center.gap-2';
const MODEL_LABEL = 'span.truncate';

function fill(template) {
  return template
    .replaceAll('__SELECTORS__', JSON.stringify(SELECTORS))
    .replaceAll('__SPINNER_SELECTOR__', JSON.stringify(SPINNER))
    .replaceAll('__MODEL_ROW_SCOPE__', JSON.stringify(MODEL_ROW))
    .replaceAll('__MODEL_LABEL__', JSON.stringify(MODEL_LABEL));
}

function el(overrides = {}) {
  return {
    tagName: 'DIV', src: '', className: '', complete: true,
    naturalWidth: 0, naturalHeight: 0, offsetParent: null,
    textContent: '', innerText: '', parentElement: null,
    getBoundingClientRect: () => ({ left: 10, top: 100, width: 500, height: 500, right: 510, bottom: 600 }),
    closest: () => null, querySelector: () => null, contains: () => false,
    compareDocumentPosition: () => 0,
    classList: { contains: () => false },
    ...overrides,
  };
}

function docStub(lists, treeNodes = []) {
  return {
    querySelectorAll: (sel) => lists[sel] ? lists[sel].slice() : [],
    querySelector(sel) {
      for (const part of sel.split(',')) {
        const hit = (lists[part] || [])[0];
        if (hit) return hit;
      }
      return null;
    },
    createTreeWalker: () => ({ nextNode: () => null }),
    body: el(),
  };
}

function sandboxFor(lists) {
  return {
    document: docStub(lists),
    window: {
      innerWidth: 1280, innerHeight: 800,
      location: { href: 'https://arena.ai/image/direct' },
      getComputedStyle: () => ({ opacity: '1' }),
    },
    Node: { DOCUMENT_POSITION_FOLLOWING: 4, DOCUMENT_POSITION_PRECEDING: 2 },
    NodeFilter: { SHOW_TEXT: 4 },
    Date: { now: () => 1758300000000 },
  };
}

function runBaseline(lists) {
  const sandbox = sandboxFor(lists);
  vm.createContext(sandbox);
  return vm.runInContext(`(${fill(extract('JS_BASELINE_V3'))})()`, sandbox,
    { filename: 'JS_BASELINE_V3' });
}

function runCheck(lists, oldSrcs, correlationId, oldOutputs = []) {
  const sandbox = sandboxFor(lists);
  sandbox.oldSrcs = oldSrcs;
  sandbox.correlationId = correlationId;
  sandbox.oldOutputs = oldOutputs;
  vm.createContext(sandbox);
  const template = fill(extract('JS_CHECK_NEW_OUTPUT_V3'));
  return vm.runInContext(
    `((${template}))(oldSrcs, correlationId, oldOutputs)`, sandbox,
    { filename: 'JS_CHECK_NEW_OUTPUT_V3' });
}

// vm-realm objects fail deepEqual — round-trip like the composer test does.
function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function jobTextEl(id, top) {
  return el({
    tagName: 'SPAN', textContent: `[JOB-ID: ${id}] make it blue`,
    className: 'flex',
    getBoundingClientRect: () => ({ left: 10, top, width: 300, height: 40, right: 310, bottom: top + 40 }),
    querySelector: () => null,
  });
}

function outputImg(src, top, { width = 1024, cls = 'aspect-square cursor-pointer' } = {}) {
  return el({
    tagName: 'IMG', src, className: cls, complete: true,
    naturalWidth: width, naturalHeight: width, offsetParent: {},
    parentElement: el({ className: 'justify-start' }),
    getBoundingClientRect: () => ({ left: 10, top, width: 500, height: 500, right: 510, bottom: top + 500 }),
  });
}

describe('output probes v4 — Tier A (no browser)', () => {
  test('baseline captures loaded remote outputs, skips blob + tiny', () => {
    const res = runBaseline({
      [SPINNER]: [],
      [SELECTORS[0]]: [
        el({ src: 'blob:x', offsetParent: {} }),
        outputImg('https://r2/out-old.png', 200),
        el({ src: 'https://r2/tiny.png', naturalWidth: 10, naturalHeight: 10, offsetParent: {} }),
      ],
    });
    assert.equal(res.output_count, 1);
    assert.deepEqual(plain(res.output_srcs), ['https://r2/out-old.png']);
    assert.equal(res.spinning, false);
  });

  test('check READY: new assistant image below matching job downloads', () => {
    const res = runCheck({
      'div, span, p, pre': [jobTextEl('JOB123', 100)],
      [SELECTORS[0]]: [outputImg('https://r2/new.png', 500)],
      [SPINNER]: [],
    }, ['https://r2/out-old.png'], 'JOB123');
    assert.equal(res.ready, true);
    assert.equal(res.src, 'https://r2/new.png');
    assert.equal(res.associatedJobId, 'JOB123');
    assert.match(res.orderCheck, /CORRECT KEY MATCH/);
  });

  test('check MISMATCH: image belongs to another job -> error, not download', () => {
    // Page-reset shape: current job JOB1 is the LAST message (top 600);
    // the new-to-us image sits between old jobs JOB2 (100) and JOB3 (500),
    // so JOB1 is not among its nearby jobs -> strict mismatch, never download.
    const res = runCheck({
      'div, span, p, pre': [jobTextEl('JOB2', 100), jobTextEl('JOB3', 500), jobTextEl('JOB1', 600)],
      [SELECTORS[0]]: [outputImg('https://r2/other.png', 400)],
      [SPINNER]: [],
    }, [], 'JOB1');
    assert.equal(res.ready, false);
    assert.equal(res.reason, 'job_id_mismatch_no_matching_image');
    assert.equal(res.mismatchDetails.length, 1);
    assert.equal(res.mismatchDetails[0].associated, 'JOB2');
  });

  test('check SPINNER: visible spinner with no new image keeps waiting', () => {
    const res = runCheck({
      'div, span, p, pre': [jobTextEl('JOB123', 100)],
      [SELECTORS[0]]: [],
      [SPINNER]: [el({ className: 'animate-spin', offsetParent: {} })],
    }, [], 'JOB123');
    assert.equal(res.ready, false);
    assert.equal(res.reason, 'generating_no_new_yet');
    assert.equal(res.spinning, true);
  });

  test('check NO NEW: nothing appeared and not spinning', () => {
    const res = runCheck({
      'div, span, p, pre': [jobTextEl('JOB123', 100)],
      [SELECTORS[0]]: [],
      [SPINNER]: [],
    }, ['https://r2/out-old.png'], 'JOB123');
    assert.equal(res.ready, false);
    assert.equal(res.reason, 'no_new');
  });

  test('check OLD-NOT-READY: old src reappearing still not ready is re-pooled', () => {
    // baseline recorded the src as not-ready (incomplete, zero width) — the
    // now-finished image must become a candidate again instead of being
    // dismissed as "already seen"
    const res = runCheck({
      'div, span, p, pre': [jobTextEl('JOB123', 100)],
      [SELECTORS[0]]: [outputImg('https://r2/old-unfinished.png', 500)],
      [SPINNER]: [],
    }, ['https://r2/old-unfinished.png'], 'JOB123',
      [{ src: 'https://r2/old-unfinished.png', complete: false, naturalWidth: 0, visible: true }]);
    assert.equal(res.ready, true);
    assert.equal(res.src, 'https://r2/old-unfinished.png');
  });
});
