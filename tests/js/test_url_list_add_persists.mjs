/**
 * url-list/actions.js — an added / edited URL row must stay (B7).
 *
 * Root cause (bugfix-verification.md §B7): after `add_url` / `edit_url`
 * replied ok, `_onAdd` / `_applyEdit` pushed `window.App.state.urls` back to
 * Python via `ArenaHistory.recordGlobal('urls', …)` 100 ms later. That
 * snapshot is STALE — `arena_state_updated` is applied after a 250 ms
 * debounce — so Python's `_remember_urls` overwrote its rows with the list
 * WITHOUT the new row and re-emitted state: the row vanished ~1 s after it
 * appeared. Python's `commit_urls` is the single write path and already
 * records the undo entry, so the client must never push rows back.
 *
 * Harness: the REAL `arena-history.js` + `url-list/actions.js` in one V8
 * context; the bridge fake emulates Python (`add_url` commits server rows,
 * `push_global_history('urls')` applies the pushed snapshot like
 * `_remember_urls` does). Timers are queued and flushed explicitly.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS = path.resolve(__dirname, '../../app/ui/web/js');
const read = (rel) => fs.readFileSync(path.join(JS, rel), 'utf-8');

function harness() {
  const byId = {};
  const timers = [];
  const logs = [];
  // "Python" side: rows as committed by the slots.
  const server = { urls: [{ id: 'url_old', url: 'https://old.example', tab_id: 'T1' }] };
  const calls = { add_url: [], edit_url: [], push_global_history: [] };
  const bridge = {
    add_url(val, cb) {
      calls.add_url.push(val);
      server.urls = [...server.urls, { id: 'url_new', url: val, tab_id: '' }];   // commit_urls()
      cb(JSON.stringify({ ok: true, id: 'url_new' }));
    },
    edit_url(id, url, cb) {
      calls.edit_url.push([id, url]);
      server.urls = server.urls.map((u) => (u.id === id ? { ...u, url } : u));
      cb(JSON.stringify({ ok: true, url }));
    },
    push_global_history(kind, json) {
      calls.push_global_history.push([kind, json]);
      if (kind === 'urls') server.urls = JSON.parse(json);   // _remember_urls() applies the push
    },
  };
  const sandbox = {
    console, JSON, Set, WeakMap, Map, Object, Array, String, Number,
    document: { getElementById: (id) => byId[id] || null, readyState: 'complete', addEventListener() {} },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout() {},
    LogConsole: { log: (m, lvl) => logs.push([m, lvl || 'info']) },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(read('arena-history.js'), sandbox, { filename: 'arena-history.js' });
  vm.runInContext(read('panels/url-list/actions.js'), sandbox, { filename: 'actions.js' });
  // The client's copy of the state — still the PRE-add list (debounced apply pending).
  const stale = () => [...server.urls.filter((u) => u.id !== 'url_new').map((u) => ({ ...u }))];
  sandbox.App = { bridge, state: { urls: stale() } };
  sandbox.window.App = sandbox.App;
  sandbox.UrlListStore = { snapshotUrls: () => sandbox.App.state.urls.map((u) => ({ ...u })) };
  sandbox.window.UrlListStore = sandbox.UrlListStore;
  byId.urlInput = new El('input');
  const flush = () => { while (timers.length) timers.shift().fn(); };
  return { A: sandbox.window.UrlListActions, byId, bridge, calls, server, logs, flush, sandbox };
}

describe('URL add / edit never pushes a stale row snapshot back to Python (B7)', () => {
  test('Add: row committed by Python survives; no push_global_history; input cleared', () => {
    const h = harness();
    h.byId.urlInput.value = '  https://arena.example/new  ';
    h.A.addUrl();
    h.flush();                                       // any deferred push-back would run here
    assert.deepEqual(h.calls.add_url, ['https://arena.example/new']);
    assert.equal(h.calls.push_global_history.length, 0, 'client must not echo rows back');
    assert.ok(h.server.urls.some((u) => u.id === 'url_new'), 'the new row is still on the server');
    assert.ok(h.server.urls.some((u) => u.id === 'url_old' && u.tab_id === 'T1'), 'old rows untouched');
    assert.equal(h.byId.urlInput.value, '');
    assert.ok(h.logs.some(([m, lvl]) => m.startsWith('URL added:') && lvl === 'success'));
  });

  test('Add: empty input is ignored, failure reply is logged as error', () => {
    const h = harness();
    h.byId.urlInput.value = '   ';
    h.A.addUrl();
    assert.equal(h.calls.add_url.length, 0);
    h.bridge.add_url = (val, cb) => { h.calls.add_url.push(val); cb(JSON.stringify({ ok: false, error: 'URL already exists' })); };
    h.byId.urlInput.value = 'https://dup.example';
    h.A.addUrl();
    h.flush();
    assert.ok(h.logs.some(([m, lvl]) => m === 'Add URL failed: URL already exists' && lvl === 'error'));
    assert.equal(h.byId.urlInput.value, 'https://dup.example', 'failed add keeps the typed text');
    assert.equal(h.calls.push_global_history.length, 0);
  });

  test('Edit: committed change survives; no push_global_history', () => {
    const h = harness();
    h.A._applyEdit('url_old', 'https://old.example/edited');
    h.flush();
    assert.deepEqual(h.calls.edit_url, [['url_old', 'https://old.example/edited']]);
    assert.equal(h.calls.push_global_history.length, 0);
    assert.equal(h.server.urls.find((u) => u.id === 'url_old').url, 'https://old.example/edited');
    assert.equal(h.server.urls.find((u) => u.id === 'url_old').tab_id, 'T1', 'tab link kept');
    assert.ok(h.logs.some(([m]) => m === 'URL updated: https://old.example/edited'));
  });

  test('regression replay: the old push-back WOULD have dropped the row (documents the mechanism)', () => {
    const h = harness();
    h.byId.urlInput.value = 'https://arena.example/new';
    h.A.addUrl();
    // What the pre-fix _onAdd did 100 ms later, with the client's stale list:
    h.sandbox.ArenaHistory.recordGlobal('urls', h.sandbox.App.state.urls);
    assert.equal(h.calls.push_global_history.length, 1);
    assert.ok(!h.server.urls.some((u) => u.id === 'url_new'), 'stale snapshot erased the new row');
  });
});

describe('static guard — url-list never records `urls` into the global history from the client', () => {
  test('no recordGlobal(\'urls\' …) in app/ui/web/js/panels/url-list/', () => {
    const dir = path.join(JS, 'panels/url-list');
    for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.js'))) {
      const src = fs.readFileSync(path.join(dir, f), 'utf-8')
        .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
      assert.ok(!/recordGlobal\(\s*['"]urls['"]/.test(src), `${f} pushes URL rows back to Python`);
      assert.ok(!/push_global_history\(\s*['"]urls['"]/.test(src), `${f} pushes URL rows back to Python`);
    }
  });
});
