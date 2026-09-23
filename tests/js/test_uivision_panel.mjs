/**
 * The 18th window `uivision` — "Firefox auto with Extension".
 *
 * Part 1: the mount — registered in every registry (Python catalog,
 * `constants.js`, `store.js` winElIds, `_PANEL_INITS`) and mounted inside the
 * grid, never an L-5 orphan. Part 2: the behaviour — the form round-trips
 * through the bridge, and the run's verdict arrives on the asynchronous
 * `uivision_result` signal rather than as the slot's return value.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';
import { createSashGrid, ALL_WINDOW_IDS, panelIdOf } from './sash_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const readJs = (rel) => fs.readFileSync(path.join(WEB, 'js', rel), 'utf-8');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');

const UIV_FILES = ['panels/uivision/form.js', 'panels/uivision/render.js', 'panels/uivision.js'];
const FIELD_IDS = ['uivHtmlPath', 'uivMacro', 'uivLogPath', 'uivFirefoxPath',
  'uivTabPattern', 'uivTarget', 'uivTimeout'];
const ALL_IDS = FIELD_IDS.concat(['uivSaveBtn', 'uivRunBtn', 'uivMacroBtn', 'uivStatus',
  'uivMatch', 'uivOutput']);

function inside(node, ancestor) {
  for (let n = node; n; n = n.parent) if (n === ancestor) return true;
  return false;
}

describe('uivision window (mount)', () => {
  test('index.html registers winUivision with the config form and controls', () => {
    assert.ok(html.includes('id="winUivision" data-window="uivision"'), 'panel present');
    assert.ok(html.includes('css/uivision.css'), 'stylesheet loaded');
    for (const f of UIV_FILES) assert.ok(html.includes(`js/${f}`), `index.html loads ${f}`);
    const start = html.indexOf('id="winUivision"');
    const end = html.indexOf('<div class="panel', start + 1);
    const block = html.slice(start, end > 0 ? end : undefined);
    for (const id of ALL_IDS) assert.ok(block.includes(`id="${id}"`), `${id} inside winUivision`);
    assert.ok(block.includes('Firefox auto with Extension'), 'window title');
  });

  test('the tab pattern is a real control the user can edit', () => {
    // the whole point: the URL pattern is configurable, not hard-coded
    const start = html.indexOf('id="uivTabPattern"');
    assert.ok(start > 0, 'pattern field exists');
    const field = html.slice(start - 200, start + 200);
    assert.match(field, /<input/, 'it is an input element');
  });

  test('the grid mounts winUivision and does not destroy it on render()', () => {
    assert.ok(ALL_WINDOW_IDS.includes('uivision'), 'harness registry has the 18th window');
    assert.equal(panelIdOf('uivision'), 'winUivision');
    const h = createSashGrid();
    const find = (n, id) => { if (n.id === id) return n; for (const c of n.children) { const r = find(c, id); if (r) return r; } return null; };
    h.SashGrid.render();
    const win = find(h.body, 'winUivision');
    assert.ok(win, 'winUivision exists after render');
    assert.ok(inside(win, h.gridEl), 'winUivision is inside #sashGrid');
  });

  test('_PANEL_INITS includes the panel and the modules publish themselves', () => {
    const inits = readJs('arena-app.js').match(/_PANEL_INITS\s*=\s*\[([\s\S]*?)\]/)[1];
    assert.match(inits, /'UiVisionPanel'/);
    const sandbox = { console: { warn() {}, log() {}, error() {} }, JSON, Object, Array, Set, WeakMap, Map, Number, String, Math, Date, parseInt, parseFloat, isNaN,
      setInterval: () => 1, setTimeout: () => 1, document: { getElementById: () => null, readyState: 'complete', addEventListener() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'core/boot.js' });
    for (const f of UIV_FILES) vm.runInContext(readJs(f), sandbox, { filename: f });
    for (const name of ['UiVisionPanel', 'UiVisionForm', 'UiVisionRender']) {
      assert.ok(vm.runInContext(`Boot.panel('${name}')`, sandbox), `${name} published`);
    }
    vm.runInContext('UiVisionPanel.init()', sandbox); // no DOM, no bridge: must not throw
  });
});

/* ── part 2: the behaviour ───────────────────────────────────────────────── */

function bootPanel(replies = {}) {
  const byId = {};
  for (const id of ALL_IDS) byId[id] = new El(id.endsWith('Btn') ? 'button' : (FIELD_IDS.includes(id) ? 'input' : 'div'));
  const calls = [];
  const listeners = {};
  const bridge = new Proxy({}, { get(_t, k) {
    if (typeof k !== 'string') return undefined;
    const fn = (...a) => {
      calls.push([k, a.filter((x) => typeof x !== 'function')]);
      const cb = a.find((x) => typeof x === 'function');
      if (cb) cb(replies[k] !== undefined ? replies[k] : '{}');
    };
    fn.connect = (h) => { (listeners[k] ||= []).push(h); };
    return fn;
  } });
  const sandbox = {
    console, JSON, Object, Array, Math, Number, String, Set, Map, WeakMap, parseInt, parseFloat, isNaN,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    document: { getElementById: (id) => byId[id] || null, querySelector: () => null, querySelectorAll: () => [],
      readyState: 'complete', addEventListener() {}, createElement: (t) => new El(t) },
    App: { bridge },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'core/boot.js' });
  for (const f of UIV_FILES) vm.runInContext(readJs(f), sandbox, { filename: f });
  vm.runInContext('UiVisionPanel.init()', sandbox);
  const push = (signal, payload) => { for (const h of listeners[signal] || []) h(typeof payload === 'string' ? payload : JSON.stringify(payload)); };
  const text = (id) => byId[id].textContent || byId[id].innerHTML || '';
  return { byId, calls, push, sandbox, text };
}

