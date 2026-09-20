/**
 * B11 — "action blocks are missing": the header badge said "16 BLOCKS" while
 * the stack list stayed empty. Whole-page regression: the REAL index.html
 * scripts render the REAL Python default stack into the REAL container ids.
 *
 * Root cause: block-render.js / block-config.js (C7 split) targeted a DOM
 * that never existed in index.html (#panel-action-blocks, #ab-block-list,
 * #ab-config-form, …) and silently returned; only the footer counters used
 * the real ids. Nothing rendered, nothing was reported.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { bootPage } from './page_harness.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

/** The backend's default stack — executed, not transcribed (RULE 8). */
function pythonDefaultBlocks() {
  const code = 'import json,sys; sys.path.insert(0, "."); ' +
    'from app.core.action_blocks_defaults import build_default_dicts; ' +
    'print(json.dumps(build_default_dicts()))';
  const out = execFileSync(process.env.PYTHON || 'python3', ['-c', code], { cwd: ROOT, encoding: 'utf8' });
  return JSON.parse(out);
}

/** The backend's builtin catalog (labels per block type) — executed too. */
function pythonBuiltinCatalog() {
  const code = 'import sys; sys.path.insert(0, "."); ' +
    'from app.core.action_blocks import get_builtin_blocks_json; print(get_builtin_blocks_json())';
  return JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', code], { cwd: ROOT, encoding: 'utf8' }));
}

const DEFAULTS = pythonDefaultBlocks();
const CATALOG = pythonBuiltinCatalog();

function rows(page) { return page.anyEl('actionBlocksStack').children; }
function rowFor(page, blockId) { return rows(page).find((r) => r.dataset.blockId === blockId); }
function lastCall(page, slot) { return [...page.calls].reverse().find((c) => c.slot === slot); }
function savedBlocks(page) { const c = lastCall(page, 'save_action_blocks'); return c ? JSON.parse(c.args[0]) : null; }

test('python default stack is the documented 16-block shape (no leaked class constants)', () => {
  assert.equal(DEFAULTS.length, 16);
  for (const b of DEFAULTS) {
    assert.equal(typeof b.id, 'string');
    assert.equal(typeof b.block_id, 'string');
    const leaked = Object.keys(b).filter((k) => k.startsWith('_'));
    assert.deepEqual(leaked, [], `${b.block_id} serialises private attrs: ${leaked}`);
  }
});

test('boot with the backend stack renders one .action-block row per block into #actionBlocksStack', () => {
  const page = bootPage({ replies: { get_action_blocks: DEFAULTS } });
  const list = rows(page);
  assert.equal(list.length, 16, 'stack list must show the 16 blocks the badge counts');
  assert.equal(page.anyEl('actionBlocksCount').textContent, '16 blocks');
  assert.equal(page.anyEl('abTotalSteps').textContent, 'Total: 16 steps');
  list.forEach((row, i) => {
    assert.ok(row.classList.contains('action-block'), `row ${i} uses the arena.css .action-block contract`);
    assert.equal(row.dataset.blockId, DEFAULTS[i].id);
    assert.equal(row.dataset.index, String(i));
    assert.equal(row.draggable, true);
    assert.ok(row.querySelector('.ab-block-title'), 'row has a title');
    assert.ok(row.querySelector('.ab-check'), 'row has the enable toggle');
  });
  const required = DEFAULTS.filter((b) => b.required);
  assert.ok(required.length >= 5);
  for (const b of required) {
    const row = rowFor(page, b.id);
    assert.equal(row.querySelector('.ab-delete-btn'), null, `${b.block_id} is required → no delete button`);
    assert.equal(row.querySelector('.ab-check').disabled, true, `${b.block_id} is required → toggle locked`);
  }
  assert.deepEqual(page.errors, []);
});

test('an empty backend reply still renders the healed default stack', () => {
  const page = bootPage({ replies: { get_action_blocks: [] } });
  assert.equal(rows(page).length, 16);
  assert.equal(page.anyEl('actionBlocksCount').textContent, '16 blocks');
});

test('action_blocks_updated push re-renders the list to the pushed stack', () => {
  const page = bootPage({ replies: { get_action_blocks: DEFAULTS } });
  const extra = { ...DEFAULTS[0], id: 'highlight_attach_extra', custom_name: 'Second highlight' };
  page.emit('action_blocks_updated', JSON.stringify([...DEFAULTS, extra]));
  assert.equal(rows(page).length, 17);
  assert.equal(page.anyEl('actionBlocksCount').textContent, '17 blocks');
  assert.match(rowFor(page, 'highlight_attach_extra').querySelector('.ab-block-title').textContent, /Second highlight/);
});

test('selecting a row opens it in the Block Config window; edits reach save_action_blocks', () => {
  const page = bootPage({ replies: { get_action_blocks: DEFAULTS } });
  const target = DEFAULTS.find((b) => b.block_id === 'SUBMIT');
  const row = rowFor(page, target.id);
  row.dispatch('click', { target: row.querySelector('.ab-block-info') });
  assert.ok(rowFor(page, target.id).classList.contains('selected'), 'selected row is highlighted');
  assert.match(page.anyEl('blockConfigHead').textContent, /Submit Once/);
  assert.match(page.anyEl('blockConfigHead').textContent, /SUBMIT/);
  const form = page.anyEl('blockConfigForm');
  const sel = form.querySelectorAll('.bc-field').find((i) => i.dataset.fieldKey === 'selector');
  assert.ok(sel, 'config form exposes the selector field');
  assert.equal(sel.value, target.selector);
  sel.value = 'button[data-testid="send"]';
  form.dispatch('input', { target: sel });
  page.flushTimers();                       // debounced config save
  const saved = savedBlocks(page);
  assert.ok(saved, 'edit persisted through save_action_blocks');
  assert.equal(saved.find((b) => b.id === target.id).selector, 'button[data-testid="send"]');
  assert.deepEqual(page.errors, []);
});

