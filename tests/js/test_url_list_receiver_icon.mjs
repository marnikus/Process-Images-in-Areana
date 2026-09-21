/**
 * url-list/render.js — the ⊘ "not used as job receiver" icon (S7, D-18).
 *
 * Python owns the decision (`UrlRow.receiver` + `receiver_title`); the row
 * template only reflects the pushed flag and shows the pushed reason as the
 * icon's title. Zero JS growth: the span lives inside the existing one-line
 * `rowHtml` template, `render.js` stays 74 lines / 12 functions (D-24a).
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list');
const CSS = path.resolve(__dirname, '../../app/ui/web/css/arena.css');
const TOOL = path.resolve(__dirname, '../../tools/js_metrics.js');
const read = (f) => fs.readFileSync(path.join(DIR, f), 'utf-8');

// Copied verbatim from tests/test_url_receivers.py REASON_TEXT (cross-layer vocabulary lock).
const REASONS = [
  'Not used as job receiver — row unchecked',
  'Not used as job receiver — no Chrome tab linked',
  'Not used as job receiver — tab not connected',
  'Not used as job receiver — tab busy with a job',
];

function loadRender() {
  const sandbox = { console, JSON, Object, Array, String, Map, Set, document: undefined };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(read('store.js') + '\n' + read('render.js'), sandbox, { filename: 'render.js' });
  return sandbox.window.UrlListRender;
}

const R = loadRender();
const tds = (html) => html.split('<td').slice(1);

describe('url-list receiver icon', () => {
  test('rowHtml contains the icon only for non-receivers', () => {
    const off = R.rowHtml({ id: 'u1', url: 'https://x', receiver: false, receiver_title: REASONS[0] });
    assert.match(off, /class="url-not-receiver"/);
    assert.match(off, /⊘/);
    const on = R.rowHtml({ id: 'u1', url: 'https://x', receiver: true, receiver_title: '' });
    assert.doesNotMatch(on, /url-not-receiver/);
    const legacy = R.rowHtml({ id: 'u1', url: 'https://x' });  // no flag at all (old payload): no icon flash
    assert.doesNotMatch(legacy, /url-not-receiver/);
  });

  test('the icon sits in the status cell and the column count is unchanged', () => {
    const html = R.rowHtml({ id: 'u1', url: 'https://x', receiver: false, receiver_title: REASONS[1] });
    const cells = tds(html);
    // 9 since the readable-tab-id round added the `Tab` column (D-7); the
    // status cell moved with it and the icon still rides inside it.
    assert.equal(cells.length, 9, 'url-table header has 9 columns (the new Tab one)');
    assert.match(cells[3], /url-status/);
    assert.match(cells[3], /url-not-receiver/);
  });

  test('the reason is the title (Python wording, escaped)', () => {
    for (const reason of REASONS) {
      const html = R.rowHtml({ id: 'u1', url: 'https://x', receiver: false, receiver_title: reason });
      assert.ok(html.includes(`title="${reason}"`), reason);
    }
    const evil = R.rowHtml({ id: 'u1', url: 'https://x', receiver: false, receiver_title: '<b onmouseover=x>' });
    assert.doesNotMatch(evil, /<b onmouseover/);
  });

  /* The 2026-09-21 round moved the row's cells into cells.js (D-4/D-7), so the
     template file came out SMALLER — the guard is re-pinned to the new numbers
     (re-run the tool in the commit that grows it again). */
  test('render.js did not grow (net-zero guard, D-24a)', () => {
    const src = read('render.js');
    assert.equal(src.split('\n').length, 46);  // tools/js_metrics.js fileLines (the ratchet's number)
    const metrics = JSON.parse(execFileSync('node', [TOOL, DIR, '--json'], { encoding: 'utf-8' }));
    const funcs = metrics.filter((e) => e.file && e.file.endsWith('url-list/render.js') && !e.isFile).length;
    assert.equal(funcs, 7);  // the ratchet's own counter (tools/js_metrics.js)
  });

  test('no JS side computes eligibility (the flag is authoritative)', () => {
    const src = read('render.js');
    const iconLine = src.split('\n').find((l) => l.includes('url-not-receiver'));
    assert.ok(iconLine, 'the icon is in the template');
    assert.doesNotMatch(iconLine, /u\.enabled\s*[!=]==?\s*(true|false)\s*&&\s*u\.tab_id/);
    assert.doesNotMatch(iconLine, /is_connected/);
    assert.doesNotMatch(src, /receiver\s*=\s*.*enabled/);
  });

  test('arena.css styles the icon', () => {
    const css = fs.readFileSync(CSS, 'utf-8');
    assert.match(css, /\.url-not-receiver\s*\{[^}]*cursor:\s*help/);
  });
});
