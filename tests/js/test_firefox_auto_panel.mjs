/**
 * The 18th window `firefox_auto` — "Firefox auto with Extension" (I-63).
 *
 * Part 1: the mount — `winFirefoxAuto` is registered in every registry
 * (Python catalog, constants.js, store.js winElIds, _PANEL_INITS) and mounts
 * inside the grid, never an L-5 orphan. Part 2: the content — the config
 * fields (the pattern is the control element), Save/Run/Stop over the 4 slots
 * and the live `firefox_auto_updated` step stream ending in one named verdict.
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

const FA_IDS = ['faPattern', 'faUrl', 'faMacro', 'faTarget', 'faStorage', 'faHome', 'faBinary', 'faMode',
  'faTimeout', 'faPause', 'faSaveBtn', 'faRunBtn', 'faStopBtn', 'faState', 'faPaths',
  'faStatus', 'faSteps'];

function inside(node, ancestor) {
  for (let n = node; n; n = n.parent) if (n === ancestor) return true;
  return false;
}

describe('firefox_auto window (mount)', () => {
  test('index.html registers winFirefoxAuto with the config fields and controls', () => {
    assert.ok(html.includes('id="winFirefoxAuto" data-window="firefox_auto"'), 'panel present');
    assert.ok(html.includes('js/panels/firefox-auto.js'), 'index.html loads the panel script');
    const start = html.indexOf('id="winFirefoxAuto"');
    const end = html.indexOf('<div class="panel', start + 1);
    const block = html.slice(start, end > 0 ? end : undefined);
    for (const id of FA_IDS) assert.ok(block.includes(`id="${id}"`), `${id} inside winFirefoxAuto`);
    assert.match(block, /Firefox auto with Extension/);
    assert.match(block, /faPattern/);   // the user-set pattern is the control element
  });

  test('the grid mounts winFirefoxAuto and does not destroy it on render()', () => {
    assert.ok(ALL_WINDOW_IDS.includes('firefox_auto'), 'harness registry has the 18th window');
    assert.equal(panelIdOf('firefox_auto'), 'winFirefoxAuto');
    const h = createSashGrid();
    const find = (n, id) => { if (n.id === id) return n; for (const c of n.children) { const r = find(c, id); if (r) return r; } return null; };
    h.SashGrid.render();
    const win = find(h.body, 'winFirefoxAuto');
    assert.ok(win, 'winFirefoxAuto exists after render');
    assert.ok(inside(win, h.gridEl), 'winFirefoxAuto is inside #sashGrid (not discarded by replaceChildren)');
  });

  test('_PANEL_INITS includes FirefoxAutoPanel and it publishes itself on window', () => {
    const inits = readJs('arena-app.js').match(/_PANEL_INITS\s*=\s*\[([\s\S]*?)\]/)[1];
    assert.match(inits, /'FirefoxAutoPanel'/);
    const sandbox = { console: { warn() {}, log() {}, error() {} }, JSON, Object, Array, Set, WeakMap, Map, Number, String, Math, Date, parseInt, isNaN,
      setInterval: () => 1, setTimeout: () => 1, document: { getElementById: () => null, readyState: 'complete', addEventListener() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'core/boot.js' });
    vm.runInContext(readJs('panels/firefox-auto.js'), sandbox, { filename: 'panels/firefox-auto.js' });
    assert.ok(vm.runInContext("Boot.panel('FirefoxAutoPanel')", sandbox), 'published on window');
    vm.runInContext('FirefoxAutoPanel.init()', sandbox); // no DOM, no bridge: must not throw
  });
});

/* ── part 2: the content ─────────────────────────────────────────────────── */
const CFG = { pattern: 'Arena', url: 'https://arena.ai', target: "xpath=//a[span[text()='New Chat']]",
  macro: 'Python_XClick_Demo', storage: 'xfile', home: '', binary: '', timeout_sec: 90, pause_ms: 3000, mode: 'find' };
const PATHS = { home: '/home/u/Desktop/uivision',
  macro_file: '/home/u/Desktop/uivision/macros/Python_XClick_Demo.json',
  autorun_file: '/cfg/uivision/ui.vision.html', log_dir: '/cfg/uivision/logs' };

