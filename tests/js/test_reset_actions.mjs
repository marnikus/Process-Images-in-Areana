/**
 * url-list/reset.js — the row's working state + the Stop / Clear-time actions.
 *
 * The user's report showed a row that never changed after Cancel: STATUS stayed
 * `unchecked` (it printed the CDP validation status, not the job state), the job
 * line stayed empty so the Stop button stayed disabled, and Clear time answered
 * `{"ok": false, "error": "job still running on this tab"}` with no visible
 * feedback. This module owns the missing half: the working state derived from
 * the pool page the row owns (D-7) and the two reset actions with their honest
 * replies/wording.
 *
 * RED at 71970e1: `app/ui/web/js/panels/url-list/reset.js` does not exist.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';
import { bootPage } from './page_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list');
const WEB = path.resolve(__dirname, '../../app/ui/web');
const read = (f) => fs.readFileSync(path.join(DIR, f), 'utf-8');

function harness({ log = [] } = {}) {
  const byId = {};
  const slots = { calls: [], replies: {} };
  const timers = [];
  const bridge = new Proxy({}, {
    get(_t, k) {
      if (typeof k !== 'string') return undefined;
      return (...args) => {
        const cb = args.find((a) => typeof a === 'function');
        slots.calls.push({ slot: k, args: args.filter((a) => typeof a !== 'function') });
        if (cb) cb(typeof slots.replies[k] === 'function' ? slots.replies[k](...args) : JSON.stringify(slots.replies[k] ?? { ok: true }));
      };
    },
  });
  const sandbox = {
    console, JSON, Math, Object, Array, Map, Set, String, Number, parseInt, Date, Error, isNaN,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout() {},
    LogConsole: { log: (m, l) => log.push({ m, l }) },
    document: { getElementById: (id) => byId[id] || null, addEventListener() {} },
    TabLabel: { of: (t, p) => (p && p.tab_label) || t },
    PagePoolPanel: { fmt: (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}` },
  };
  sandbox.window = sandbox;
  sandbox.App = { bridge, state: { urls: [] } };
  vm.createContext(sandbox);
  for (const f of ['store.js', 'matching.js', 'reset.js']) {
    vm.runInContext(read(f), sandbox, { filename: f });
  }
  return { R: sandbox.window.UrlListReset, sandbox, byId, slots, log, timers, bridge };
}

/** A row with the two cells the module touches (bookmark → tab → status → cool). */
function row(urlId, tabId) {
  const tr = new El('tr');
  tr.dataset.urlId = urlId;
  const status = new El('span');
  status.className = 'url-status url-status-unchecked';
  status.textContent = 'unchecked';
  tr.appendChild(status);
  const cool = new El('td');
  cool.className = 'url-cool-cell';
  tr.appendChild(cool);
  const stop = new El('button');
  stop.dataset = { action: 'stop-job', urlId, tabId };
  tr.appendChild(stop);
  return tr;
}

const store_urls = (S, urls) => { S.UrlListStore.snapshotUrls = () => urls; };

