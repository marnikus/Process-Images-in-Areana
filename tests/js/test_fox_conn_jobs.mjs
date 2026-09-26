/**
 * I-64 — Firefox rows in the URL list and the pool table (2026-09-25).
 *
 * CONN shows the lane with a browser icon (🌐 cdp / 🦊 uivision) and a Firefox
 * row never borrows a Chrome tab match; the pool row marks a Firefox worker; a
 * click on any JOBS count edits it through `set_page_jobs` — without changing
 * either JOBS template (the display-only pins stay green).
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

function sandbox(extra = {}) {
  const box = { console, JSON, Object, Array, String, Number, Math, Date, parseInt, isNaN, ...extra };
  box.window = box;
  vm.createContext(box);
  return box;
}

function load(box, ...files) {
  for (const f of files) vm.runInContext(read(f), box, { filename: f });
  return box;
}

const esc = (s) => String(s ?? '').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const MATCH = { title: 'Arena', url: 'https://arena.ai/c/1', kind: 'url', score: 9 };

describe('the CONN cell names the lane', () => {
  const C = load(sandbox(), 'panels/url-list/conn.js').UrlListConn;

  test('a Firefox row shows 🦊 uivision and never a Chrome match', () => {
    const html = C.cell({ conn: 'uivision', browser: 'firefox', tab_id: 'P.x_tab1' }, MATCH, { tabs: [1] }, esc);
    assert.match(html, /🦊 uivision/);
    assert.doesNotMatch(html, /● url/);
    assert.match(html, /P\.x_tab1/);
  });

  test('a Chrome row keeps the match evidence behind 🌐 cdp', () => {
    assert.match(C.cell({ conn: 'cdp', browser: 'chrome' }, MATCH, { tabs: [1] }, esc), /🌐 cdp ● url \(9\)/);
    assert.match(C.cell({ conn: 'cdp', browser: 'chrome' }, null, { tabs: [1] }, esc), /🌐 cdp ○ no tab/);
  });

  test('an unlinked row keeps the old wording', () => {
    assert.match(C.cell({}, null, { tabs: [] }, esc), />○ no chrome</);
    assert.match(C.cell({}, MATCH, { tabs: [1] }, esc), />● url \(9\)</);
  });

  test('cdp-render hands the row to UrlListConn, and still works without it', () => {
    const box = load(sandbox(), 'panels/cdp/cdp-render.js');
    const plain = box.CDPRender._connCellHtml(null, { tabs: [] }, { conn: 'uivision' });
    assert.match(plain, /○ no chrome/);                              // conn.js not loaded: old fallback
    load(box, 'panels/url-list/conn.js');
    const fox = box.CDPRender._connCellHtml(MATCH, { tabs: [1] }, { conn: 'uivision', tab_id: 'P.x_tab1' });
    assert.match(fox, /🦊 uivision/);
  });
});

describe('the pool row marks a Firefox worker', () => {
  const box = load(sandbox({ document: { getElementById: () => null } }),
    'core/tab-label.js', 'panels/page-pool/store.js', 'panels/page-pool/cells.js', 'panels/page-pool/render.js');
  const row = (extra) => box.PagePoolRender._rowHtml({ tab_id: 'P.x_tab1', tab_label: 'Profile1_0007',
    worker_no: 3, title: 'T', url: 'https://arena.ai', status: 'steady', jobs_completed: 2, ...extra });

  test('🦊 before the worker number for Firefox, nothing for Chrome', () => {
    assert.match(row({ browser_mark: '🦊 ' }), /white-space:nowrap;">🦊 <b class="worker-no">#3<\/b> Profile1_0007<\/td>/);
    assert.match(row({}), /white-space:nowrap;"><b class="worker-no">#3<\/b>/);
  });
});

function fakeRow(tabId, poolTitle) {
  const cell = { textContent: '7', closest: (sel) => (sel === 'tr' ? tr : cell) };
  const tr = {
    dataset: tabId ? { tabId } : {},
    querySelector: (sel) => (sel === '.pool-tab-cell' && poolTitle ? { getAttribute: () => poolTitle } : null),
  };
  return cell;
}

describe('a JOBS count is click-to-edit', () => {
  function jobsBox() {
    const calls = [], lines = [], refreshed = [];
    const box = sandbox({ LogConsole: { log: (t, l) => lines.push([t, l]) } });
    box.App = { bridge: { set_page_jobs: (tab, n, cb) => { calls.push([tab, n]); cb(JSON.stringify({ ok: true, jobs: n })); } } };
    box.PagePoolActions = { refresh: () => refreshed.push(1) };
    box.TabLabel = { of: (id) => `L(${id})` };
    load(box, 'core/jobs-edit.js');
    return { J: box.JobsEdit, calls, lines, refreshed, box };
  }

  test('the tab id comes from the URL-list row or the pool row', () => {
    const { J } = jobsBox();
    assert.equal(J.tabOf(fakeRow('P.x_tab1', null)), 'P.x_tab1');
    assert.equal(J.tabOf(fakeRow('', 'ABCDEF')), 'ABCDEF');
    assert.equal(J.tabOf({ closest: () => null }), '');
  });

  test('only whole numbers in range are sent', () => {
    const { J } = jobsBox();
    assert.equal(J.parse(' 12 '), 12);
    assert.equal(J.parse('0'), 0);
    for (const bad of ['-1', '1.5', 'x', '1000000', '', '  ', null]) assert.equal(J.parse(bad), null, String(bad));
  });

  test('a click asks, sends, logs and refreshes the pool', () => {
    const { J, calls, lines, refreshed, box } = jobsBox();
    box.Dialog = { promptEdit: (title, initial, ok, onOk) => { assert.equal(initial, '7'); onOk('3'); } };
    J.onClick({ target: fakeRow('P.x_tab1', null) });
    assert.deepEqual(calls, [['P.x_tab1', 3]]);
    assert.deepEqual(lines.at(-1), ['✏ Jobs for L(P.x_tab1) set to 3', 'info']);
    assert.equal(refreshed.length, 1);
    J.send('P.x_tab1', 'abc');
    assert.equal(calls.length, 1);
    assert.equal(lines.at(-1)[1], 'warn');
  });

  test('a refused edit is logged as an error; a click elsewhere does nothing', () => {
    const { J, lines, calls } = jobsBox();
    J.onReply('P.x_tab1', JSON.stringify({ ok: false, error: 'tab not in pool' }));
    assert.deepEqual(lines.at(-1), ['Jobs edit failed: tab not in pool', 'error']);
    J.onReply('P.x_tab1', 'not json');
    assert.equal(lines.at(-1)[1], 'error');
    J.onClick({ target: { closest: () => null } });
    assert.equal(calls.length, 0);
  });

  test('the listener is installed once per document', () => {
    const { J } = jobsBox();
    const added = [];
    const doc = { addEventListener: (type) => added.push(type) };
    assert.equal(J.install(doc), true);
    assert.equal(J.install(doc), false);
    assert.deepEqual(added, ['click']);
  });
});
