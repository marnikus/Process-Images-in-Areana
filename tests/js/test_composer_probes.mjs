/* Tier A — composer probes (Node.js, no browser).
   Extracts JS_INSERT_PROMPT / JS_SEND_STATE from cdp_arena module.
*/

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const candidates = [
  path.resolve(__dirname, '../../app/browser/cdp_arena/js_snippets.py'),
  path.resolve(__dirname, '../../app/browser/cdp_arena.py'),
];

function tryExtractFromText(txt, name) {
  const m = txt.match(new RegExp(name + ' = """\\n([\\s\\S]*?)\\n"""'));
  return m ? m[1] : null;
}

function extract(name) {
  for (const p of candidates) {
    try {
      if (!fs.existsSync(p)) continue;
      const txt = fs.readFileSync(p, 'utf-8');
      const val = tryExtractFromText(txt, name);
      if (val) return val;
    } catch {}
  }
  assert.fail(`${name} const not found in cdp_arena`);
}

function docStub(lists) {
  return {
    querySelectorAll: (sel) => lists[sel] || [],
    querySelector(sel) {
      for (const part of sel.split(',')) {
        const hit = (lists[part] || [])[0];
        if (hit) return hit;
      }
      return null;
    },
  };
}

function textareaStub(visible) {
  return {
    offsetParent: visible ? {} : null,
    value: '',
    events: 0,
    focus() {},
    dispatchEvent() { this.events++; },
  };
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function runInsert(lists, text) {
  const sandbox = {
    document: docStub(lists),
    Event: function (t) { this.type = t; },
    window: { HTMLTextAreaElement: { prototype: {} } },
  };
  Object.defineProperty(sandbox.window.HTMLTextAreaElement.prototype, 'value', {
    set(v) { this._reactValue = v; }, configurable: true,
  });
  vm.createContext(sandbox);
  const fn = vm.runInContext(extract('JS_INSERT_PROMPT'), sandbox, { filename: 'JS_INSERT_PROMPT' });
  return fn(text);
}

function runSendState(buttons) {
  const sandbox = {
    document: docStub({ 'button[aria-label="Send message"]': buttons }),
  };
  vm.createContext(sandbox);
  const fn = vm.runInContext(extract('JS_SEND_STATE'), sandbox, { filename: 'JS_SEND_STATE' });
  return fn();
}

const SEL_MSG = 'textarea[name="message"]';
const SEL_DESC = 'textarea[placeholder^="Describe"]';

describe('composer probes — Tier A (no browser)', () => {
  test('insert fills the VISIBLE composer, skips hidden first match', () => {
    const hidden = textareaStub(false);
    const visible = textareaStub(true);
    const text = 'x'.repeat(4213);
    const res = runInsert({ [SEL_MSG]: [hidden], [SEL_DESC]: [visible] }, text);
    assert.deepEqual(plain(res), { ok: true, len: 4213 });
    assert.equal(visible.value, text);
    assert.equal(visible._reactValue, text);
    assert.ok(visible.events >= 2);
    assert.equal(hidden.value, '');
    assert.equal(hidden._reactValue, undefined);
    assert.equal(hidden.events, 0);
  });

  test('insert reports hidden vs missing distinctly', () => {
    const resHidden = runInsert({ [SEL_MSG]: [textareaStub(false)] }, 'hi');
    assert.deepEqual(plain(resHidden), { ok: false, error: 'textarea hidden' });
    const resMissing = runInsert({}, 'hi');
    assert.deepEqual(plain(resMissing), { ok: false, error: 'textarea not found' });
  });

  test('send-state maps missing / hidden / disabled / enabled', () => {
    assert.deepEqual(plain(runSendState([])), { found: false, visible: false, enabled: false });
    assert.deepEqual(plain(runSendState([{ offsetParent: null, disabled: false }])), { found: true, visible: false, enabled: false });
    assert.deepEqual(plain(runSendState([{ offsetParent: {}, disabled: true }])), { found: true, visible: true, enabled: false });
    assert.deepEqual(plain(runSendState([
      { offsetParent: null, disabled: false },
      { offsetParent: {}, disabled: true },
      { offsetParent: {}, disabled: false },
    ])), { found: true, visible: true, enabled: true });
  });
});
