/**
 * B10 — Captcha window provider dropdown (2Captcha | CapMonster Cloud).
 * Whole page, real scripts, fake bridge: the dropdown mirrors the bridge's
 * provider reply, switching calls `set_captcha_provider`, Save stores the key
 * for the ACTIVE provider, and a rejected switch snaps the dropdown back.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { bootPage } from './page_harness.mjs';

const MASK2 = 'abcd****7890';

function providerReply(active, keys = { '2captcha': MASK2, capmonster: '' }) {
  const providers = [
    { id: '2captcha', label: '2Captcha', server: '2captcha.com', dashboard: 'https://2captcha.com/enterpage', has_key: !!keys['2captcha'], masked_key: keys['2captcha'] || '' },
    { id: 'capmonster', label: 'CapMonster Cloud', server: 'api.capmonster.cloud', dashboard: 'https://capmonster.cloud/Dashboard', has_key: !!keys.capmonster, masked_key: keys.capmonster || '' },
  ];
  const me = providers.find((p) => p.id === active);
  return { ok: true, has_key: me.has_key, masked_key: me.masked_key, provider: active, provider_label: me.label, providers };
}

function boot(overrides = {}) {
  const state = { active: '2captcha', keys: { '2captcha': MASK2, capmonster: '' } };
  const page = bootPage({
    replies: {
      get_captcha_api_key: () => JSON.stringify(providerReply(state.active, state.keys)),
      set_captcha_provider: (pid) => {
        if (pid === 'bogus') return JSON.stringify({ ok: false, error: "unknown provider 'bogus'" });
        state.active = pid;
        return JSON.stringify(providerReply(state.active, state.keys));
      },
      set_captcha_api_key: (key) => {
        state.keys[state.active] = key ? key.slice(0, 4) + '****' + key.slice(-4) : '';
        return JSON.stringify(providerReply(state.active, state.keys));
      },
      watcher_status: () => JSON.stringify({ ok: true, running: false, has_key: !!state.keys[state.active], sdk_available: true,
        provider: state.active, provider_label: providerReply(state.active).provider_label, solved_total: 0, failed_total: 0, tabs_seen: 0, balance: null }),
      ...overrides,
    },
    prepare: (anyEl) => {
      const sel = anyEl('captchaProvider');
      sel.tagName = 'SELECT';
      sel.options = [{ value: '2captcha', textContent: '2Captcha' }, { value: 'capmonster', textContent: 'CapMonster Cloud' }];
      sel.value = '2captcha';
    },
  });
  page.flushTimers();   // CaptchaPanel.init → setTimeout(refresh, 1200)
  return { ...page, state, sel: page.anyEl('captchaProvider') };
}

describe('B10 — Captcha window provider dropdown', () => {
  test('refresh fills the dropdown from get_captcha_api_key: value, ✓ labels, hint, key label', () => {
    const { sel, anyEl, calls } = boot();
    assert.ok(calls.some((c) => c.slot === 'get_captcha_api_key'));
    assert.equal(sel.value, '2captcha');
    assert.equal(sel.options[0].textContent, '2Captcha ✓ key set');
    assert.equal(sel.options[1].textContent, 'CapMonster Cloud — no key');
    assert.equal(anyEl('captchaProviderHint').textContent, `key: ${MASK2}`);
    assert.ok(anyEl('captchaKeyLabel').textContent.startsWith('2Captcha API key'));
    assert.equal(anyEl('captchaApiKey').placeholder, 'paste 2Captcha API key');
    assert.ok(anyEl('captchaStatusLine').textContent.includes('2Captcha key: set'));
  });

  test('choosing CapMonster calls set_captcha_provider and re-labels the window', () => {
    const { sel, anyEl, calls, logs, state, flushTimers } = boot();
    sel.value = 'capmonster';
    sel.dispatch('change', { target: sel });
    const sw = calls.filter((c) => c.slot === 'set_captcha_provider');
    assert.deepEqual(sw.map((c) => c.args), [['capmonster']]);
    assert.equal(state.active, 'capmonster');
    assert.equal(sel.value, 'capmonster');
    assert.equal(anyEl('captchaProviderHint').textContent, 'key: (not set)');
    assert.ok(anyEl('captchaKeyLabel').textContent.startsWith('CapMonster Cloud API key'));
    assert.equal(anyEl('captchaApiKey').placeholder, 'paste CapMonster Cloud API key');
    assert.ok(logs.some((l) => l === 'warn: Captcha provider: CapMonster Cloud — paste its API key and Save'), logs.join('\n'));
    flushTimers();   // deferred loadStatus
    assert.ok(anyEl('captchaStatusLine').textContent.includes('no CapMonster Cloud key'));
  });

  test('Save stores the key for the ACTIVE provider and clears the field', () => {
    const { sel, anyEl, calls, logs, state } = boot();
    sel.value = 'capmonster';
    sel.dispatch('change', { target: sel });
    anyEl('captchaApiKey').value = 'capmonster-key-0123456789';
    anyEl('captchaSaveBtn').dispatch('click', {});
    const saves = calls.filter((c) => c.slot === 'set_captcha_api_key');
    assert.deepEqual(saves.map((c) => c.args), [['capmonster-key-0123456789']]);
    assert.equal(state.keys.capmonster, 'capm****6789');
    assert.equal(anyEl('captchaApiKey').value, '');
    assert.ok(logs.some((l) => l === 'success: CapMonster Cloud key saved: capm****6789'), logs.join('\n'));
    assert.equal(sel.options[1].textContent, 'CapMonster Cloud ✓ key set');
    assert.equal(sel.options[0].textContent, '2Captcha ✓ key set', 'the 2Captcha key is untouched');
    assert.ok(!logs.some((l) => l.includes('capmonster-key-0123456789')), 'raw key never logged');
  });

  test('a rejected provider switch is logged and the dropdown snaps back', () => {
    const { sel, anyEl, logs, state } = boot();
    sel.value = 'bogus';
    sel.dispatch('change', { target: sel });
    assert.equal(state.active, '2captcha');
    assert.equal(sel.value, '2captcha');
    assert.equal(anyEl('captchaProviderHint').textContent, `key: ${MASK2}`);
    assert.ok(logs.some((l) => l.startsWith("error: Captcha provider switch failed: unknown provider 'bogus'")), logs.join('\n'));
  });

  test('the panel works against an older bridge without the provider slot', () => {
    const page = bootPage({
      replies: { get_captcha_api_key: { ok: true, has_key: false, masked_key: '' } },
      prepare: (anyEl) => { anyEl('captchaProvider').options = []; anyEl('captchaProviderHint').textContent = 'key: —'; },
    });
    page.flushTimers();
    assert.deepEqual(page.errors.filter((e) => /Captcha/.test(e)), []);
    assert.equal(page.anyEl('captchaProviderHint').textContent, 'key: —', 'left untouched without a providers list');
  });

  test('a non-callable (signal-shaped) watcher_status is skipped, never thrown (2026-09-25)', () => {
    // QWebChannel exposes signals as {connect,disconnect}; when a signal shares
    // a slot name, `data.signals` runs LAST and overwrites the callable method —
    // `_call` must skip the non-callable instead of dying with
    // `TypeError: fn is not a function` (the startup crash).
    const page = bootPage({
      rawBridgeProps: { watcher_status: { connect() {} } },
    });
    page.flushTimers();   // CaptchaPanel.init → setTimeout(refresh, 1200)
    assert.ok(!page.calls.some((c) => c.slot === 'watcher_status'),
      'the non-callable must never be invoked');
    assert.ok(page.calls.some((c) => c.slot === 'get_captcha_api_key'),
      'refresh() continued to the remaining pulls');
  });
});
