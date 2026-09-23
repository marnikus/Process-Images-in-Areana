/**
 * Job count is display-only in the web page (2026-09-21).
 *
 * The counter the pool table, the URL list and the Live Debug window show is a
 * number — no view may promise that the number decides where the next job goes,
 * because that routing concept (I-28 load balancing) is gone: the pool and the
 * URL-list link now pick by pool order only.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PANELS = path.resolve(__dirname, '../../app/ui/web/js/panels');
const read = (rel) => fs.readFileSync(path.join(PANELS, rel), 'utf-8');

const MODULES = ['page-pool/render.js', 'page-pool/store.js', 'page-pool/cells.js',
  'url-list/render.js', 'url-list/matching.js', 'url-list/cells.js',
  'live-debug/render.js', 'live-debug/store.js'];

/** The pool table row for one page, rendered by the real module. */
function poolRow(page) {
  const sandbox = { console, JSON, Object, Array, Math, Date, Number, String, parseInt, isNaN,
    setTimeout: () => 1, setInterval: () => 1, document: { getElementById: () => null } };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  for (const f of ['core/tab-label.js', 'panels/page-pool/store.js', 'panels/page-pool/cells.js',
    'panels/page-pool/render.js']) {
    vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../app/ui/web/js', f), 'utf-8'), sandbox, { filename: f });
  }
  return vm.runInContext('PagePoolRender._rowHtml(' + JSON.stringify(page) + ')', sandbox);
}

const worker = (extra = {}) => ({
  tab_id: 'ABCDEF0123456789XYZ', tab_label: 'm@gmail.com_0007', worker_no: 3,
  title: 'T', url: 'https://arena.ai', status: 'steady', is_connected: true,
  cooldown_remaining: 0, cooldown_total: 0, pending_penalty: 0, current_job_id: '',
  jobs_completed: 7, ...extra,
});

describe('the counter is a number in every view', () => {
  test('the pool row shows the count with a display-only tooltip', () => {
    const row = poolRow(worker());
    assert.match(row, /<td title="Jobs completed">7<\/td>/, row);
    assert.ok(!/lowest count|next job/i.test(row), 'no routing promise in the pool row');
  });

  test('a page without the field still renders 0, never "undefined"', () => {
    const row = poolRow(worker({ jobs_completed: undefined }));
    assert.match(row, /<td title="Jobs completed">0<\/td>/);
  });

  test('the URL-list Jobs cell is the same plain number', () => {
    const text = read('url-list/render.js');
    assert.match(text, /title="Jobs completed"/);
    assert.ok(!/lowest|fewest|balance/i.test(text), 'no routing promise in the URL list');
  });

  test('the Live Debug line shows the count without claiming it routes', () => {
    const text = read('live-debug/render.js') + read('live-debug/store.js');
    assert.match(text, /jobs/);
    assert.ok(!/lowest|fewest|balance/i.test(text));
  });
});

describe('no JS module routes by the count', () => {
  test('no module promises count-based routing any more', () => {
    for (const rel of MODULES) {
      const text = read(rel);
      assert.ok(!/lowest count|fewest (completed )?jobs|load balanc/i.test(text),
        `${rel} still describes count-based routing`);
    }
  });

  test('page-pool/render.js no longer carries the old promise text', () => {
    assert.ok(!read('page-pool/render.js').includes('next job goes to the free tab'));
  });
});