const SETTINGS = {
  uivision_html_path: '/rpa/ui.vision.html',
  uivision_macro: 'Python_XClick_Demo',
  uivision_log_path: '/rpa/log.txt',
  uivision_firefox_path: 'firefox',
  uivision_tab_pattern: 'arena.ai',
  uivision_target: "xpath=//a[span[text()='New Chat']]",
  uivision_timeout_s: 60,
  matched_url: 'https://arena.ai/image/direct',
  missing: [],
  ready: true,
};

describe('uivision window (behaviour)', () => {
  test('the saved settings fill every field on first paint', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS) });
    assert.equal(h.byId.uivMacro.value, 'Python_XClick_Demo');
    assert.equal(h.byId.uivTabPattern.value, 'arena.ai');
    assert.equal(h.byId.uivTarget.value, "xpath=//a[span[text()='New Chat']]");
  });

  test('the matched tab is shown so the operator knows what will open', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS) });
    assert.match(h.text('uivMatch'), /arena\.ai\/image\/direct/);
  });

  test('a failed match explains what was compared, not just "no match"', () => {
    // I-66: the bare "no tab matches the pattern" gave the operator nothing to act on
    const h = bootPanel({ get_uivision_settings: JSON.stringify({
      ...SETTINGS, matched_url: '',
      match_note: "pattern 'arena.ai' matched none of 2 URL(s): https://a.test/, https://b.test/" }) });
    assert.match(h.text('uivMatch'), /matched none of 2 URL/);
    assert.match(h.text('uivMatch'), /a\.test/);
  });

  test('a miss without a note still says something sensible', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify({ ...SETTINGS, matched_url: '' }) });
    assert.match(h.text('uivMatch'), /no tab matches/);
  });

  test('an incomplete config names what is still missing', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify({ missing: ['log file path'], ready: false }) });
    assert.match(h.text('uivMatch'), /log file path/);
  });

  test('saving sends every field back to Python', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS) });
    h.byId.uivTabPattern.value = 'example.test';
    h.byId.uivSaveBtn.dispatch('click', { target: null });
    const save = h.calls.find(([k]) => k === 'save_uivision_settings');
    assert.ok(save, 'save slot called');
    assert.equal(JSON.parse(save[1][0]).uivision_tab_pattern, 'example.test');
  });

  test('the timeout is sent as a number, not a string', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS) });
    h.byId.uivTimeout.value = '30';
    h.byId.uivSaveBtn.dispatch('click', { target: null });
    const save = h.calls.find(([k]) => k === 'save_uivision_settings');
    assert.equal(JSON.parse(save[1][0]).uivision_timeout_s, 30);
  });

  test('running shows progress immediately and asks Python to start', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS),
      run_uivision_test: JSON.stringify({ ok: true, state: 'running' }) });
    h.byId.uivRunBtn.dispatch('click', { target: null });
    assert.ok(h.calls.some(([k]) => k === 'run_uivision_test'), 'run slot called');
    assert.match(h.text('uivStatus'), /running/);
  });

  test('the verdict arrives asynchronously on uivision_result', () => {
    // the slot only says "started"; success is only known once the log is read
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS),
      run_uivision_test: JSON.stringify({ ok: true, state: 'running' }) });
    h.byId.uivRunBtn.dispatch('click', { target: null });
    h.push('uivision_result', { ok: true, state: 'ok', message: 'done', lines: ['[status] Macro completed'] });
    assert.match(h.text('uivStatus'), /done/);
    assert.match(h.text('uivOutput'), /Macro completed/);
  });

  test('a failed run is shown with its reason', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS),
      run_uivision_test: JSON.stringify({ ok: true, state: 'running' }) });
    h.byId.uivRunBtn.dispatch('click', { target: null });
    h.push('uivision_result', { ok: false, state: 'failed', message: 'no XModules', lines: [] });
    assert.match(h.text('uivStatus'), /failed/);
    assert.match(h.text('uivOutput'), /no XModules/);
  });

  test('a refused launch is reported without waiting for a verdict', () => {
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS),
      run_uivision_test: JSON.stringify({ ok: false, state: 'failed', message: 'log file path' }) });
    h.byId.uivRunBtn.dispatch('click', { target: null });
    assert.match(h.text('uivOutput'), /log file path/);
  });

  test('the macro source can be shown for importing into Ui.Vision', () => {
    const macro = JSON.stringify({ Name: 'Python_XClick_Demo', Commands: [{ Command: 'XClick' }] });
    const h = bootPanel({ get_uivision_settings: JSON.stringify(SETTINGS),
      get_uivision_macro: JSON.stringify({ ok: true, macro }) });
    h.byId.uivMacroBtn.dispatch('click', { target: null });
    assert.match(h.text('uivOutput'), /XClick/);
  });

  test('a malformed reply never throws', () => {
    const h = bootPanel({ get_uivision_settings: 'not json' });
    h.byId.uivRunBtn.dispatch('click', { target: null });
    h.push('uivision_result', 'also not json');
    assert.ok(true);
  });
});