test('enable toggle persists enabled=false and marks the row', () => {
  const page = bootPage({ replies: { get_action_blocks: DEFAULTS } });
  const target = DEFAULTS.find((b) => !b.required);
  const row = rowFor(page, target.id);
  const check = row.querySelector('.ab-check');
  check.checked = false;
  row.dispatch('click', { target: check });
  assert.equal(savedBlocks(page).find((b) => b.id === target.id).enabled, false);
  assert.ok(rowFor(page, target.id).classList.contains('ab-disabled'));
  assert.equal(page.anyEl('abSelectedSteps').textContent, 'Selected: 15 steps');
});

test('drag reorder moves the block and saves the new order', () => {
  const page = bootPage({ replies: { get_action_blocks: DEFAULTS } });
  const src = rows(page)[2];
  const dst = rows(page)[0];
  const ev = () => ({ preventDefault() {}, dataTransfer: {} });
  src.dispatch('dragstart', ev());
  dst.dispatch('dragover', ev());
  dst.dispatch('drop', ev());
  const order = savedBlocks(page).map((b) => b.id);
  assert.equal(order[0], DEFAULTS[2].id);
  assert.equal(rows(page)[0].dataset.blockId, DEFAULTS[2].id);
});

test('job status signals light up the stack row and the Current Job Stack view', () => {
  const page = bootPage({ replies: { get_action_blocks: DEFAULTS } });
  const target = DEFAULTS.find((b) => b.block_id === 'ATTACH_IMAGE');
  assert.equal((page.handlers.job_action_status || []).length, 1, 'job_action_status is routed exactly once');
  page.emit('job_started', 'job-1', '/img/a.png');
  page.emit('job_action_status', 'job-1', target.id, JSON.stringify({
    job_id: 'job-1', block_id: target.id, block_name: target.name, status: 'running', message: 'FIND input[type=file]',
  }));
  assert.ok(rowFor(page, target.id).classList.contains('ab-status-running'));
  const jobRows = page.anyEl('jobActionStack').querySelectorAll('.job-block-row');
  assert.equal(jobRows.length, 16, 'job view lists every block of the stack');
  const jr = jobRows.find((r) => r.dataset.blockId === target.id);
  assert.ok(jr.classList.contains('jb-running'));
  assert.match(jr.textContent, /FIND input/);
  page.emit('job_action_status', 'job-1', target.id, JSON.stringify({ status: 'success', message: 'Attached', rect: { x: 1, y: 2, width: 3, height: 4 } }));
  assert.ok(rowFor(page, target.id).classList.contains('ab-status-success'));
  page.emit('job_finished', 'job-1', JSON.stringify({ status: 'completed' }));
  assert.ok(page.anyEl('allJobsStack').querySelectorAll('.ab-job-tab').length >= 1, 'all-jobs view shows the job');
  assert.deepEqual(page.errors, []);
});

test('catalog labels (get_builtin_blocks, async reply) word the Block Config rows like the Old App Tune panel', () => {
  const page = bootPage({ replies: { get_action_blocks: DEFAULTS, get_builtin_blocks: CATALOG } });
  const target = DEFAULTS.find((b) => b.block_id === 'SUBMIT');
  const labels = CATALOG.find((c) => c.block_id === 'SUBMIT').labels;
  const row = rowFor(page, target.id);
  row.dispatch('click', { target: row.querySelector('.ab-edit-btn') });
  const rowsInForm = page.anyEl('blockConfigForm').querySelectorAll('.bc-row');
  assert.equal(rowsInForm[0].querySelector('.bc-label').textContent, labels.selector);
  assert.equal(rowsInForm[0].querySelector('.bc-field').dataset.fieldKey, 'selector');
  const keys = rowsInForm.map((r) => r.querySelector('.bc-field').dataset.fieldKey);
  assert.deepEqual(keys.slice(0, Object.keys(labels).length), Object.keys(labels), 'labelled keys come first, in catalog order');
  assert.ok(keys.includes('custom_name') && keys.includes('enabled'), 'generic fields follow');
});

test('custom-block and stack-preset chips load through the async slot path and act on the stack', () => {
  const custom = { name: 'Find X', block: { ...DEFAULTS[0], block_id: 'CUSTOM_FIND', name: 'Find & Click', custom_name: 'Find X' } };
  const preset = { name: 'My stack', blocks: DEFAULTS.slice(0, 5) };
  const page = bootPage({ replies: { get_action_blocks: DEFAULTS, get_custom_blocks: [custom], get_stack_presets: [preset] } });
  const customChips = page.anyEl('customBlockChips').querySelectorAll('.chip');
  const stackChips = page.anyEl('stackPresetChips').querySelectorAll('.chip');
  assert.equal(customChips.length, 1);
  assert.equal(stackChips.length, 1);
  assert.match(stackChips[0].textContent, /My stack/);
  assert.match(stackChips[0].textContent, /5 blocks/);
  customChips[0].dispatch('click', {});
  assert.equal(rows(page).length, 17, 'custom chip appends its block to the stack');
  assert.equal(savedBlocks(page).length, 17);
  stackChips[0].dispatch('click', {});
  assert.equal(rows(page).length, 5, 'stack preset replaces the stack');
  assert.deepEqual(page.errors, []);
});