function bootFaPanel() {
  const byId = {};
  for (const id of FA_IDS) byId[id] = new El(id.endsWith('Btn') ? 'button' : 'div');
  const calls = [];
  const listeners = {};
  const responses = {
    get_firefox_auto_config: JSON.stringify({ ok: true, config: CFG, paths: PATHS, running: false }),
    save_firefox_auto_config: JSON.stringify({ ok: true, config: CFG, paths: PATHS }),
    run_firefox_auto_test: JSON.stringify({ ok: true, state: 'running' }),
    stop_firefox_auto_test: JSON.stringify({ ok: true, state: 'stopping' }),
  };
  const bridge = new Proxy({}, { get(_t, k) {
    if (typeof k !== 'string') return undefined;
    const fn = (...a) => { calls.push({ name: k, args: a }); const cb = a.find((x) => typeof x === 'function'); if (cb) cb(responses[k] || '{}'); };
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
  vm.runInContext(readJs('panels/firefox-auto.js'), sandbox, { filename: 'panels/firefox-auto.js' });
  vm.runInContext('FirefoxAutoPanel.init()', sandbox);
  const push = (payload) => { for (const h of listeners.firefox_auto_updated || []) h(JSON.stringify(payload)); };
  const call = (name) => calls.find((c) => c.name === name);
  const click = (id) => byId[id].dispatch('click');
  return { byId, calls, responses, push, call, click, sandbox,
    text: (id) => byId[id].textContent };
}

describe('firefox_auto window (content)', () => {
  test('the first paint pulls the config and fills every field, the paths and idle state', () => {
    const h = bootFaPanel();
    assert.ok(h.call('get_firefox_auto_config'), 'initial pull on bridge-ready');
    assert.equal(h.byId.faPattern.value, 'Arena');
    assert.equal(h.byId.faTarget.value, CFG.target);
    assert.equal(h.byId.faTimeout.value, 90);
    assert.equal(h.byId.faPause.value, 3000);
    assert.match(h.text('faPaths'), /Ui\.Vision home: \/home\/u\/Desktop\/uivision/);
    assert.match(h.text('faPaths'), /macro file: .*Python_XClick_Demo\.json/);
    assert.equal(h.text('faState'), 'idle');
    assert.ok(!h.byId.faRunBtn.disabled);
  });

  test('Save sends exactly the field table (numbers as numbers) and shows the verdict', () => {
    const h = bootFaPanel();
    h.byId.faPattern.value = 'My Pattern';
    h.click('faSaveBtn');
    const save = h.call('save_firefox_auto_config');
    assert.ok(save, 'save slot called');
    const payload = JSON.parse(save.args[0]);
    assert.deepEqual(Object.keys(payload).sort(), Object.keys(CFG).sort());
    assert.equal(payload.pattern, 'My Pattern');
    assert.equal(payload.timeout_sec, 90);
    assert.equal(typeof payload.timeout_sec, 'number');
    assert.equal(h.text('faStatus'), '✅ config saved');
    assert.equal(h.byId.faStatus.style.color, '#4caf50');
  });

  test('a refused save names the error and stays visible', () => {
    const h = bootFaPanel();
    h.responses.save_firefox_auto_config = JSON.stringify({ ok: false, error: 'macro name not allowed' });
    h.click('faSaveBtn');
    assert.match(h.text('faStatus'), /⚠ save refused: macro name not allowed/);
    assert.equal(h.byId.faStatus.style.color, '#e6a23c');
  });

  test('Run clears the steps, disables itself and streams every phase', () => {
    const h = bootFaPanel();
    h.push({ kind: 'step', step: 'provision', message: 'macro written: /h/macros/M.json' });
    h.click('faRunBtn');
    assert.ok(h.call('run_firefox_auto_test'), 'run slot called');
    assert.equal(h.text('faSteps'), '', 'old steps cleared on a new run');
    assert.equal(h.text('faState'), 'running…');
    assert.equal(h.byId.faRunBtn.disabled, true);
    h.push({ kind: 'step', step: 'launch', message: 'starting Firefox', level: 'info' });
    assert.match(h.text('faSteps'), /· launch: starting Firefox/);
    assert.equal(h.text('faStatus'), 'launch — starting Firefox');
    h.push({ kind: 'step', step: 'foreground', message: 'no Firefox window matches', level: 'warn' });
    h.push({ kind: 'step', step: 'launch', message: 'Firefox not found', level: 'error' });
    assert.match(h.text('faSteps'), /⚠ foreground: no Firefox window matches/);
    assert.match(h.text('faSteps'), /✗ launch: Firefox not found/);
  });

  test('the ok result re-enables Run and appends the macro log tail', () => {
    const h = bootFaPanel();
    h.click('faRunBtn');
    h.push({ kind: 'result', result: 'ok', message: 'macro completed', lines: ['echo: done — XClick fired (native OS input)'] });
    assert.equal(h.text('faState'), 'idle');
    assert.ok(!h.byId.faRunBtn.disabled);
    assert.match(h.text('faStatus'), /✅ ok: macro completed/);
    assert.match(h.text('faSteps'), /\| echo: done — XClick fired/);
  });

  test('every verdict kind shows its own icon — never one invented "failed"', () => {
    for (const [result, icon] of [['timeout', '⌛'], ['stopped', '⏹'], ['blocked', '❌'], ['error', '❌']]) {
      const h = bootFaPanel();
      h.click('faRunBtn');
      h.push({ kind: 'result', result, message: 'because' });
      assert.match(h.text('faStatus'), new RegExp(`${icon} ${result}: because`), result);
      assert.equal(h.text('faState'), 'idle', `${result} ends the run`);
    }
  });

  test('Stop asks the backend and says what will happen', () => {
    const h = bootFaPanel();
    h.click('faStopBtn');
    assert.ok(h.call('stop_firefox_auto_test'), 'stop slot called');
    assert.match(h.text('faStatus'), /⏹ stop requested — the run ends on its next check/);
  });

  test('a pushed running/saved payload repaints without any bridge call', () => {
    const h = bootFaPanel();
    const before = h.calls.length;
    h.push({ kind: 'running' });
    assert.equal(h.text('faState'), 'running…');
    h.push({ kind: 'saved', config: { pattern: 'Z' }, paths: { home: '/h' } });
    assert.equal(h.byId.faPattern.value, 'Z');
    assert.match(h.text('faPaths'), /Ui\.Vision home: \/h/);
    assert.equal(h.calls.length, before, 'pushed payloads never call the bridge');
  });

  test('the step stream is capped at the last 60 lines', () => {
    const h = bootFaPanel();
    for (let n = 1; n <= 65; n++) h.push({ kind: 'step', step: 's', message: `m${n}` });
    const lines = h.text('faSteps').split('\n');
    assert.equal(lines.length, 60);
    assert.match(lines[59], /m65/);
    assert.match(lines[0], /m6/);
  });
});
