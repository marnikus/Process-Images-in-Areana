import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { El } from './fake_dom.mjs';
import { bootPage, WEB } from './page_harness.mjs';

const JS_DIR = path.join(WEB, 'js/panels/url-list');
const source = (name) => fs.readFileSync(path.join(JS_DIR, name), 'utf8');
const slotCalls = (h, slot) => h.calls.filter((call) => call.slot === slot);

function setup({ replies = {}, pages = [], rawBridgeProps = {} } = {}) {
  const h = bootPage({ replies, rawBridgeProps, prepare: (anyEl) => {
    anyEl('urlResetAllCooldownsBtn').tagName = 'BUTTON';
  } });
  const tbody = h.anyEl('urlTableBody');
  const tr = new El('tr');
  tr.dataset.urlId = 'url-1';
  const cell = new El('td');
  cell.className = 'url-cool-cell';
  const makeButton = (kind, value, label = 'worker-1') => {
    const button = new El('button');
    button.className = 'url-inline-value';
    button.dataset.inlineKind = kind;
    button.dataset.tabId = 'tab-1';
    button.dataset.inlineLabel = label;
    button.dataset.urlId = 'url-1';
    button.textContent = value;
    cell.appendChild(button);
    return button;
  };
  const cool = makeButton('cooldown', '02:00');
  const jobsCell = new El('td');
  jobsCell.className = 'url-jobs-cell';
  const jobs = new El('button');
  jobs.className = 'url-inline-value';
  jobs.dataset.inlineKind = 'jobs';
  jobs.dataset.tabId = 'tab-1';
  jobs.dataset.inlineLabel = 'worker-1';
  jobs.dataset.urlId = 'url-1';
  jobs.textContent = '7';
  jobsCell.appendChild(jobs);
  tr.appendChild(cell);
  tr.appendChild(jobsCell);
  tbody.appendChild(tr);
  if (pages.length) h.emit('page_pool_updated', JSON.stringify({ total: pages.length, pages }));
  return { h, tr, cool, jobs, cell, jobsCell, reset: h.anyEl('urlResetAllCooldownsBtn') };
}

function key(el, keyName) {
  let prevented = false;
  el.dispatchBubbling('keydown', { key: keyName, preventDefault() { prevented = true; } });
  return prevented;
}

function click(el) { el.dispatchBubbling('click', { preventDefault() {} }); }
function inputOf(row) { return row.querySelector('input.url-inline-input'); }

const page = (extra = {}) => ({ tab_id: 'tab-1', tab_label: 'worker-1', status: 'cooldown',
  cooldown_remaining: 120, cooldown_total: 120, pending_penalty: 0, jobs_completed: 7,
  url: 'https://arena.ai/c/1', ...extra });