describe('UrlListReset.stateLabel / fillStatusCell (D-7)', () => {
  test('a busy-like page reads processing, a timer reads cooldown, a free page reads ready', () => {
    const { R } = harness();
    assert.equal(R.stateLabel({ status: 'busy', cooldown_remaining: 0 }), 'processing');
    assert.equal(R.stateLabel({ status: 'waiting_generation' }), 'processing');
    assert.equal(R.stateLabel({ status: 'waiting_captcha' }), 'processing');
    assert.equal(R.stateLabel({ status: 'cooldown', cooldown_remaining: 271 }), 'cooldown');
    assert.equal(R.stateLabel({ status: 'steady', cooldown_remaining: 0 }), 'ready');
    assert.equal(R.stateLabel(null), '', 'a row owning no pool page keeps its validation status');
  });

  test('a busy tab with a live countdown still reads processing (the job is the headline)', () => {
    const { R } = harness();
    assert.equal(R.stateLabel({ status: 'busy', cooldown_remaining: 900 }), 'processing');
  });

  test('fillStatusCell rewrites the pill from the pool page', () => {
    const { R } = harness();
    const tr = row('u1', 't1');
    const cell = tr.querySelector('.url-status');
    assert.equal(R.fillStatusCell(tr, { status: 'cooldown', cooldown_remaining: 300 }), true);
    assert.equal(cell.textContent, 'cooldown');
    assert.ok(cell.className.includes('url-status-cooldown'), cell.className);
    R.fillStatusCell(tr, { status: 'steady', cooldown_remaining: 0 });
    assert.equal(cell.textContent, 'ready');
    assert.ok(cell.className.includes('url-status-ready'), cell.className);
  });

  test('a row that owns no pooled tab gets its validation status back', () => {
    const { R, sandbox } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: null, status: 'unchecked' }]);
    const tr = row('u1', null);
    const cell = tr.querySelector('.url-status');
    cell.className = 'url-status url-status-ready';   // stale working state from the last pass
    cell.textContent = 'ready';
    assert.equal(R.fillStatusCell(tr, null), true, 'a stale working state must not stick');
    assert.equal(cell.textContent, 'unchecked');
    assert.ok(cell.className.includes('url-status-unchecked'));
  });

  test('fillStatusCell leaves an unknown pill alone (no row in the store)', () => {
    const { R } = harness();
    const tr = row('u1', null);
    const cell = tr.querySelector('.url-status');
    assert.equal(R.fillStatusCell(tr, null), false);
    assert.equal(cell.textContent, 'unchecked');
    assert.ok(cell.className.includes('url-status-unchecked'));
  });

  test('an errored pooled page shows its own status, never a fake ready', () => {
    const { R } = harness();
    assert.equal(R.stateLabel({ status: 'error', cooldown_remaining: 0 }), 'error');
  });
});

describe('UrlListReset.jobLine (F-5)', () => {
  const pages = [
    { tab_id: 't1', current_image: 'a.png', status: 'busy' },
    { tab_id: 't2', current_image: '', status: 'busy' },
    { tab_id: 't3', current_image: '', status: 'steady' },
  ];

  test('shows the running image, and a busy tab without a lost image still shows busy', () => {
    const { R } = harness();
    assert.equal(R.jobLine(pages, 't1'), '▶ a.png');
    assert.equal(R.jobLine(pages, 't2'), '⏳ busy');
    assert.equal(R.jobLine(pages, 't3'), '');
    assert.equal(R.jobLine(pages, 'ghost'), '');
    assert.equal(R.jobLine(pages, ''), '');
  });

  test('the Stop button is enabled for every line it renders', () => {
    const { R } = harness();
    assert.ok(R.jobLine(pages, 't2'), 'a busy tab with a lost image is still stoppable');
  });
});

