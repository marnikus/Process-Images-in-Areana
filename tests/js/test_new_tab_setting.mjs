/**
 * I-79 "Start new chat as new tab" — the two controls in Settings → Job Cycle & Cooldown.
 * They ride the existing cooldown slots (no new slot): `NewTabSetting` (own module —
 * settings.js is size-frozen) loads them from get_cooldown_config's `new_tab`;
 * settings.js's `saveCooldown` sends `NewTabSetting.read()` with the cooldown payload.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const read = (rel) => fs.readFileSync(path.join(WEB, rel), 'utf-8');

function harness({ reply = null, withModule = true } = {}) {
  const byId = {};
  for (const id of ['cooldownEnabled', 'newTabEnabled']) byId[id] = Object.assign(new El('input'), { checked: false });
  for (const [id, v] of Object.entries({ cooldownMinMinutes: '5', cooldownCaptchaMinutes: '15', newTabUrl: '' })) {
    byId[id] = Object.assign(new El('input'), { value: v });
  }
  const sent = [];
  const sandbox = { console, JSON, Set, WeakMap, Map, Math, Object, Array, String, Number, parseInt, parseFloat, isNaN,
    navigator: {}, localStorage: { getItem() { return null; }, setItem() {} },
    document: { getElementById: (id) => byId[id] || null, readyState: 'complete', addEventListener() {},
      documentElement: { getAttribute() { return 'dark'; }, setAttribute() {} } },
    LogConsole: { log() {} } };
  sandbox.window = sandbox;
  sandbox.App = { bridge: {
    set_cooldown_config(json, cb) { sent.push(JSON.parse(json)); cb(JSON.stringify({ ok: true })); },
    get_cooldown_config(cb) { cb(JSON.stringify(reply || { ok: true, config: {} })); } } };
  vm.createContext(sandbox);
  vm.runInContext(read('js/core/boot.js'), sandbox, { filename: 'boot.js' });
  vm.runInContext(read('js/panels/settings.js'), sandbox, { filename: 'settings.js' });
  if (withModule) vm.runInContext(read('js/panels/new-tab-setting.js'), sandbox, { filename: 'new-tab-setting.js' });
  return { S: sandbox.window.SettingsPanel, N: sandbox.window.NewTabSetting, byId, sent };
}

test('init loads the saved setting into the checkbox and the URL', () => {
  const { N, byId } = harness({ reply: { ok: true, config: { enabled: true, min_seconds: 300 },
    new_tab: { enabled: true, url: 'https://arena.ai/image/direct?model_a=max' } } });
  N.init();
  assert.equal(byId.newTabEnabled.checked, true);
  assert.equal(byId.newTabUrl.value, 'https://arena.ai/image/direct?model_a=max');
});

test('an older reply without new_tab leaves the controls alone', () => {
  const { N, byId } = harness({ reply: { ok: true, config: { enabled: true } } });
  byId.newTabUrl.value = 'kept';
  N.init();
  assert.equal(byId.newTabUrl.value, 'kept');
});

test('Save sends the option with the cooldown payload', () => {
  const { S, byId, sent } = harness();
  byId.newTabEnabled.checked = true;
  byId.newTabUrl.value = '  https://arena.ai/image/direct?model_a=max ';
  S.saveCooldown();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].new_tab, true);
  assert.equal(sent[0].new_tab_url, 'https://arena.ai/image/direct?model_a=max');
  assert.equal(sent[0].min_seconds, 300);
});

test('the page has both controls inside the Job Cycle box', () => {
  const html = read('index.html');
  const box = html.slice(html.indexOf('Job Cycle & Cooldown'), html.indexOf('Max Retries'));
  assert.match(box, /id="newTabEnabled" type="checkbox"/);
  assert.match(box, /id="newTabUrl"/);
  assert.match(box, /Start new chat as new tab/);
});

test('Save without the module loaded still sends the cooldown payload, no option keys', () => {
  const { S, sent } = harness({ withModule: false });
  S.saveCooldown();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].min_seconds, 300);
  assert.equal('new_tab' in sent[0], false);
});

test('the module is booted with the other panels and loaded after settings.js', () => {
  const app = fs.readFileSync(path.join(WEB, 'js/arena-app.js'), 'utf-8');
  assert.match(app, /'NewTabSetting'/);
  const html = read('index.html');
  assert.ok(html.indexOf('js/panels/new-tab-setting.js') > html.indexOf('js/panels/settings.js'));
});