describe('URL List inline value editor', () => {
  test('pool snapshots render focusable COOLDOWN and JOBS buttons with worker labels', () => {
    const h = bootPage();
    const tr = new El('tr');
    tr.dataset.urlId = 'url-1';
    const cool = new El('td');
    cool.className = 'url-cool-cell';
    const reset = new El('button');
    reset.dataset.action = 'cool-reset';
    tr.appendChild(cool);
    tr.appendChild(reset);
    h.run('UrlListCells').fillCoolCell(tr, page({ cooldown_remaining: 120, cooldown_total: 300 }));
    assert.match(cool.innerHTML, /<button type="button" class="url-inline-value url-inline-cooldown"/);
    assert.match(cool.innerHTML, /data-inline-kind="cooldown"/);
    assert.match(cool.innerHTML, /aria-label="Cooldown for worker-1"/);

    const jobs = new El('td');
    jobs.className = 'url-jobs-cell';
    tr.appendChild(jobs);
    h.run('UrlListInlineEdit').fillJobsCell(tr, page({ jobs_completed: 7 }));
    assert.match(jobs.innerHTML, /<button type="button" class="url-inline-value url-inline-jobs"/);
    assert.match(jobs.innerHTML, /data-inline-kind="jobs"/);
    assert.match(jobs.innerHTML, /aria-label="Jobs for worker-1"/);
  });

  test('mouse click and Enter/Space open the shared editor; input is prefilled, focused, selected', () => {
    const mouse = setup();
    mouse.cool._rect.width = 112;
    click(mouse.cool);
    let input = inputOf(mouse.tr);
    assert.ok(input, 'clicking COOLDOWN opens an input');
    assert.equal(input.style.width, '112px', 'the editor preserves the displayed value width');
    assert.equal(input.value, '02:00');
    assert.equal(input.focused, true);
    assert.equal(input.selected, true);
    assert.equal(input.getAttribute('aria-label'), 'Cooldown for worker-1');

    const keyboard = setup();
    assert.equal(key(keyboard.jobs, ' '), true, 'Space is consumed instead of generating a second click');
    input = inputOf(keyboard.tr);
    assert.ok(input, 'Space opens JOBS');
    assert.equal(input.value, '7');
    assert.equal(input.focused, true);
    assert.equal(input.selected, true);
  });

  test('Enter saves once; a following blur cannot duplicate the save', () => {
    const { h, tr, cool } = setup({ replies: { set_page_cooldown: { ok: true } } });
    click(cool);
    const input = inputOf(tr);
    input.value = '1:30';
    key(input, 'Enter');
    input.dispatch('blur', { type: 'blur', target: input });
    assert.deepEqual(slotCalls(h, 'set_page_cooldown').map((c) => c.args), [['tab-1', 90]]);
    assert.equal(tr.querySelector('.url-cool-cell').textContent, '01:30');
  });

  test('outside pointer saves and blur remains exactly-once', () => {
    const { h, tr, jobs } = setup({ replies: { set_page_job_count: { ok: true, changed: true, persisted: true } } });
    click(jobs);
    const input = inputOf(tr);
    input.value = '9';
    const outside = h.anyEl('outsideTarget');
    h.sb.document.dispatchEvent({ type: 'pointerdown', target: outside });
    input.dispatch('blur', { type: 'blur', target: input });
    assert.deepEqual(slotCalls(h, 'set_page_job_count').map((c) => c.args), [['tab-1', '9']]);
    assert.equal(tr.querySelector('.url-jobs-cell').textContent, '9');
  });

  test('a synchronous bridge error restores the original value and reports the failure', () => {
    const { h, tr, jobs } = setup({ rawBridgeProps: {
      set_page_job_count: () => { throw new Error('offline'); },
    } });
    click(jobs);
    inputOf(tr).value = '8';
    key(inputOf(tr), 'Enter');
    assert.equal(tr.querySelector('.url-jobs-cell').textContent, '7');
    assert.ok(h.logs.some((line) => line.includes('offline')));
  });

  test('Escape cancels without a slot call and restores the prior value', () => {
    const { h, tr, cool } = setup();
    click(cool);
    const input = inputOf(tr);
    input.value = '00:00';
    key(input, 'Escape');
    assert.equal(slotCalls(h, 'set_page_cooldown').length, 0);
    assert.equal(tr.querySelector('.url-cool-cell').textContent, '02:00');
  });

  test('cooldown parser accepts the display forms and enforces the one-day range', () => {
    const { h } = setup();
    const editor = h.sb.UrlListInlineEdit;
    assert.equal(editor.normalizeCooldown('5:09').seconds, 309);
    assert.equal(editor.normalizeCooldown('5:09').display, '05:09');
    assert.equal(editor.normalizeCooldown('1:02:03').seconds, 3723);
    assert.equal(editor.normalizeCooldown('1:02:03').display, '1:02:03');
    assert.equal(editor.normalizeCooldown('24:00:00').seconds, 86400);
    assert.equal(editor.normalizeCooldown('24:00:00').display, '24:00:00');
    for (const raw of ['', '  ', '-1:00', '1.5', 'word', '00:60', '1:60:00', '25:00:00', '24:00:01', '90:00']) {
      assert.equal(editor.normalizeCooldown(raw), null, `reject ${JSON.stringify(raw)}`);
    }
  });

  test('cooldown accepts zero, rejects invalid input, and skips an unchanged normalized value', () => {
    const zero = setup({ replies: { set_page_cooldown: { ok: true } } });
    click(zero.cool);
    inputOf(zero.tr).value = '00:00';
    key(inputOf(zero.tr), 'Enter');
    assert.deepEqual(slotCalls(zero.h, 'set_page_cooldown').map((c) => c.args), [['tab-1', 0]]);
    assert.equal(zero.tr.querySelector('.url-cool-cell').textContent, '00:00');

    for (const raw of ['', '   ', '-00:01', 'nonsense', '24:00:01']) {
      const invalid = setup();
      click(invalid.cool);
      inputOf(invalid.tr).value = raw;
      key(inputOf(invalid.tr), 'Enter');
      assert.equal(slotCalls(invalid.h, 'set_page_cooldown').length, 0, `no save for ${JSON.stringify(raw)}`);
      assert.equal(invalid.tr.querySelector('.url-cool-cell').textContent, '02:00');
    }

    const unchanged = setup();
    const beforeLogs = unchanged.h.logs.length;
    click(unchanged.cool);
    inputOf(unchanged.tr).value = '2:00';
    key(inputOf(unchanged.tr), 'Enter');
    assert.equal(slotCalls(unchanged.h, 'set_page_cooldown').length, 0);
    assert.equal(unchanged.h.logs.length, beforeLogs);
    assert.equal(unchanged.tr.querySelector('.url-cool-cell').textContent, '02:00');
  });

  test('JOBS accepts whole non-negative counts, normalizes zeros, and ignores invalid/unchanged input', () => {
    const changed = setup({ replies: { set_page_job_count: { ok: true, changed: true, persisted: true } } });
    click(changed.jobs);
    inputOf(changed.tr).value = '0008';
    key(inputOf(changed.tr), 'Enter');
    assert.deepEqual(slotCalls(changed.h, 'set_page_job_count').map((c) => c.args), [['tab-1', '8']]);
    assert.equal(changed.tr.querySelector('.url-jobs-cell').textContent, '8');

    for (const raw of ['', ' ', '-1', '1.5', '1e3', '+2', '2 jobs']) {
      const invalid = setup();
      click(invalid.jobs);
      inputOf(invalid.tr).value = raw;
      key(inputOf(invalid.tr), 'Enter');
      assert.equal(slotCalls(invalid.h, 'set_page_job_count').length, 0, `no save for ${JSON.stringify(raw)}`);
      assert.equal(invalid.tr.querySelector('.url-jobs-cell').textContent, '7');
    }
    const unchanged = setup();
    click(unchanged.jobs);
    inputOf(unchanged.tr).value = '0007';
    key(inputOf(unchanged.tr), 'Enter');
    assert.equal(slotCalls(unchanged.h, 'set_page_job_count').length, 0);
  });
});

