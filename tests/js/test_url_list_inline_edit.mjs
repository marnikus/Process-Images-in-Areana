/**
 * URL-list inline editing + global reset.
 *
 * Owner brief 2026-10-01: the URL List edits COOLDOWN and JOBS inline from the
 * displayed value (click/Enter/Space, Enter/blur save once, Escape cancel,
 * invalid restores), the separate cooldown ✎ is gone, and one toolbar button
 * resets every row's cooldown with one concise result message.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list');
const read = (f) => fs.readFileSync(path.join(JS, f), 'utf-8');

function harness() {
  const byId = {};
  const logs = [];
  const calls = [];
  const pending = [];
  const sandbox = {
    console, JSON, Math, Object, Array, Map, Set, String, Number, Boolean,
    parseInt, parseFloat, isNaN, Date,
    document: {
      getElementById: (id) => byId[id] || null,
      addEventListener() {},
      createElement(tag) {
        const el = new El(tag);
        el.value = '';
        el.focus = () => { el.focused = true; };
        el.select = () => { el.selected = true; };
        return el;
      },
    },
    LogConsole: { log: (m, l) => logs.push([m, l || 'info']) },
    PagePoolPanel: { fmt: (s) => {
      const total = Math.max(0, Number(s) || 0);
      const m = Math.floor(total / 60), sec = total % 60;
      return m < 60
        ? String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0')
        : Math.floor(m / 60) + ':' + String(m % 60).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    } },
    TabLabel: { of: (tabId) => tabId || '' },
  };
  sandbox.window = sandbox;
  sandbox.App = {
    bridge: {
      set_page_cooldown(tabId, secs, cb) {
        calls.push({ slot: 'set_page_cooldown', args: [tabId, secs] });
        cb(JSON.stringify({ ok: true }));
      },
      set_url_job_count(payload, cb) {
        calls.push({ slot: 'set_url_job_count', args: [payload] });
        cb(JSON.stringify({ ok: true }));
      },
      reset_all_url_cooldowns(cb) {
        calls.push({ slot: 'reset_all_url_cooldowns', args: [] });
        pending.push(cb);
      },
    },
    state: { urls: [] },
  };
  vm.createContext(sandbox);
  for (const f of ['store.js', 'crud-actions.js', 'actions.js', 'inline-edit.js', 'bulk-reset.js']) {
    vm.runInContext(read(f), sandbox, { filename: f });
  }
  return { IE: sandbox.window.UrlListInlineEdit, A: sandbox.window.UrlListActions, sandbox, byId, logs, calls, pending };
}

function mountButton(h, attrs) {
  const cell = new El('td');
  const shell = new El('span');
  shell.className = 'url-inline-shell';
  const btn = new El('button');
  btn.type = 'button';
  btn.className = 'url-inline-btn';
  btn.dataset = { ...attrs };
  btn.textContent = attrs.inlineText;
  shell.appendChild(btn);
  cell.appendChild(shell);
  return { cell, shell, btn };
}

function currentInput(shell) {
  return shell.children.find((c) => c.tagName === 'INPUT') || null;
}

describe('UrlListInlineEdit', () => {
  test('cooldown click → inline input, Enter then blur saves once, normalized', () => {
    const h = harness();
    const { shell, btn } = mountButton(h, {
      inlineField: 'cooldown', inlineValue: '05:00', inlineText: '05:00',
      inlineWidth: '5', inlineInputLabel: 'Edit cooldown for row 1', tabId: 't1', urlId: 'u1',
    });
    assert.equal(h.IE.start(btn), true);
    const input = currentInput(shell);
    assert.equal(input.value, '05:00');
    assert.equal(input.focused, true);
    assert.equal(input.selected, true);
    input.value = '01:30';
    input.dispatch('keydown', { key: 'Enter', preventDefault() {} });
    input.dispatch('blur', {});
    assert.deepEqual(h.calls, [{ slot: 'set_page_cooldown', args: ['t1', 90] }]);
    assert.equal(shell.children[0].textContent, '01:30');
  });

  test('cooldown invalid, empty, negative and unchanged values restore without saving', () => {
    const cases = ['abc', '', '-1:00', '05:00'];
    for (const value of cases) {
      const h = harness();
      const { shell, btn } = mountButton(h, {
        inlineField: 'cooldown', inlineValue: '05:00', inlineText: '05:00',
        inlineWidth: '5', inlineInputLabel: 'Edit cooldown', tabId: 't1', urlId: 'u1',
      });
      h.IE.start(btn);
      const input = currentInput(shell);
      input.value = value;
      input.dispatch('blur', {});
      assert.equal(shell.children[0].textContent, '05:00', value);
      assert.equal(h.calls.length, 0, value);
      assert.equal(h.logs.length, 0, value);
    }
  });

  test('cooldown blur saves H:MM:SS and Escape cancels', () => {
    const h = harness();
    const { shell, btn } = mountButton(h, {
      inlineField: 'cooldown', inlineValue: '59:59', inlineText: '59:59',
      inlineWidth: '5', inlineInputLabel: 'Edit cooldown', tabId: 't1', urlId: 'u1',
    });
    h.IE.start(btn);
    let input = currentInput(shell);
    input.value = '1:05:00';
    input.dispatch('blur', {});
    assert.deepEqual(h.calls[0], { slot: 'set_page_cooldown', args: ['t1', 3900] });
    assert.equal(shell.children[0].textContent, '1:05:00');
    h.IE.start(shell.children[0]);
    input = currentInput(shell);
    input.value = '00:30';
    input.dispatch('keydown', { key: 'Escape', preventDefault() {} });
    assert.equal(shell.children[0].textContent, '1:05:00');
    assert.equal(h.calls.length, 1);
  });

  test('jobs edit accepts whole non-negative numbers only and blur saves', () => {
    const h = harness();
    const { shell, btn } = mountButton(h, {
      inlineField: 'jobs', inlineValue: '3', inlineText: '3',
      inlineWidth: '2', inlineInputLabel: 'Edit jobs for row 1', tabId: 't1', urlId: 'u1',
    });
    h.IE.start(btn);
    const input = currentInput(shell);
    input.value = '12';
    input.dispatch('blur', {});
    assert.deepEqual(h.calls[0], { slot: 'set_url_job_count', args: ['{"url_id":"u1","count":12}'] });
    assert.equal(shell.children[0].textContent, '12');

    const bad = harness();
    const mounted = mountButton(bad, {
      inlineField: 'jobs', inlineValue: '12', inlineText: '12',
      inlineWidth: '2', inlineInputLabel: 'Edit jobs', tabId: 't1', urlId: 'u1',
    });
    bad.IE.start(mounted.btn);
    const badInput = currentInput(mounted.shell);
    badInput.value = '-1';
    badInput.dispatch('blur', {});
    assert.equal(mounted.shell.children[0].textContent, '12');
    assert.equal(bad.calls.length, 0);
  });

  test('keyboard start supports Enter and Space on the focusable value', () => {
    const h = harness();
    const { shell, btn } = mountButton(h, {
      inlineField: 'jobs', inlineValue: '7', inlineText: '7',
      inlineWidth: '1', inlineInputLabel: 'Edit jobs', tabId: 't1', urlId: 'u1',
    });
    h.IE.onButtonKey({ key: 'Enter', preventDefault() {} }, btn);
    assert.equal(currentInput(shell)?.value, '7');
    h.IE.cancel();
    h.IE.onButtonKey({ key: ' ', preventDefault() {} }, shell.children[0]);
    assert.equal(currentInput(shell)?.value, '7');
  });
});

describe('Reset all cooldowns button', () => {
  test('disabled when nothing can reset, enabled when a timer or debt exists', () => {
    const h = harness();
    const btn = new El('button');
    h.byId.urlResetAllCooldownsBtn = btn;
    h.A.updateResetAllButton([]);
    assert.equal(btn.disabled, true);
    h.A.updateResetAllButton([{ cooldown_remaining: 0, pending_penalty: 0 }]);
    assert.equal(btn.disabled, true);
    h.A.updateResetAllButton([{ cooldown_remaining: 90, pending_penalty: 0 }]);
    assert.equal(btn.disabled, false);
    h.A.updateResetAllButton([{ cooldown_remaining: 0, pending_penalty: 900 }]);
    assert.equal(btn.disabled, false);
  });

  test('one in-flight reset ignores repeated clicks, then reports one concise partial failure', () => {
    const h = harness();
    const btn = new El('button');
    btn.focus = () => { btn.focused = true; };
    h.byId.urlResetAllCooldownsBtn = btn;
    h.A.updateResetAllButton([{ cooldown_remaining: 90, pending_penalty: 0 }]);
    h.A.resetAllCooldowns();
    h.A.resetAllCooldowns();
    assert.equal(h.calls.length, 1);
    assert.equal(btn.disabled, true);
    h.pending[0](JSON.stringify({
      ok: true, reset_count: 2, failed_rows: [{ url: 'https://arena.ai/b', label: 'worker-2', error: 'persist failed' }],
    }));
    assert.equal(btn.focused, true);
    assert.equal(btn.disabled, true);
    assert.equal(h.logs.length, 1);
    assert.match(h.logs[0][0], /Reset all cooldowns: 2 reset/);
    assert.match(h.logs[0][0], /worker-2/);
    assert.equal(h.logs[0][1], 'warn');
  });
});


describe('static guard — row actions lost the cooldown ✎ button', () => {
  test('render.js has inline value buttons and no cool-edit action', () => {
    const src = read('render.js');
    assert.doesNotMatch(src, /data-action="cool-edit"/);
    assert.match(src, /url-jobs-cell/);
  });
});
