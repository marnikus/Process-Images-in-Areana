/**
 * Settings → Job Cycle (2026-09-28 owner spec "DUPLICATE COOLDOWN CONTROLS"): no pause /
 * captcha inputs — the URL List bar is their only editing home — but "Enable minimum pause
 * between jobs" stays (kept until the owner approves removing it). It is a VIEW of the one
 * key `cooldown_enabled` (same key as the bar's "on"): `JobCycleSetting` loads it with the
 * new-tab option from get_cooldown_config and saves ONLY {enabled, new_tab, new_tab_url}, so
 * the bar's values are never reset; after any save / preset load both views reload.
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
    cooldownEnabled: Object.assign(new El('input'), { checked: true }),
    newTabUrl: Object.assign(new El('input'), { value: '' }) };
  const sent = [];
  const logs = [];
  const sandbox = { console, JSON, Set, WeakMap, Map, Math, Object, Array, String, Number, parseInt, parseFloat, isNaN,
    navigator: {}, localStorage: { getItem() { return null; }, setItem() {} },
    document: { getElementById: (id) => byId[id] || null, readyState: 'complete', addEventListener() {},
      documentElement: { getAttribute() { return 'dark'; }, setAttribute() {} } },
    LogConsole: { log(m, l) { logs.push([m, l]); } } };
  const reloads = [];
  sandbox.UrlList = { loadCooldownConfig() { reloads.push('UrlList'); } };
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
  return { S: sandbox.window.SettingsPanel, N: sandbox.window.JobCycleSetting, byId, sent, logs, reloads, sandbox };
}

test('Settings has no pause / captcha inputs — the URL List bar owns them; the enable switch stays', () => {
  const box = settingsBox();
  assert.match(box, /id="cooldownEnabled" type="checkbox"/);
  assert.match(box, /Enable minimum pause between jobs/);
  for (const id of ['cooldownMinMinutes', 'cooldownCaptchaMinutes', 'cooldownRateLimitMinutes']) {
    assert.equal(box.includes(`id="${id}"`), false, `${id} must live only in the URL List bar`);
  }
  const html = read('index.html');
  for (const id of ['urlCooldownEnabled', 'urlCooldownMin', 'urlCooldownPenalty', 'urlCooldownRateLimit', 'urlCooldownSaveBtn']) {
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

test('load shows the stored enable switch (missing = on, like the URL List bar)', () => {
  const off = harness({ reply: { ok: true, config: { enabled: false } } });
  off.N.load();
  assert.equal(off.byId.cooldownEnabled.checked, false);
  const legacy = harness({ reply: { ok: true, config: {} } });
  legacy.byId.cooldownEnabled.checked = false;
  legacy.N.load();
  assert.equal(legacy.byId.cooldownEnabled.checked, true);
});

test('a reply without new_tab leaves the controls alone', () => {
  const { N, byId } = harness({ reply: { ok: true, config: { enabled: true } } });
  byId.newTabUrl.value = 'kept';
  N.init();
  assert.equal(byId.newTabUrl.value, 'kept');
});

test('Settings Save sends ONLY the switch + option — never pause / captcha / limit values', () => {
  const { S, byId, sent } = harness();
  byId.cooldownEnabled.checked = false;
  byId.newTabEnabled.checked = true;
  byId.newTabUrl.value = '  https://arena.ai/image/direct?model_a=max ';
  S.save();
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { enabled: false, new_tab: true, new_tab_url: 'https://arena.ai/image/direct?model_a=max' });
});

test('Settings Save logs one line with both parts', () => {
  const { S, byId, logs } = harness();
  byId.cooldownEnabled.checked = false;
  S.save();
  assert.ok(logs.some(([m, l]) => l === 'success' && m === 'Job Cycle saved: minimum pause off · new chat as new tab off'));
});

test('the cooldown push re-renders BOTH views from the one stored state', () => {
  const { N, byId, sandbox } = harness();
  const bar = [];
  sandbox.UrlListCooldown = { applyConfig(c) { bar.push(c); } };
  const push = { ok: true, config: { enabled: false, min_seconds: 420 }, new_tab: { enabled: true, url: 'https://arena.ai/x' } };
  N.apply(JSON.stringify(push));
  assert.deepEqual(bar, [push.config]);
  assert.equal(byId.cooldownEnabled.checked, false);
  assert.equal(byId.newTabEnabled.checked, true);
  assert.equal(byId.newTabUrl.value, 'https://arena.ai/x');
});

test('a failed or broken push changes no view', () => {
  const { N, byId, sandbox } = harness();
  const bar = [];
  sandbox.UrlListCooldown = { applyConfig(c) { bar.push(c); } };
  N.apply(JSON.stringify({ ok: false, error: 'disk' }));
  N.apply('not json');
  assert.deepEqual(bar, []);
  assert.equal(byId.cooldownEnabled.checked, true);
});

test('init connects the bridge push once; an emitted push re-renders both views', () => {
  const { N, byId, sandbox } = harness();
  const handlers = [];
  sandbox.App.bridge.cooldown_config_updated = { connect(fn) { handlers.push(fn); } };
  const bar = [];
  sandbox.UrlListCooldown = { applyConfig(c) { bar.push(c); } };
  N.init();
  N.init();
  assert.equal(handlers.length, 1);
  handlers[0](JSON.stringify({ ok: true, config: { enabled: false, min_seconds: 480 } }));
  assert.equal(byId.cooldownEnabled.checked, false);
  assert.deepEqual(bar, [{ enabled: false, min_seconds: 480 }]);
});

test('one handler set: only url-list/cooldown.js reads, validates and saves the bar', () => {
  const actions = read('js/panels/url-list/actions.js');
  assert.equal(/Cooldown|urlCooldown/.test(actions.split('\n').slice(1).join('\n')), false);
  const panel = read('js/panels/url-list.js');
  assert.equal(/_actions\?*\.(load|save)CooldownConfig/.test(panel), false);
  assert.match(panel, /this\._cooldown\?\.load\(\)/);
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
  // The RULE 24 refresh table moved out of the 368-line `panels/workspace.js`
  // into the slice that owns the flow when it was split (audit #3 L9), so the
  // mount no longer holds these names. Assert them where they live now, and keep
  // the negative case: the restored job cycle must NOT be pushed into the
  // Settings panel (that is the I-80 single-home fix).
  const ws = read('js/panels/workspace/flow.js');
  assert.match(ws, /\['UrlList', 'loadCooldownConfig'\]/);
  assert.match(ws, /\['JobCycleSetting', 'load'\]/);
  assert.equal(/\['SettingsPanel', 'loadCooldownConfig'\]/.test(ws), false);
  // the mount still wires the slices, so the table is reachable at all
  const mount = read('js/panels/workspace.js');
  assert.match(mount, /workspace\/flow\.js/);
});