describe('URL List reset-all cooldown toolbar control', () => {
  test('disabled with no resettable cooldown; active and pending snapshots enable it', () => {
    const { h, reset } = setup();
    assert.equal(reset.disabled, true);
    h.emit('page_pool_updated', JSON.stringify({ pages: [page({ cooldown_remaining: 0, pending_penalty: 0 })] }));
    assert.equal(reset.disabled, true);
    h.emit('page_pool_updated', JSON.stringify({ pages: [page({ cooldown_remaining: 0, pending_penalty: 30 })] }));
    assert.equal(reset.disabled, false, 'pending debt counts as a cooldown to reset');
    h.emit('page_pool_updated', JSON.stringify({ pages: [page({ cooldown_remaining: 12, pending_penalty: 0 })] }));
    assert.equal(reset.disabled, false);
    h.emit('page_pool_updated', JSON.stringify({ pages: [page({ status: 'busy', current_image: 'run.png',
      cooldown_remaining: 0, pending_penalty: 30 })] }));
    assert.equal(reset.disabled, true, 'debt protected by an active job is not resettable yet');
  });

  test('busy guard blocks repeat clicks until the one batch reply completes', () => {
    let reply, calls = 0;
    const { h, reset } = setup({ pages: [page()], rawBridgeProps: {
      reset_all_cooldowns: (cb) => { calls += 1; reply = cb; },
    } });
    click(reset);
    assert.equal(reset.disabled, true);
    assert.equal(reset.getAttribute('aria-busy'), 'true');
    click(reset);
    assert.equal(calls, 1);
    h.emit('page_pool_updated', JSON.stringify({ pages: [page({ cooldown_remaining: 0, pending_penalty: 0 })] }));
    reply(JSON.stringify({ ok: true, reset: 1, reset_tab_ids: ['tab-1'], failed_tab_ids: [], deferred_tab_ids: [], persisted: true }));
    assert.equal(reset.getAttribute('aria-busy'), 'false');
    assert.equal(reset.disabled, true);
    assert.equal(h.logs.filter((line) => line.includes('Reset all cooldowns:')).length, 1);
  });

  test('partial persistence failure reports the affected workers in one concise message', () => {
    const { h, reset } = setup({ pages: [page(), page({ tab_id: 'tab-2', tab_label: 'worker-2' })],
      rawBridgeProps: { reset_all_cooldowns: (cb) => cb(JSON.stringify({
        ok: true, reset: 2, reset_tab_ids: ['tab-1', 'tab-2'],
        failed_tab_ids: [], deferred_tab_ids: [], persisted: false,
      })) },
    });
    click(reset);
    const messages = h.logs.filter((line) => line.includes('Reset all cooldowns:'));
    assert.equal(messages.length, 1);
    assert.match(messages[0], /2/);
    assert.match(messages[0], /tab-1/);
    assert.match(messages[0], /tab-2/);
  });

  test('partial worker apply failure names the skipped worker without per-row spam', () => {
    const { h, reset } = setup({ pages: [page(), page({ tab_id: 'tab-2', tab_label: 'worker-2' })],
      rawBridgeProps: { reset_all_cooldowns: (cb) => cb(JSON.stringify({
        ok: true, reset: 1, reset_tab_ids: ['tab-1'], failed_tab_ids: ['tab-2'],
        deferred_tab_ids: [], persisted: true,
      })) },
    });
    click(reset);
    const messages = h.logs.filter((line) => line.includes('Reset all cooldowns:'));
    assert.equal(messages.length, 1);
    assert.match(messages[0], /1 reset/);
    assert.match(messages[0], /worker-2 \(tab-2\)/);
  });

  test('row pencil is removed while the Page Pool edit control is retained', () => {
    const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
    assert.match(html, /id="urlResetAllCooldownsBtn"[^>]*disabled/);
    assert.match(html, /aria-label="Reset all cooldowns"/);
    assert.doesNotMatch(source('render.js'), /data-action="cool-edit"/);
    assert.doesNotMatch(source('reset.js'), /cool-edit|editCooldown/);
    assert.doesNotMatch(source('listeners.js'), /cool-edit/);
    assert.match(fs.readFileSync(path.join(WEB, 'js/panels/page-pool/render.js'), 'utf8'), /data-cool-edit/);
    assert.match(fs.readFileSync(path.join(WEB, 'css/arena.css'), 'utf8'), /url-inline-value:focus-visible/);
  });
});
