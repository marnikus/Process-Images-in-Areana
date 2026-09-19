/* Tier A — composer probes (Node.js, no browser).
   RULE 8: extracts the REAL JS_INSERT_PROMPT / JS_SEND_STATE templates from
   app/browser/cdp_arena.py (regex on the triple-quoted strings — the file
   under test, not a copy; C3 split: cdp_arena/js_snippets.py) and runs them against a stub document.
   RULE 21: the templates carry __PLACEHOLDER__ tokens; the app fills them
   from site_adapter at import (wiring proven by tests/test_probe_selectors.py);
   here we substitute representative selectors, exactly like the app does.
   Regression: the error-state DOM offers a hidden first-match textarea;
   insert must fill the VISIBLE composer or Send stays disabled forever. */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// The payloads live in the cdp_arena package (C3 split); the facade is kept
// as a fallback so the test keeps working if they move back.
const candidates = [
  path.resolve(__dirname, '../../app/browser/cdp_arena/js_snippets.py'),
  path.resolve(__dirname, '../../app/browser/cdp_arena.py'),
];

function extract(name) {
  // Matches both `NAME = """template"""` and `NAME = _inject("""template""", ...)`.
  for (const candidate of candidates) {
    if (!fs.existsSync(candidate)) continue;
    const txt = fs.readFileSync(candidate, 'utf-8');
    const m = txt.match(new RegExp(name + ' = [^"]*"""\\n([\\s\\S]*?)\\n"""'));
    if (m) return m[1];
  }
  assert.fail(`${name} const not found in cdp_arena package`);
}

// Same substitution the app performs at import (json.dumps of selector payloads).
function fill(template, name, value) {
  return template.replaceAll(name, JSON.stringify(value));
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
  return JSON.parse(JSON.stringify(value)); // vm-realm objects fail deepEqual
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
  const template = fill(extract('JS_INSERT_PROMPT'), '__TEXTAREA_SELECTORS__',
    [SEL_MSG, SEL_DESC]);
  const fn = vm.runInContext(template, sandbox,
    { filename: 'JS_INSERT_PROMPT' });
  return fn(text);
}

function runSendState(buttons) {
  const sandbox = {
    document: docStub({ 'button[aria-label="Send message"]': buttons }),
  };
  vm.createContext(sandbox);
  const template = fill(extract('JS_SEND_STATE'), '__SEND_PRESENCE_SELECTOR__',
    'button[aria-label="Send message"]');
  const fn = vm.runInContext(template, sandbox,
    { filename: 'JS_SEND_STATE' });
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
    assert.ok(visible.events >= 2); // input + change dispatched
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
    assert.deepEqual(plain(runSendState([])),
      { found: false, visible: false, enabled: false });
    assert.deepEqual(plain(runSendState([{ offsetParent: null, disabled: false }])),
      { found: true, visible: false, enabled: false });
    assert.deepEqual(plain(runSendState([{ offsetParent: {}, disabled: true }])),
      { found: true, visible: true, enabled: false });
    assert.deepEqual(plain(runSendState([
      { offsetParent: null, disabled: false },
      { offsetParent: {}, disabled: true },
      { offsetParent: {}, disabled: false },
    ])), { found: true, visible: true, enabled: true });
  });
});
