/**
 * Settings → Job Cycle holds ONLY the I-79 "Start new chat as new tab" option (2026-09-28
 * owner: no duplicate pause / captcha controls — the URL List bar owns those).
 * `JobCycleSetting` loads the option from get_cooldown_config's `new_tab` and saves it
 * through set_cooldown_config with ONLY its two keys, so it never resets the bar's values.
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
const settingsBox = () => {
  const html = read('index.html');
  return html.slice(html.indexOf('<!-- Job Cycle'), html.indexOf('Max Retries'));
};

function harness({ reply = null, withModule = true } = {}) {
  const byId = { newTabEnabled: Object.assign(new El('input'), { checked: false }),
    newTabUrl: Object.assign(new El('input'), { value: '' }) };
  const sent = [];
  const logs = [];
  const sandbox = { console, JSON, Set, WeakMap, Map, Math, Object, Array, String, Number, parseInt, parseFloat, isNaN,
    navigator: {}, localStorage: { getItem() { return null; }, setItem() {} },
    document: { getElementById: (id) => byId[id] || null, readyState: 'complete', addEventListener() {},
      documentElement: { getAttribute() { return 'dark'; }, setAttribute() {} } },
    LogConsole: { log(m, l) { logs.push([m, l]); } } };
  sandbox.window = sandbox;
  sandbox.App = { bridge: {
    save_settings(json, cb) { if (cb) cb(JSON.stringify({ ok: true })); },
    set_cdp_config(json, cb) { if (cb) cb(JSON.stringify({ ok: true })); },
    set_cooldown_config(json, cb) { sent.push(JSON.parse(json)); cb(JSON.stringify({ ok: true, new_tab: JSON.parse(json) })); },
    get_cooldown_config(cb) { cb(JSON.stringify(reply || { ok: true, config: {} })); } } };
  vm.createContext(sandbox);
  vm.runInContext(read('js/core/boot.js'), sandbox, { filename: 'boot.js' });
  vm.runInContext(read('js/panels/settings.js'), sandbox, { filename: 'settings.js' });
  if (withModule) vm.runInContext(read('js/panels/job-cycle-setting.js'), sandbox, { filename: 'job-cycle-setting.js' });
  return { S: sandbox.window.SettingsPanel, N: sandbox.window.JobCycleSetting, byId, sent, logs };
}

test('Settings has no duplicate pause / captcha controls — the URL List bar owns them', () => {
  const box = settingsBox();
  for (const id of ['cooldownEnabled', 'cooldownMinMinutes', 'cooldownCaptchaMinutes']) {
    assert.equal(box.includes(`id="${id}"`), false, `${id} must live only in the URL List bar`);
  }
  const html = read('index.html');
  for (const id of ['urlCooldownMin', 'urlCooldownPenalty', 'urlCooldownSaveBtn']) {
    assert.ok(html.includes(`id="${id}"`), `URL List bar keeps ${id}`);
  }
  assert.match(box, /id="newTabEnabled" type="checkbox"/);
  assert.match(box, /id="newTabUrl"/);
  assert.match(box, /URL List/);                     // the pointer to where the pause is set
});

test('init loads the saved option into the checkbox and the URL', () => {
  const { N, byId } = harness({ reply: { ok: true, config: { enabled: true },
    new_tab: { enabled: true, url: 'https://arena.ai/image/direct?model_a=max' } } });
  N.init();
  assert.equal(byId.newTabEnabled.checked, true);
  assert.equal(byId.newTabUrl.value, 'https://arena.ai/image/direct?model_a=max');
});

test('a reply without new_tab leaves the controls alone', () => {
  const { N, byId } = harness({ reply: { ok: true, config: { enabled: true } } });
  byId.newTabUrl.value = 'kept';
  N.init();
  assert.equal(byId.newTabUrl.value, 'kept');
});

test('Settings Save sends ONLY the option — never pause / captcha / limit values', () => {
  const { S, byId, sent } = harness();
  byId.newTabEnabled.checked = true;
  byId.newTabUrl.value = '  https://arena.ai/image/direct?model_a=max ';
  S.save();
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { new_tab: true, new_tab_url: 'https://arena.ai/image/direct?model_a=max' });
});

test('Settings Save without the module loaded sends no cooldown payload at all', () => {
  const { S, sent } = harness({ withModule: false });
  S.save();
  assert.equal(sent.length, 0);
});

test('the module is booted with the panels, loaded after settings.js, reloaded on restore', () => {
  const app = read('js/arena-app.js');
  assert.match(app, /'JobCycleSetting'/);
  const html = read('index.html');
  assert.ok(html.indexOf('js/panels/job-cycle-setting.js') > html.indexOf('js/panels/settings.js'));
  const ws = read('js/panels/workspace.js');
  assert.match(ws, /\['UrlList', 'loadCooldownConfig'\]/);
  assert.match(ws, /\['JobCycleSetting', 'load'\]/);
  assert.equal(/\['SettingsPanel', 'loadCooldownConfig'\]/.test(ws), false);
});
