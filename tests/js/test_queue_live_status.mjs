/**
 * B10 — Image Queue live status. Boots the REAL page (every <script> from
 * index.html, in order) with a fake QWebChannel whose signals can be emitted
 * from the test, then proves the STATUS / ATTEMPTS / OUTPUT / ERROR cells of the
 * queue follow the run:
 *
 *   job_started(job_id, path)          → row shows `processing`, attempts +1
 *   job_finished(job_id, payload)      → row shows completed/failed + output/error
 *   arena_state_updated(json) (250 ms) → rows rebuilt from the pushed state
 *   one panel's restore() throwing     → the queue STILL updates + console/log line
 *   pushed state with images: []       → table cleared, "0/0 images"
 *
 * Regression: the user ran a job, the image was saved, and the Image Queue
 * kept showing `pending / 0 / —` (the full-state push was the only path and a
 * single failure anywhere on it — Python save_state, one sibling panel's
 * restore(), a bad payload — silently froze every row).
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { bootPage as bootHarness } from './page_harness.mjs';

const IMAGES = [
  { id: 'img-a', relative_path: 'a.png', absolute_path: 'F:\\Stocks 2026\\icons\\a.png', filename: 'a.png', status: 'pending', selected: true, assigned_url: '', attempts: 0, output_path: '', error: '', size: 10 },
  { id: 'img-b', relative_path: 'b.png', absolute_path: 'F:\\Stocks 2026\\icons\\b.png', filename: 'b.png', status: 'pending', selected: false, assigned_url: '', attempts: 0, output_path: '', error: '', size: 10 },
  { id: 'img-c', relative_path: 'c.png', absolute_path: 'F:\\Stocks 2026\\icons\\c.png', filename: 'c.png', status: 'pending', selected: false, assigned_url: '', attempts: 0, output_path: '', error: '', size: 10 },
];

function stateJson(images) {
  return JSON.stringify({
    version: 1, urls: [{ id: 'u1', url: 'https://arena.ai', enabled: true, status: 'unchecked', last_error: '', tab_id: '' }],
    images, folder: { root_path: 'F:\\Stocks 2026\\icons', supported_types: ['.png'], ignore_ai_suffix: true },
    prompt: { template: 'p' }, settings: { output: {}, highlight: {}, timeouts: {}, browser: {} },
    progress: { total: images.length, pending: 1, selected: 1, processing: 0, completed: 0, failed: 0, skipped: 0 },
    run_state: 'idle', jobs: [],
  });
}

function bootPage(images = IMAGES) {
  const page = bootHarness({
    replies: { get_arena_state: () => stateJson(JSON.parse(JSON.stringify(images))) },
    prepare: (anyEl) => { anyEl('queueTableBody').tagName = 'TBODY'; },
  });
  return { ...page, tbody: page.anyEl('queueTableBody') };
}

const rows = (tbody) => tbody.children;
const rowOf = (tbody, id) => rows(tbody).find((tr) => tr.dataset.imgId === id);
const cellText = (html, cls) => { const m = html.match(new RegExp(`<span class="status-badge ${cls}[^"]*">([^<]*)</span>`)); return m ? m[1] : null; };

describe('B10 — Image Queue follows the run (whole page, real scripts)', () => {
  test('initial load renders every row as pending with a data-img-id handle', () => {
    const { tbody } = bootPage();
    assert.equal(rows(tbody).length, 3);
    assert.deepEqual(rows(tbody).map((tr) => tr.dataset.imgId), ['img-a', 'img-b', 'img-c']);
    assert.ok(rowOf(tbody, 'img-a').innerHTML.includes('s-pending'));
  });

  test('job_started → the row flips to processing and counts the attempt (Windows path, any case/slash)', () => {
    const { tbody, emit } = bootPage();
    emit('job_started', 'job-1', 'f:/stocks 2026/icons/A.PNG');
    const html = rowOf(tbody, 'img-a').innerHTML;
    assert.ok(html.includes('status-badge s-processing'), html);
    assert.ok(/<td style="font-size:10px;">1<\/td>/.test(html), 'attempts cell must read 1');
    assert.ok(rowOf(tbody, 'img-b').innerHTML.includes('s-pending'), 'other rows untouched');
  });

  test('job_finished(completed) → completed + output basename; job_finished(failed) → failed + error text', () => {
    const { tbody, emit } = bootPage();
    emit('job_started', 'job-1', 'F:\\Stocks 2026\\icons\\a.png');
    emit('job_finished', 'job-1', JSON.stringify({ status: 'completed', message: 'Saved', output_path: 'F:\\Stocks 2026\\icons\\a_AI.png', image_id: 'img-a', attempts: 1, error: '' }));
    let html = rowOf(tbody, 'img-a').innerHTML;
    assert.ok(html.includes('status-badge s-completed'), html);
    assert.ok(html.includes('>a_AI.png</span>'), 'OUTPUT cell shows the saved file');

    // second image fails — located by image_id even without a job_started
    emit('job_finished', 'job-2', JSON.stringify({ status: 'failed', message: 'Find & Click failed for button', output_path: '', image_id: 'img-b', attempts: 2, error: 'Find & Click failed for button' }));
    html = rowOf(tbody, 'img-b').innerHTML;
    assert.ok(html.includes('status-badge s-failed'), html);
    assert.ok(html.includes('Find &amp; Click failed for button'), 'ERROR cell shows the message');
    assert.ok(/<td style="font-size:10px;">2<\/td>/.test(html), 'attempts from the payload');
  });

  test('arena_state_updated (debounced 250 ms) rebuilds the rows from the pushed state', () => {
    const { tbody, emit, flushTimers, sb } = bootPage();
    flushTimers();
    const pushed = JSON.parse(JSON.stringify(IMAGES));
    pushed[0] = { ...pushed[0], status: 'completed', attempts: 1, output_path: 'F:\\Stocks 2026\\icons\\a_AI.png' };
    pushed[2] = { ...pushed[2], status: 'failed', attempts: 3, error: 'boom' };
    emit('arena_state_updated', stateJson(pushed));
    assert.ok(rowOf(tbody, 'img-a').innerHTML.includes('s-pending'), 'not applied before the debounce fires');
    flushTimers();
    assert.ok(rowOf(tbody, 'img-a').innerHTML.includes('s-completed'));
    assert.ok(rowOf(tbody, 'img-a').innerHTML.includes('>a_AI.png</span>'));
    assert.ok(rowOf(tbody, 'img-c').innerHTML.includes('s-failed'));
    assert.ok(rowOf(tbody, 'img-c').innerHTML.includes('>boom</td>'));
    assert.equal(vm.runInContext('App.state.images[0].status', sb), 'completed');
  });

  test('a sibling panel throwing inside restore() no longer blocks the queue — and it is reported', () => {
    const { tbody, emit, flushTimers, sb, errors, logs } = bootPage();
    flushTimers();
    vm.runInContext("UrlList.restore = function () { throw new Error('url panel exploded'); };", sb);
    const pushed = JSON.parse(JSON.stringify(IMAGES));
    pushed[0] = { ...pushed[0], status: 'processing', attempts: 1 };
    emit('arena_state_updated', stateJson(pushed));
    flushTimers();
    assert.ok(rowOf(tbody, 'img-a').innerHTML.includes('s-processing'), 'queue updated despite UrlList failure');
    assert.ok(errors.some((e) => e.includes('UrlList') && e.includes('url panel exploded')), errors.join('\n'));
    assert.ok(logs.some((l) => l.startsWith('error: UI state sync: UrlList failed')), logs.join('\n'));
    // reported once, not on every push
    emit('arena_state_updated', stateJson(pushed));
    flushTimers();
    assert.equal(logs.filter((l) => l.includes('UI state sync: UrlList')).length, 1);
  });

  test('a pushed state with images: [] clears the table (0/0 images)', () => {
    const { tbody, emit, flushTimers, anyEl } = bootPage();
    flushTimers();
    emit('arena_state_updated', stateJson([]));
    flushTimers();
    assert.equal(rows(tbody).length, 0);
    assert.equal(anyEl('queueCount').textContent, '0/0 images');
  });

  test('a malformed push is reported instead of swallowed; the next good push still applies', () => {
    const { tbody, emit, flushTimers, logs } = bootPage();
    flushTimers();
    emit('arena_state_updated', '{"images": [NaN]}');
    flushTimers();
    assert.ok(logs.some((l) => l.includes('UI state sync: state payload failed')), logs.join('\n'));
    const pushed = JSON.parse(JSON.stringify(IMAGES));
    pushed[1] = { ...pushed[1], status: 'completed', attempts: 1 };
    emit('arena_state_updated', stateJson(pushed));
    flushTimers();
    assert.ok(rowOf(tbody, 'img-b').innerHTML.includes('s-completed'));
  });

  test('job signals for an unknown image are ignored without throwing', () => {
    const { tbody, emit, errors } = bootPage();
    emit('job_started', 'job-x', 'F:\\elsewhere\\zzz.png');
    emit('job_finished', 'job-x', '{"status":"completed"}');
    emit('job_finished', 'job-y', 'not json');
    assert.equal(rows(tbody).filter((tr) => tr.innerHTML.includes('s-pending')).length, 3);
    assert.deepEqual(errors.filter((e) => e.includes('ImageQueue')), []);
  });
});
