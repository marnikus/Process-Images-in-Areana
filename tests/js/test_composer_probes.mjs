/* Tier A — composer probes (Node.js, no browser).
   RULE 8: extracts the real JS_SEND_STATE const from
   app/browser/cdp_arena.py (regex on the triple-quoted strings — the file
   under test, not a copy) and runs them against a stub document.
   Prompt insertion moved to composer_js and is tested by test_composer_prompt.mjs. */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const arenaPy = fs.readFileSync(
  path.resolve(__dirname, '../../app/browser/cdp_arena.py'), 'utf-8');

function extract(name) {
  const m = arenaPy.match(new RegExp(name + ' = """\\n([\\s\\S]*?)\\n"""'));
  assert.ok(m, `${name} const not found in cdp_arena.py`);
  return m[1];
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

function plain(value) {
  return JSON.parse(JSON.stringify(value)); // vm-realm objects fail deepEqual
}

function runSendState(buttons) {
  const sandbox = {
    document: docStub({ 'button[aria-label="Send message"]': buttons }),
  };
  vm.createContext(sandbox);
  const fn = vm.runInContext(extract('JS_SEND_STATE'), sandbox,
    { filename: 'JS_SEND_STATE' });
  return fn();
}

describe('send-state probe — Tier A (no browser)', () => {
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
