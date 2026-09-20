/**
 * url-list/interval.js — the "🔁 every … ms" control in the URL window (S6, D-12R).
 *
 * It is a NEW module: the six frozen url-list files must not grow (RULE 18 +
 * the JS ratchet). The control reads its value from the pushed
 * `progress_updated.live.url_interval_ms` (no new slot — D-20), clamps
 * 500…60000 like Python's `debug_view.clamp_interval_ms`, saves through the
 * existing `save_settings` slot via `Boot.needBridge`, and binds once.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const JS = path.join(WEB, 'js');
const read = (rel) => fs.readFileSync(path.join(JS, rel), 'utf-8');
const lineCount = (rel) => read(rel).split('\n').filter((_l, i, a) => i < a.length - 1 || _l !== '').length;  // wc -l

function harness({ withBridge = true } = {}) {
  const byId = { urlIntervalMs: new El('input'), urlIntervalSaveBtn: new El('button') };
  const saved = [];
  const listeners = [];
  const bridge = {
    save_settings(json, cb) { saved.push(JSON.parse(json)); if (cb) cb(JSON.stringify({ ok: true })); },
    progress_updated: { connect(fn) { listeners.push(fn); } },
  };
  const sandbox = { console, JSON, Set, WeakMap, Map, Math, Object, Array, String, Number, parseInt,
    document: { getElementById: (id) => byId[id] || null, readyState: 'complete', addEventListener() {} },
    LogConsole: { log() {} } };
  sandbox.window = sandbox;
  sandbox.App = { bridge: withBridge ? bridge : null };
  vm.createContext(sandbox);
  vm.runInContext(read('core/boot.js'), sandbox, { filename: 'boot.js' });
  vm.runInContext(read('panels/url-list/interval.js'), sandbox, { filename: 'interval.js' });
  return { U: sandbox.window.UrlInterval, byId, saved, listeners, bridge };
}

describe('UrlInterval (url-list/interval.js)', () => {
  test('exports bounds that mirror Python and clamps the same way', () => {
    const { U } = harness();
    assert.deepEqual([U.MIN, U.MAX, U.DEFAULT], [500, 60000, 5000]);
    assert.deepEqual([1, 60001, 'abc', undefined, 2500, '1200'].map((v) => U.clamp(v)), [500, 60000, 5000, 5000, 2500, 1200]);
  });

  test('loads its value from the pushed progress payload (no slot call)', () => {
    const { U, byId, listeners } = harness();
    U.init();
    assert.equal(listeners.length, 1, 'self-connects progress_updated once');
    listeners[0](JSON.stringify({ processed: 0, live: { url_interval_ms: 1200, last_pass_at: 0, passes: 0 } }));
    assert.equal(byId.urlIntervalMs.value, '1200');
    listeners[0](JSON.stringify({ processed: 0 }));  // payload without `live` leaves the field alone
    assert.equal(byId.urlIntervalMs.value, '1200');
  });

  test('a typed value is not clobbered by a later push while the field has focus', () => {
    const { U, byId, listeners } = harness();
    U.init();
    byId.urlIntervalMs.value = '777';
    byId.urlIntervalMs.dispatch('focus', {});
    listeners[0](JSON.stringify({ live: { url_interval_ms: 5000 } }));
    assert.equal(byId.urlIntervalMs.value, '777');
    byId.urlIntervalMs.dispatch('blur', {});
    listeners[0](JSON.stringify({ live: { url_interval_ms: 5000 } }));
    assert.equal(byId.urlIntervalMs.value, '5000');
  });

  test('Save clamps and calls save_settings with only the interval key', () => {
    const { U, byId, saved } = harness();
    U.init();
    byId.urlIntervalMs.value = '99999';
    byId.urlIntervalSaveBtn.dispatch('click', {});
    assert.deepEqual(saved, [{ url_reconcile_interval_ms: 60000 }]);
    assert.equal(byId.urlIntervalMs.value, '60000', 'the field shows what was actually saved');
  });

  test('binds once and survives a missing bridge', () => {
    const { U, byId, saved } = harness({ withBridge: false });
    U.init(); U.init();
    assert.equal((byId.urlIntervalSaveBtn._listeners.click || []).length, 1);
    byId.urlIntervalSaveBtn.dispatch('click', {});
    assert.deepEqual(saved, []);
  });

  test('index.html mounts the control inside the cooldown bar and loads the module before url-list.js', () => {
    const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
    const bar = html.slice(html.indexOf('id="urlCooldownBar"'), html.indexOf('id="urlTableWrap"') > 0 ? html.indexOf('id="urlTableWrap"') : undefined);
    assert.match(bar, /id="urlIntervalMs"/);
    assert.match(bar, /id="urlIntervalSaveBtn"/);
    assert.ok(html.indexOf('js/panels/url-list/interval.js') < html.indexOf('js/panels/url-list.js"'));
    const inits = read('arena-app.js').match(/_PANEL_INITS\s*=\s*\[([\s\S]*?)\]/)[1];
    assert.match(inits, /'UrlInterval'/);
  });

  test('the six frozen url-list files did not grow (the control is a new module)', () => {
    const frozen = { 'panels/url-list/store.js': 38, 'panels/url-list/render.js': 73, 'panels/url-list/matching.js': 105,
      'panels/url-list/cooldown.js': 48, 'panels/url-list/actions.js': 166, 'panels/url-list/listeners.js': 62,
      'panels/url-list.js': 137 };
    for (const [rel, max] of Object.entries(frozen)) {
      const lines = lineCount(rel);
      assert.ok(lines <= max, `${rel}: ${lines} lines > frozen ${max}`);
    }
    assert.ok(lineCount('panels/url-list/interval.js') <= 80, 'interval.js stays small');
  });
});