describe('UrlListReset.stopJob / clearTime (the actions)', () => {
  test('stopJob sends the row’s tab and reports the abort honestly', () => {
    const { R, sandbox, slots, log } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: 't1' }]);
    slots.replies.stop_tab_job = { ok: true, mode: 'abort' };
    R.stopJob('u1');
    assert.deepEqual(slots.calls[0], { slot: 'stop_tab_job', args: ['t1'] });
    assert.match(log.at(-1).m, /Stop requested for tab t1/);
    assert.equal(log.at(-1).l, 'warn');
  });

  test('stopJob reports a repair as a reset with the cooldown it armed', () => {
    const { R, sandbox, slots, log } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: 't1' }]);
    slots.replies.stop_tab_job = { ok: true, mode: 'reset', seconds: 300 };
    R.stopJob('u1');
    assert.match(log.at(-1).m, /Stop: tab t1 reset/);
    assert.match(log.at(-1).m, /05:00/);
  });

  test('stopJob surfaces a refusal instead of pretending success', () => {
    const { R, sandbox, slots, log } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: 't1' }]);
    slots.replies.stop_tab_job = { ok: false, error: 'no live job on this tab' };
    R.stopJob('u1');
    assert.match(log.at(-1).m, /no live job on this tab/);
    assert.equal(log.at(-1).l, 'error');
  });

  test('stopJob warns when the row has no linked tab yet', () => {
    const { R, sandbox, slots, log } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: null }]);
    R.stopJob('u1');
    assert.equal(slots.calls.length, 0);
    assert.match(log.at(-1).m, /no linked tab/);
  });

  test('clearTime zeroes the countdown and flashes the cool cell green', () => {
    const { R, sandbox, slots, log, timers } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: 't1' }]);
    slots.replies.reset_page_cooldown = { ok: true, was: 271, busy: false, job_cleared: false };
    const tr = row('u1', 't1');
    R.clearTime('u1', tr);
    assert.deepEqual(slots.calls[0], { slot: 'reset_page_cooldown', args: ['t1'] });
    const cool = tr.querySelector('.url-cool-cell');
    assert.ok(cool.classList.contains('url-cool-cleared'), 'the clear is visible (colour change)');
    assert.equal(timers.at(-1).ms, 1200);
    timers.at(-1).fn();
    assert.equal(cool.classList.contains('url-cool-cleared'), false, 'the flash is temporary');
    assert.match(log.at(-1).m, /ready now/);
    assert.match(log.at(-1).m, /04:31/);
  });

  test('clearTime never flashes or claims ready while a job still runs', () => {
    const { R, sandbox, slots, log } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: 't1' }]);
    slots.replies.reset_page_cooldown = { ok: true, was: 120, busy: true, job_cleared: false };
    const tr = row('u1', 't1');
    R.clearTime('u1', tr);
    assert.equal(tr.querySelector('.url-cool-cell').classList.contains('url-cool-cleared'), false);
    assert.match(log.at(-1).m, /still busy/);
    assert.equal(log.at(-1).l, 'warn');
  });

  test('clearTime finds the row itself when the caller has no element (older button path)', () => {
    const { R, sandbox, slots } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: 't1' }]);
    slots.replies.reset_page_cooldown = { ok: true, was: 10, busy: false, job_cleared: true };
    const tbody = new El('tbody');
    tbody.id = 'urlTableBody';
    const tr = row('u1', 't1');
    tbody.appendChild(tr);
    sandbox.document.getElementById = (id) => (id === 'urlTableBody' ? tbody : null);
    R.clearTime('u1');
    assert.ok(tr.querySelector('.url-cool-cell').classList.contains('url-cool-cleared'));
  });

  test('coolAction routes cool-reset through clearTime and cool-edit to the pool panel', () => {
    const { R, sandbox, slots } = harness();
    store_urls(sandbox, [{ id: 'u1', tab_id: 't1' }]);
    slots.replies.reset_page_cooldown = { ok: true, was: 0, busy: false };
    const edited = [];
    sandbox.PagePoolPanel.editCooldown = (t) => edited.push(t);
    const btn = new El('button');
    btn.dataset = { action: 'cool-reset', urlId: 'u1', tabId: 't1' };
    const tr = row('u1', 't1');
    tr.appendChild(btn);
    R.coolAction('cool-reset', btn);
    assert.equal(slots.calls[0].slot, 'reset_page_cooldown');
    R.coolAction('cool-edit', btn);
    assert.deepEqual(edited, ['t1']);
  });

  test('a tab-less row is refused by coolAction, exactly like before', () => {
    const { R, log } = harness();
    const btn = new El('button');
    btn.dataset = { action: 'cool-reset', urlId: 'u1' };
    R.coolAction('cool-reset', btn);
    assert.match(log.at(-1).m, /Tab not in pool/);
  });
});

