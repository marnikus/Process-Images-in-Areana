/* Captcha panel provider-selection tests — execute the REAL panel source
   (app/ui/web/js/panels/captcha.js) against a stub DOM + fake bridge
   (RULE 8: run the real thing, don't string-assert).

   Regression: picking a provider used to call loadStatus(), which re-synced
   the drop-down from the STORED provider — the selection snapped back to
   2Captcha before Save could ever happen. A provider switch must stick with
   or without a saved key; balance problems report, never revert. */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

/* ——— minimal DOM stub (just the ids the panel touches) ——— */

class El {
  constructor(id, tag = 'input') {
    this.id = id;
    this.tagName = tag.toUpperCase();
    this._value = '';
    this.checked = false;
    this.handlers = {};
  }
  addEventListener(ev, fn) { (this.handlers[ev] ||= []).push(fn); }
  fire(ev) { (this.handlers[ev] || []).forEach((fn) => fn({ target: this })); }
  get value() { return this._value; }
  set value(v) { this._value = String(v); }
}

function makeDom() {
  const ids = ['captchaSaveBtn', 'captchaStatsBtn', 'captchaKeyShow', 'captchaProvider',
               'captchaEnabled', 'captchaApiKey', 'captchaTimeoutMin', 'captchaStatusLine',
               'capStatBalance', 'capStatDetected', 'capStatAuto', 'capStatFailed',
               'capStatRate', 'capStatManual'];
  const els = {};
  for (const id of ids) els[id] = new El(id, id === 'captchaProvider' ? 'select' : 'input');
  els.captchaStatusLine.textContent = '';
  return {
    els,
    getElementById: (id) => els[id] || null,
  };
}

/* ——— fake WebChannel bridge ——— */

function makeBridge(statusPayload, capture = {}) {
  const state = { ...statusPayload };  // mirrors the real store: Save commits
  return {
    get_captcha_status: (cb) => cb(JSON.stringify({ ok: true, ...state })),
    set_captcha_settings: (json, cb) => {
      capture.saved = JSON.parse(json);
      const saved = capture.saved;
      const key = (saved.api_key || '').trim()
        || (state.providers?.[saved.provider]?.has_key ? 'kept' : '');
      state.providers = { ...(state.providers || {}),
        [saved.provider]: { enabled: !!(saved.enabled && key), has_key: !!key,
                            masked_key: key ? 'abcd****wxyz' : '' } };
      state.provider = saved.provider;  // apply_settings commits the active provider
      state.enabled = state.providers[saved.provider].enabled;
      state.has_key = !!key;
      state.masked_key = state.providers[saved.provider].masked_key;
      cb(JSON.stringify({ ok: true, provider: saved.provider,
                          enabled: state.providers[saved.provider].enabled,
                          masked_key: state.providers[saved.provider].masked_key || '(empty)' }));
    },
    get_captcha_stats: (cb) => cb(JSON.stringify({ ok: true, detected_total: 0 })),
  };
}

function loadPanel(dom, bridge, logs, timers) {
  const src = readFileSync(join(ROOT, 'app', 'ui', 'web', 'js', 'panels', 'captcha.js'), 'utf8');
  const fn = new Function('document', 'App', 'LogConsole', 'setTimeout',
                          `${src}; return CaptchaPanel;`);
  const panel = fn(dom, { bridge },
                   { log: (m, l = 'info') => logs.push([m, l]) },
                   (f, ms) => timers.push([f, ms]));
  return panel;
}

const storedStatus = (active = '2captcha') => ({
  provider: active,
  enabled: true,
  has_key: true,
  masked_key: 'two0****1234',
  solve_timeout_sec: 180,
  balance: 12.34,
  balance_at: '12:03',
  last_error: '',
  providers: {
    '2captcha': { enabled: true, has_key: true, masked_key: 'two0****1234' },
    'capmonster': { enabled: false, has_key: false, masked_key: '' },
  },
});

function setup(active = '2captcha', status = storedStatus(active)) {
  const dom = makeDom();
  const logs = [];
  const timers = [];
  const capture = {};
  const bridge = makeBridge(status, capture);
  const panel = loadPanel(dom, bridge, logs, timers);
  panel.init();                   // the page bootstrap calls this
  timers.forEach(([f]) => f());   // run the deferred initial loads now
  return { dom, logs, capture, panel };
}


test('initial load syncs the drop-down to the stored provider', () => {
  const { dom } = setup('2captcha');
  assert.equal(dom.els.captchaProvider.value, '2captcha');
  assert.equal(dom.els.captchaEnabled.checked, true);  // stored provider is enabled+keyed
});

test('switching provider never snaps back — even on later reloads', () => {
  const { dom, panel } = setup();
  dom.els.captchaApiKey.value = 'two0leftover';
  dom.els.captchaProvider.value = 'capmonster';
  dom.els.captchaProvider.fire('change');
  assert.equal(dom.els.captchaProvider.value, 'capmonster');  // selection sticks
  assert.equal(dom.els.captchaApiKey.value, '');              // key field cleared

  // a status reload (timer, stats refresh, anything) must NOT revert it
  panel.loadStatus();
  assert.equal(dom.els.captchaProvider.value, 'capmonster');
});

test('status line shows the SELECTED provider state + save hint, not the other one', () => {
  const { dom } = setup();
  dom.els.captchaProvider.value = 'capmonster';
  dom.els.captchaProvider.fire('change');
  const line = dom.els.captchaStatusLine.textContent;
  assert.match(line, /CapMonster Cloud/);
  assert.match(line, /key: \(not set\)/);
  assert.match(line, /press Save to switch/);
  assert.doesNotMatch(line, /two0\*\*\*\*1234/);          // other provider's mask stays out
  assert.doesNotMatch(line, /\$12\.34/);                  // balance belongs to 2Captcha
});

test('save posts the selected provider and key; success keeps the selection', () => {
  const { dom, capture, panel } = setup();
  dom.els.captchaProvider.value = 'capmonster';
  dom.els.captchaProvider.fire('change');
  dom.els.captchaEnabled.checked = true;
  dom.els.captchaApiKey.value = 'cmkey12345678';
  panel.save();
  assert.equal(capture.saved.provider, 'capmonster');
  assert.equal(capture.saved.api_key, 'cmkey12345678');
  assert.equal(capture.saved.enabled, true);
  // post-save reload: stored state now matches — selection stays capmonster
  assert.equal(dom.els.captchaProvider.value, 'capmonster');
});

test('enable without a key: provider still saved, warning tells the user', () => {
  const { dom, capture, logs, panel } = setup();
  dom.els.captchaProvider.value = 'capmonster';
  dom.els.captchaProvider.fire('change');
  dom.els.captchaEnabled.checked = true;  // no key pasted, none stored
  panel.save();
  assert.equal(capture.saved.provider, 'capmonster');  // selection is saved anyway
  assert.equal(capture.saved.enabled, true);
  assert.ok(logs.some(([m, l]) => l === 'warn' && /needs an API key/.test(m) && /CapMonster Cloud/.test(m)));
});

test('balance/last error are only shown for the active provider after save', () => {
  const status = storedStatus('capmonster');
  status.balance = 7.77;
  status.providers.capmonster = { enabled: true, has_key: true, masked_key: 'capm****5678' };
  const { dom } = setup('capmonster', status);
  const line = dom.els.captchaStatusLine.textContent;
  assert.match(line, /CapMonster Cloud/);
  assert.match(line, /\$7\.77/);
  assert.doesNotMatch(line, /two0\*\*\*\*1234/);
});
