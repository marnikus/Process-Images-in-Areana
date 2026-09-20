/**
 * url-list/listeners.js — the URL window's DOM listeners are bound once and
 * dispatch to the facade (2026-10-02 bugfix: double bindings / dead Add).
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

function load(withBoot = true) {
  const byId = {};
  const sandbox = { console, JSON, Set, WeakMap, Map, Object, Array, String,
    document: { getElementById: (id) => byId[id] || null, readyState: 'complete', addEventListener() {} } };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  if (withBoot) vm.runInContext(fs.readFileSync(path.join(JS, 'core/boot.js'), 'utf-8'), sandbox, { filename: 'boot.js' });
  vm.runInContext(fs.readFileSync(path.join(JS, 'panels/url-list/listeners.js'), 'utf-8'), sandbox, { filename: 'listeners.js' });
  return { L: sandbox.window.UrlListListeners, byId };
}

function facadeSpy() {
  const calls = [];
  const rec = (name) => (...a) => calls.push([name, ...a]);
  return { calls, addUrl: rec('addUrl'), reparseTabs: rec('reparseTabs'), popupTabs: rec('popupTabs'),
           saveCooldownConfig: rec('saveCooldownConfig'), toggleUrl: rec('toggleUrl'), testUrl: rec('testUrl'),
           removeUrl: rec('removeUrl'), editUrl: rec('editUrl'), connectUrl: rec('connectUrl'),
           stopJob: rec('stopJob'), coolAction: rec('coolAction') };
}

function mountControls(byId) {
  ['urlAddBtn', 'urlReparseBtn', 'urlPopupBtn', 'urlCooldownSaveBtn'].forEach((id) => { byId[id] = new El('button'); });
  byId.urlInput = new El('input');
  byId.urlTableBody = new El('tbody');
}

describe('UrlListListeners.bind', () => {
  test('returns false without the mandatory elements', () => {
    const { L } = load();
    assert.equal(L.bind(facadeSpy()), false);
  });

  test('binds every control once — a second bind() adds no duplicate handlers', () => {
    const { L, byId } = load();
    mountControls(byId);
    const f = facadeSpy();
    assert.equal(L.bind(f), true);
    assert.equal(L.bind(f), true);                 // facade init() ran twice (state restore)
    byId.urlAddBtn.dispatch('click', {});
    byId.urlInput.dispatch('keydown', { key: 'Enter', preventDefault() {} });
    byId.urlInput.dispatch('keydown', { key: 'a', preventDefault() {} });
    byId.urlReparseBtn.dispatch('click', {});
    byId.urlPopupBtn.dispatch('click', {});
    byId.urlCooldownSaveBtn.dispatch('click', {});
    assert.deepEqual(f.calls.map((c) => c[0]), ['addUrl', 'addUrl', 'reparseTabs', 'popupTabs', 'saveCooldownConfig']);
  });

  test('without Boot it still binds (plain addEventListener fallback)', () => {
    const { L, byId } = load(false);
    mountControls(byId);
    const f = facadeSpy();
    assert.equal(L.bind(f), true);
    byId.urlAddBtn.dispatch('click', {});
    assert.deepEqual(f.calls, [['addUrl']]);
  });
});

describe('UrlListListeners.onTableClick', () => {
  const evOn = (el) => ({ target: el });

  test('checkbox toggle and every row button action route to the facade', () => {
    const { L } = load();
    const f = facadeSpy();
    const chk = new El('input'); chk.type = 'checkbox'; chk.dataset = { action: 'toggle', urlId: 'u1' };
    L.onTableClick(f, evOn(chk));
    for (const action of ['test', 'toggle', 'remove', 'edit', 'connect', 'stop-job']) {
      const btn = new El('button'); btn.dataset = { action, urlId: 'u2' };
      L.onTableClick(f, evOn(btn));
    }
    const cool = new El('button'); cool.dataset = { action: 'cool-reset', urlId: 'u3', tabId: 't' };
    L.onTableClick(f, evOn(cool));
    assert.deepEqual(f.calls, [
      ['toggleUrl', 'u1'], ['testUrl', 'u2'], ['toggleUrl', 'u2'], ['removeUrl', 'u2'], ['editUrl', 'u2'],
      ['connectUrl', 'u2'], ['stopJob', 'u2'], ['coolAction', 'cool-reset', cool],
    ]);
  });

  test('clicks outside buttons/checkboxes and buttons without ids are ignored', () => {
    const { L } = load();
    const f = facadeSpy();
    L.onTableClick(f, evOn(new El('span')));
    const btn = new El('button'); btn.dataset = { action: 'edit' };
    L.onTableClick(f, evOn(btn));
    const unknown = new El('button'); unknown.dataset = { action: 'explode', urlId: 'u9' };
    L.onTableClick(f, evOn(unknown));
    assert.deepEqual(f.calls, []);
  });
});
