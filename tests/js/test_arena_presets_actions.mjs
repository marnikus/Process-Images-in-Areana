/**
 * arena-presets/actions.js + render.js — static ids, bound once, no injected duplicates
 * (2026-10-02 bugfix: colliding ids left the Arena Presets window's buttons dead).
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
const HTML = fs.readFileSync(path.resolve(__dirname, '../../app/ui/web/index.html'), 'utf-8');

const IDS = ['promptPresetName', 'promptPresetSaveBtn', 'promptPresetSelect', 'promptPresetLoadBtn', 'promptPresetDeleteBtn',
  'arenaPresetNameInput', 'arenaPresetSaveBtn', 'arenaPresetExportBtn', 'arenaPresetImportBtn', 'arenaPresetFileInput',
  'arenaPresetsList', 'arenaPromptPresetNameInput', 'arenaPromptPresetSaveBtn', 'promptPresetsList',
  'presetNameInput', 'settingsExportBtn', 'settingsImportBtn', 'promptTextarea', 'arenaPresetsCount'];

function makeEl(id) {
  const el = new El(id.endsWith('Btn') ? 'button' : (id === 'promptPresetSelect' ? 'select' : (id.endsWith('Input') || id.endsWith('Name') ? 'input' : 'div')));
  el.id = id;
  el.value = '';
  return el;
}

function load(bridge) {
  const byId = {};
  IDS.forEach((id) => { byId[id] = makeEl(id); });
  const settingsBar = new El('div');                     // presetNameInput/settingsExportBtn share a parent bar
  settingsBar.appendChild(byId.presetNameInput);
  settingsBar.appendChild(byId.settingsExportBtn);
  const created = [];
  const logs = [];
  const sandbox = { console: { warn() {}, log() {}, error() {} }, JSON, Set, WeakMap, Map, Object, Array, String, Blob: class {}, URL: { createObjectURL: () => 'blob:', revokeObjectURL() {} },
    document: {
      getElementById: (id) => byId[id] || created.find((e) => e.id === id) || null,   // created + inserted elements are findable, like a real DOM
      createElement: (tag) => { const e = new El(tag); created.push(e); return e; },
      readyState: 'complete', addEventListener() {},
    },
    LogConsole: { log: (m, l) => logs.push([m, l]) },
  };
  sandbox.window = sandbox;
  sandbox.App = { bridge, state: { urls: [] } };
  vm.createContext(sandbox);
  for (const f of ['core/boot.js', 'panels/arena-presets/store.js', 'panels/arena-presets/render.js', 'panels/arena-presets/actions.js']) {
    vm.runInContext(fs.readFileSync(path.join(JS, f), 'utf-8'), sandbox, { filename: f });
  }
  return { A: sandbox.window.ArenaPresetsActions, R: sandbox.window.ArenaPresetsRender, byId, created, logs, sandbox };
}

describe('index.html preset markup', () => {
  test('every preset id is static and unique (no duplicate ids)', () => {
    for (const id of IDS) {
      const n = (HTML.match(new RegExp(`id="${id}"`, 'g')) || []).length;
      assert.equal(n, 1, `id="${id}" occurs ${n} times`);
    }
    assert.ok(/id="promptPresetBar"/.test(HTML));
  });
});

describe('ArenaPresetsActions binding', () => {
  test('binds static controls once; no bar is injected into the DOM', () => {
    const calls = [];
    const bridge = {
      save_prompt_preset: (n, t, cb) => { calls.push(['sp', n, t]); cb(JSON.stringify({ ok: true })); },
      list_prompt_presets: (cb) => { calls.push(['lp']); cb(JSON.stringify([{ name: 'p1' }])); },
      save_arena_preset: (n, cb) => { calls.push(['sa', n]); cb(JSON.stringify({ ok: true })); },
    };
    const { A, byId, created } = load(bridge);
    A.bindSettingsPresets(); A.bindPromptPresets(); A.bindArenaPresets();
    A.bindSettingsPresets(); A.bindPromptPresets(); A.bindArenaPresets();   // second init → no double handlers
    assert.deepEqual(created.map((e) => e.id), ['settingsSavePresetBtn']);  // only the settings save button is created
    byId.promptTextarea.value = 'hello';
    byId.promptPresetName.value = ' p1 ';
    byId.promptPresetSaveBtn.dispatch('click', {});
    assert.deepEqual(calls, [['sp', 'p1', 'hello'], ['lp']]);
    assert.equal(byId.promptPresetName.value, '');
    byId.arenaPromptPresetNameInput.value = 'p2';
    byId.arenaPromptPresetSaveBtn.dispatch('click', {});
    assert.deepEqual(calls[2], ['sp', 'p2', 'hello']);
    byId.arenaPresetNameInput.value = 'A1';
    byId.arenaPresetSaveBtn.dispatch('click', {});
    assert.deepEqual(calls.at(-1), ['sa', 'A1']);
    byId.arenaPresetNameInput.value = 'A2';
    byId.arenaPresetNameInput.dispatch('keydown', { key: 'Enter' });
    assert.deepEqual(calls.at(-1), ['sa', 'A2']);
  });

  test('guards: empty name / empty prompt never hit the bridge; errors are logged', () => {
    const calls = [];
    const bridge = {
      save_prompt_preset: (n, t, cb) => { calls.push(n); cb(JSON.stringify({ ok: false, error: 'disk' })); },
    };
    const { A, byId, logs } = load(bridge);
    A.bindPromptPresets();
    byId.promptPresetSaveBtn.dispatch('click', {});          // no name
    byId.promptPresetName.value = 'x';
    byId.promptPresetSaveBtn.dispatch('click', {});          // no prompt text
    assert.deepEqual(calls, []);
    byId.promptTextarea.value = 'body';
    byId.promptPresetSaveBtn.dispatch('click', {});
    assert.deepEqual(calls, ['x']);
    assert.ok(logs.some(([m, l]) => m.includes('disk') && l === 'error'));
  });

  test('load/delete act on the <select> value and re-render the list', () => {
    const calls = [];
    const bridge = {
      load_prompt_preset: (n, cb) => { calls.push(['load', n]); cb(JSON.stringify({ ok: true, template: 'T-' + n })); },
      delete_prompt_preset: (n, cb) => { calls.push(['del', n]); cb(JSON.stringify({ ok: true })); },
      list_prompt_presets: (cb) => { calls.push(['list']); cb(JSON.stringify(['a', 'b'])); },
    };
    const { A, R, byId } = load(bridge);
    A.bindPromptPresets();
    byId.promptPresetLoadBtn.dispatch('click', {});          // nothing selected → noop
    assert.deepEqual(calls, []);
    byId.promptPresetSelect.value = 'a';
    byId.promptPresetLoadBtn.dispatch('click', {});
    assert.equal(byId.promptTextarea.value, 'T-a');
    byId.promptPresetDeleteBtn.dispatch('click', {});
    assert.deepEqual(calls, [['load', 'a'], ['del', 'a'], ['list']]);
    R.renderArenaPresets(JSON.stringify([{ name: 'one' }]));
    assert.equal(byId.arenaPresetsCount.textContent, '1 preset');
    assert.equal(byId.arenaPresetsList.children.length, 1);
    R.renderArenaPresets('[]');
    assert.match(byId.arenaPresetsList.textContent, /No arena presets yet/);
  });
});
