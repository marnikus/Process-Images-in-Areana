/**
 * Pool row ↔ worker badge identity (I-55): one tab, one id string.
 *
 * The in-page badge (`app/browser/worker_badge.py`) prints `#n` + the FULL tab
 * id, while the pool table's Tab ID cell printed `tab_id.slice(0,12)` — a real
 * Chrome target id is 32 hex chars, so the two could never read the same (user
 * report: "the tabID in the POOL does not match the ID shown in the badge").
 * The cell renders the full id now (title keeps the identical string), and the
 * URL row tooltip does the same for its linked tab.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { bootPage } from './page_harness.mjs';

const FULL = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d';  // 32 hex chars, like /json/list `id`

const snapWith = (page) => ({ total: 1, steady: 1, busy: 0, cooling: 0, free: 1, pages: [page] });
const worker = (extra = {}) => ({ tab_id: FULL, worker_no: 3, status: 'steady', title: 'Arena',
  url: 'https://arena.ai/c/1', jobs_completed: 0, ...extra });

/* fake_dom stores one innerHTML per element: rows are CHILDREN of the tbody. */
function rowsHtml(el) {
  return [...el.children].map((c) => c.innerHTML || '').join('\n');
}

function poolHtml(page) {
  const h = bootPage();
  h.emit('page_pool_updated', JSON.stringify(snapWith(page)));
  return rowsHtml(h.anyEl('poolTableBody'));
}

describe('pool Tab ID cell (I-55 parity with the worker badge)', () => {
  test('renders the full 32-char tab id, never the 12-char slice', () => {
    const html = poolHtml(worker());
    assert.ok(html.includes(FULL), 'full tab id in the pool row');
    assert.ok(!html.includes(`>${FULL.slice(0, 12)}<`), 'no truncated id text');
  });

  test('the worker number leads the id, exactly like the badge', () => {
    assert.match(poolHtml(worker({ worker_no: 7 })), /#7<\/b>\s*1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d/);
  });

  test('a legacy row without worker_no still shows the full id', () => {
    assert.ok(poolHtml(worker({ worker_no: 0 })).includes(`#0</b> ${FULL}`));
  });

  test('the URL row tooltip carries the same full id for its linked tab', () => {
    const h = bootPage();
    h.emit('arena_state_updated', JSON.stringify({ urls: [{ id: 'u1', url: 'https://arena.ai/c/1',
      enabled: true, status: 'ready', tab_id: FULL }], images: [] }));
    h.flushTimers();
    const html = rowsHtml(h.anyEl('urlTableBody'));
    assert.ok(html.includes('linked tab ' + FULL), 'tooltip shows the full id');
    assert.ok(!html.includes(FULL.slice(0, 8) + '&quot;'), 'no 8-char slice in the tooltip');
  });
});