describe('the module conventions', () => {
  test('reset.js never hand-slices an id (TabLabel owns the readable label)', () => {
    const src = read('reset.js');
    assert.doesNotMatch(src, /tab_?[Ii]d\s*\.\s*slice\s*\(/);
    assert.doesNotMatch(src, /substring\s*\(/);
    assert.match(src, /TabLabel\.of/);
  });

  test('index.html loads reset.js with the other url-list modules', () => {
    const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf-8');
    assert.match(html, /<script src="js\/panels\/url-list\/reset\.js"><\/script>/);
  });

  test('arena.css styles the working states and the clear flash', () => {
    const css = fs.readFileSync(path.join(WEB, 'css/arena.css'), 'utf-8');
    for (const cls of ['url-status-processing', 'url-status-cooldown', 'url-status-ready']) {
      assert.match(css, new RegExp(`\\.${cls}\\s*\\{`), cls);
    }
    assert.match(css, /\.url-cool-cleared\s*\{/);
  });
});

describe('the URL row reflects the pool after a reset (page harness)', () => {
  /** A real <tr> with the cells the per-row pass fills (fake_dom keeps real trees). */
  function pageRow(urlId, tabId) {
    const tr = new El('tr');
    tr.dataset.urlId = urlId;
    tr.dataset.tabId = tabId || '';
    tr.dataset.url = 'https://arena.ai/c/1';
    const add = (tag, cls) => { const e = new El(tag); if (cls) e.className = cls; tr.appendChild(e); return e; };
    add('td', 'url-tab-cell');
    const pill = add('span', 'url-status url-status-unchecked');
    pill.textContent = 'unchecked';
    add('td', 'url-cool-cell');
    add('td', 'url-jobs-cell');
    add('div', 'url-job-line');
    const stop = add('button', 'btn-small url-stop-btn');
    stop.disabled = true;
    return tr;
  }

  const pooled = (extra) => ({
    tab_id: 't1', tab_label: 'marnikus@gmail.com_3045', url: 'https://arena.ai/c/1',
    status: 'steady', current_image: null, cooldown_remaining: 0, cooldown_total: 0,
    pending_penalty: 0, jobs_completed: 0, ...extra,
  });

  function harnessWithRow() {
    const h = bootPage();
    const tbody = h.anyEl('urlTableBody');
    tbody.appendChild(pageRow('u1', 't1'));
    h.sb.App.state.urls = [{ id: 'u1', tab_id: 't1', url: 'https://arena.ai/c/1', status: 'unchecked' }];
    return { h, tbody, tr: tbody.children[0] };
  }

  /** Push a pool snapshot the way Python does, then refresh the rows. */
  function snapshot(h, page, at) {
    const snap = { total: 1, steady: 0, busy: 1, cooling: 0, free: 0, pages: [page] };
    h.emit('page_pool_updated', JSON.stringify(snap));   // poolPages + job lines
    const panel = h.run('PagePoolPanel');
    panel.snapshot = snap;
    panel.snapAt = at;                                   // deterministic stamp
    h.run('UrlList').refreshCooldownCells();
  }

  test('a job in flight lights up STATUS, the job line and the Stop button', () => {
    const { h, tr } = harnessWithRow();
    snapshot(h, pooled({ status: 'busy', current_image: 'pic.png' }), 11);
    const pill = tr.querySelector('.url-status');
    assert.equal(pill.textContent, 'processing');
    assert.ok(pill.className.includes('url-status-processing'), pill.className);
    assert.equal(tr.querySelector('.url-job-line').textContent, '▶ pic.png');
    assert.equal(tr.querySelector('.url-stop-btn').disabled, false, 'the reported dead button');
  });

  test('a busy tab that lost its image is still stoppable and still not "unchecked"', () => {
    const { h, tr } = harnessWithRow();
    snapshot(h, pooled({ status: 'busy', current_image: null }), 11);
    assert.equal(tr.querySelector('.url-status').textContent, 'processing');
    assert.equal(tr.querySelector('.url-job-line').textContent, '⏳ busy');
    assert.equal(tr.querySelector('.url-stop-btn').disabled, false);
  });

  test('after the reset the same row reads cooldown with a live clock and no job line', () => {
    const { h, tr } = harnessWithRow();
    snapshot(h, pooled({ status: 'busy', current_image: 'pic.png' }), 11);
    snapshot(h, pooled({ status: 'cooldown', cooldown_remaining: 300, cooldown_total: 300 }), 12);
    assert.equal(tr.querySelector('.url-status').textContent, 'cooldown');
    assert.equal(tr.querySelector('.url-job-line').textContent, '', 'the ▶ image line is gone');
    assert.equal(tr.querySelector('.url-stop-btn').disabled, true, 'nothing left to stop');
    assert.match(tr.querySelector('.url-cool-cell').innerHTML, /05:00/);
  });

  test('a cleared row is ready again, and an unpooled row keeps its validation status', () => {
    const { h, tr } = harnessWithRow();
    snapshot(h, pooled({ status: 'steady', cooldown_remaining: 0 }), 11);
    assert.equal(tr.querySelector('.url-status').textContent, 'ready');
    snapshot(h, pooled({ status: 'steady' }), 12);      // same tab, still pooled
    const panel = h.run('PagePoolPanel');
    panel.snapshot = { total: 0, pages: [] };
    panel.snapAt = 13;
    h.run('UrlList').refreshCooldownCells();
    const pill = tr.querySelector('.url-status');
    assert.equal(pill.textContent, 'unchecked', 'no pooled tab: the validation status stays');
    assert.ok(pill.className.includes('url-status-unchecked'));
  });
});
