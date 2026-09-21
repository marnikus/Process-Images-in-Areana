/**
 * S7 url-list/render.js — the ⊘ icon only reflects the Python `receiver` flag + reason (plan §S7 tests 9-13).
 *
 * RED at base: `url-not-receiver` never appears in the template.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS = path.resolve(__dirname, '../../app/ui/web/js');
const read = (rel) => fs.readFileSync(path.join(JS, rel), 'utf-8');

function harness() {
  const sandbox = { window: {}, console: { error() {}, warn() {}, info() {}, log() {} }, setTimeout, clearTimeout };
  sandbox.window.window = sandbox.window;
  vm.createContext(sandbox);
  for (const rel of ['panels/url-list/store.js', 'panels/url-list/render.js']) {
    vm.runInContext(read(rel), sandbox, { filename: rel });
  }
  return sandbox.window.UrlListRender;
}

const iconExpr = (src) => {
  const marker = src.indexOf('url-not-receiver');
  return marker < 0 ? '' : src.slice(Math.max(0, marker - 60), marker + 120);
};

describe('S7 ⊘ icon', () => {
  test('test_row_html_contains_the_icon_only_for_non_receivers', () => {
    const render = harness();
    const html = render.rowHtml({ id: 'u1', url: 'https://arena.ai/c', receiver: false, receiver_reason: 'offline' });
    assert.match(html, /url-not-receiver/);
    assert.match(html, /title="offline"/);
    const clean = render.rowHtml({ id: 'u1', url: 'https://arena.ai/c', receiver: true });
    assert.ok(!clean.includes('url-not-receiver'), 'a receiver row must not flash an icon');
  });

  test('test_the_icon_sits_in_the_status_cell', () => {
    const render = harness();
    const html = render.rowHtml({ id: 'u1', url: 'https://arena.ai/c', receiver: false, receiver_reason: 'busy' });
    const marker = html.indexOf('url-not-receiver');
    const tdsBefore = html.slice(0, marker).split('<td').length - 1;
    assert.equal(tdsBefore, 3, 'the icon belongs to the 3rd <td> (status cell) — column count unchanged');
  });

  test('test_render_js_did_not_grow', () => {
    const src = read('panels/url-list/render.js');
    assert.equal(src.split(/\r?\n/).length, 74, 'render.js stays 74 lines (D-24a net-zero)');
    const fns = src.match(/^\s{2}(?:async\s+)?[\w$]+\(/gm) || [];
    assert.equal(fns.length, 10, 'function count stays 10 (actual base; plan said 12)');
  });

  test('test_the_reason_is_the_title', () => {
    const render = harness();
    for (const reason of ['unchecked', 'not linked', 'offline', 'busy']) {
      const html = render.rowHtml({ id: 'u1', url: 'x', receiver: false, receiver_reason: reason });
      assert.ok(html.includes(`title="${reason}"`), `title must carry the Python wording "${reason}"`);
    }
  });

  test('test_no_js_side_computes_eligibility', () => {
    const expr = iconExpr(read('panels/url-list/render.js'));
    assert.match(expr, /\.receiver\b/, 'the icon keys off the flag');
    assert.ok(!expr.includes('.enabled'), 'no run-gate math in the template');
    assert.ok(!expr.includes('.tab_id'), 'no link math in the template');
  });
});
