/**
 * Pool row ↔ worker badge identity (I-55, restated for the readable id).
 *
 * Round 1 made the pool row print the FULL 32-hex tab id so it could match the
 * in-page badge. The readable-id round (D-5/D-7) turns that around: every view
 * prints `{email}_{4 digits}` and the hex id stays the identity — it survives in
 * the `title` tooltip and in every action attribute, so a row can still be
 * traced to Chrome's tab listing.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { bootPage } from './page_harness.mjs';

const FULL = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d';  // 32 hex chars, like /json/list `id`
const LABEL = 'marnikus@gmail.com_3045';

const snapWith = (page) => ({ total: 1, steady: 1, busy: 0, cooling: 0, free: 1, pages: [page] });
const worker = (extra = {}) => ({ tab_id: FULL, tab_label: LABEL, worker_no: 3, status: 'steady',
  title: 'Arena', url: 'https://arena.ai/c/1', jobs_completed: 0, ...extra });

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
  test('renders the readable label, never the raw id as the visible text', () => {
    const html = poolHtml(worker());
    assert.ok(html.includes(LABEL), 'the label is the visible id');
    assert.ok(!html.includes(`>${FULL}<`), 'no raw tab id text');
    assert.ok(!html.includes(`>${FULL.slice(0, 12)}<`), 'no truncated id text either');
    assert.ok(html.includes(`title="${FULL}"`), 'the hex id stays reachable');
  });

  test('the worker number leads the label, exactly like the badge', () => {
    assert.match(poolHtml(worker({ worker_no: 7 })), /#7<\/b>\s*marnikus@gmail\.com_3045/);
  });

  test('a row without a label falls back to the short id, never the 12-char slice', () => {
    const html = poolHtml(worker({ tab_label: '' }));
    assert.ok(html.includes(FULL.slice(0, 8)), 'the 8-char short id');
    assert.ok(!html.includes(`>${FULL.slice(0, 12)}<`), 'never the 12-char slice');
  });

  test('the action buttons still carry the hex identity', () => {
    const html = poolHtml(worker());
    assert.ok(html.includes(`data-cool-reset="${FULL}"`), html);
    assert.ok(html.includes(`data-disconnect="${FULL}"`), html);
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
