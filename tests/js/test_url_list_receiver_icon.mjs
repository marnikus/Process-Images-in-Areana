/**
 * Tier A — the ⊘ icon in url-list/render.js only reflects Python's UrlRow.receiver (S7, D-19).
 * The template stays one line; no JS-side eligibility; the title is Python's reason.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as acorn from 'acorn';
import * as walk from 'acorn-walk';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const baseDir = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list');
const renderSrc = fs.readFileSync(path.resolve(baseDir, 'render.js'), 'utf-8');

function loadRender() {
  const sandbox = { console, JSON, Math, Object, Array, Map, Set, Error, String, document: undefined };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.resolve(baseDir, 'store.js'), 'utf-8') + '\n' + renderSrc, sandbox, { filename: 'render.js' });
  return sandbox.UrlListRender;
}

const REASONS = ['unchecked', 'not linked', 'offline', 'busy'];   // copied from tests/test_url_receivers.py

describe('url-list receiver icon (S7)', () => {
  test('row html contains the icon only for non-receivers', () => {
    const R = loadRender();
    const off = R.rowHtml({ id: 'u1', url: 'https://arena.ai/x', receiver: false, receiver_reason: 'offline' });
    assert.ok(off.includes('class="url-not-receiver"') && off.includes('⊘') && off.includes('title="offline"'));
    const on = R.rowHtml({ id: 'u2', url: 'https://arena.ai/y', receiver: true, receiver_reason: '' });
    assert.ok(!on.includes('url-not-receiver'));
    const legacy = R.rowHtml({ id: 'u3', url: 'https://arena.ai/z' });      // no flag ⇒ no icon
    assert.ok(!legacy.includes('url-not-receiver'));
  });

  test('the icon sits in the status cell (column count unchanged)', () => {
    const R = loadRender();
    const html = R.rowHtml({ id: 'u1', url: 'x', receiver: false, receiver_reason: 'busy' });
    const cells = html.split('<td').slice(1);
    assert.equal(cells.length, 8);
    assert.ok(cells[2].includes('url-not-receiver'), 'icon must live in the 3rd (status) cell');
  });

  test('render.js did not grow (net-zero guard, D-24a)', () => {
    assert.equal(renderSrc.split('\n').length, 74);
    let funcs = 0;                                   // the same count the JS quality lane records (acorn)
    walk.full(acorn.parse(renderSrc, { ecmaVersion: 2022 }), (node) => { if (/Function/.test(node.type)) funcs += 1; });
    assert.equal(funcs, 12);
  });

  test('the reason is the title for every Python reason', () => {
    const R = loadRender();
    for (const reason of REASONS) {
      const html = R.rowHtml({ id: 'u', url: 'x', receiver: false, receiver_reason: reason });
      assert.ok(html.includes(`title="${reason}"`), reason);
    }
  });

  test('no JS side computes eligibility for the icon', () => {
    const iconLine = renderSrc.split('\n').find((l) => l.includes('url-not-receiver')) || '';
    assert.ok(iconLine.includes('u.receiver'));
    assert.ok(!iconLine.includes('u.enabled') || iconLine.indexOf('u.enabled') < iconLine.indexOf('url-not-receiver'),
      'the icon must not be derived from the checkbox');
    assert.ok(!/receiver\s*=\s*\(?u\.tab_id/.test(renderSrc));
  });
});
