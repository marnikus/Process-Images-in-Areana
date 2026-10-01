/**
 * The Image Queue's display lane may never fail silently (owner report 2026-09-30:
 * "folder picker display nothing" — picker alive with "55 images 6 pending", list gone).
 *
 * Boots the REAL page (every <script> from index.html, in order) and proves:
 *   a missing queue module (merged-build shape: split facade without its image-queue/*
 *   files) is reported ONCE by kind + file name — never a raw TypeError per push;
 *   a module that appears later renders on the next push without a restart (RULE 24);
 *   a queue table missing from the DOM is reported, not silently skipped.
 * Before this fix the lane threw `Cannot read properties of undefined (reading
 * 'restore')` on every push and the table stayed empty forever.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { bootPage } from './page_harness.mjs';

const IMAGES = [
  { id: 'img-a', relative_path: 'a.png', absolute_path: 'F:\\Stocks 2026\\icons testing\\single\\a.png', filename: 'a.png', status: 'pending', selected: true, assigned_url: '', attempts: 0, output_path: '', error: '', size: 10 },
  { id: 'img-b', relative_path: 'b.png', absolute_path: 'F:\\Stocks 2026\\icons testing\\single\\b.png', filename: 'b.png', status: 'completed', selected: false, assigned_url: '', attempts: 1, output_path: 'F:\\Stocks 2026\\icons testing\\single\\a_AI.png', error: '', size: 10 },
  { id: 'img-c', relative_path: 'c.png', absolute_path: 'F:\\Stocks 2026\\icons testing\\single\\c.png', filename: 'c.png', status: 'pending', selected: false, assigned_url: '', attempts: 0, output_path: '', error: '', size: 10 },
];

function stateJson(images) {
  return JSON.stringify({
    version: 1, urls: [], images,
    folder: { root_path: 'F:\\Stocks 2026\\icons testing\\single', supported_types: ['.png'], ignore_ai_suffix: true },
    prompt: { template: 'p' }, settings: { output: {}, highlight: {}, timeouts: {}, browser: {} },
    progress: { total: images.length, pending: 2 }, run_state: 'idle', jobs: [],
  });
}

function bootQueuePage() {
  return bootPage({
    replies: { get_arena_state: () => stateJson(IMAGES) },
    prepare: (anyEl) => { anyEl('queueTableBody').tagName = 'TBODY'; },
  });
}

const rowCount = (page) => page.anyEl('queueTableBody').children.length;
const linesAbout = (page, needle) => page.logs.filter((l) => l.includes(needle));

/* The merged-build damage in one line: the facade booted without its modules
   (its init() cache stayed empty) and the file never registered on window. */
const breakStore = (page) => page.run('window.ImageQueue._store = null; delete window.ImageQueueStore;');

describe('the Image Queue lane never fails silently (folder-picker-displays-nothing bug)', () => {
  test('a missing queue module is reported by name — never a raw TypeError', () => {
    const page = bootQueuePage();
    breakStore(page);
    page.emit('arena_state_updated', stateJson(IMAGES));
    page.flushTimers();
    assert.equal(rowCount(page), 0);                       // no store → no rows, honestly
    const about = linesAbout(page, 'ImageQueueStore');
    assert.equal(about.length, 1, `one report, got: ${JSON.stringify(page.logs)}`);
    assert.ok(about[0].includes('image-queue/store.js'), `the report names the file: ${about[0]}`);
    assert.ok(!page.logs.join('|').includes('Cannot read properties'), 'no raw TypeError text');
    assert.ok(!page.errors.join('|').includes('reading \'restore\''), 'no undefined-property crash');
  });

  test('the same missing module is reported once, never once per push', () => {
    const page = bootQueuePage();
    breakStore(page);
    page.emit('arena_state_updated', stateJson(IMAGES));
    page.flushTimers();
    page.emit('arena_state_updated', stateJson(IMAGES));
    page.flushTimers();
    assert.equal(linesAbout(page, 'ImageQueueStore').length, 1);
  });

  test('a module that appears later renders on the next push — no restart (RULE 24)', () => {
    const page = bootQueuePage();
    breakStore(page);
    page.emit('arena_state_updated', stateJson(IMAGES));
    page.flushTimers();
    assert.equal(rowCount(page), 0);
    page.run('window.ImageQueueStore = ImageQueueStore');   // the repaired/late-loaded file
    page.emit('arena_state_updated', stateJson(IMAGES));
    page.flushTimers();
    assert.equal(rowCount(page), 3);
    assert.deepEqual(
      page.anyEl('queueTableBody').children.map((tr) => tr.dataset.imgId),
      ['img-a', 'img-b', 'img-c']);
  });

  test('a queue table that is not in the DOM is reported, not silently skipped', () => {
    const page = bootQueuePage();
    page.run('document.getElementById = (id) => (id === \'queueTableBody\' ? null : null)');
    page.emit('arena_state_updated', stateJson(IMAGES));
    page.flushTimers();
    const about = linesAbout(page, 'queueTableBody');
    assert.equal(about.length, 1, `the missing table is named: ${JSON.stringify(page.logs)}`);
    page.emit('arena_state_updated', stateJson(IMAGES));
    page.flushTimers();
    assert.equal(linesAbout(page, 'queueTableBody').length, 1, 'reported once, not per push');
  });
});
