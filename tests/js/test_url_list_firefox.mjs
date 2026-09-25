/**
 * Firefox rows in the URL list (2026-09-25, design D8).
 *
 * Owner brief §2.3: every row names its connection method — Chrome `cdp`,
 * Firefox `uivision` — with a browser icon, and the Tab cell carries the
 * same alias label as every other view (D-7). No new column: the cells the
 * template already declares are filled with the new truth.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';
import { bootPage } from './page_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const FF_ID = '9THrgpBc.Profile1_tab1';
const FF_URL = 'https://arena.ai/c/7';

function worker(extra = {}) {
  return {
    tab_id: FF_ID, tab_label: 'aka_0042', worker_no: 4, status: 'steady',
    title: 'Arena', url: FF_URL, jobs_completed: 0, cooldown_remaining: 0,
    cooldown_total: 0, pending_penalty: 0, ...extra,
  };
}

function tabCell(page) {
  const h = bootPage();
  const tr = new El('tr');
  const cell = new El('td');
  cell.className = 'url-tab-cell';
  tr.appendChild(cell);
  h.run('UrlListCells').fillTabCell(tr, page);
  return tr.querySelector('.url-tab-cell').innerHTML;
}

describe('URL list — browser identity', () => {
  test('a Firefox row shows the fox and its alias label', () => {
    const html = tabCell(worker({ browser: 'firefox' }));
    assert.ok(html.includes('🦊'), html);
    assert.ok(html.includes('aka_0042'), html);
  });

  test('a Chrome row shows the globe — same label mechanics', () => {
    const html = tabCell(worker({ tab_id: 'c1', browser: 'chrome', tab_label: 'you_1234' }));
    assert.ok(html.includes('🌐'), html);
    assert.ok(html.includes('you_1234'), html);
  });

  test('a pooled tab with no browser field degrades to the globe (legacy pages)', () => {
    const html = tabCell(worker({ tab_id: 'c1' }));
    assert.ok(html.includes('🌐'), html);
  });

  test('not-pooled rows keep their dash — never a phantom browser', () => {
    const html = tabCell(null);
    assert.ok(html.includes('Tab not in pool'), html);
    assert.ok(!html.includes('🦊') && !html.includes('🌐'), html);
  });
});

describe('URL list — Conn cell', () => {
  function connHtml(u, store) {
    const h = bootPage();
    return h.run('CDPRender')._connCellHtml(u, store);
  }

  const noMatchStore = { findBestTabForUrl: () => null, tabs: [] };

  test('a row bound to a Firefox pool page reads uivision, not "no tab"', () => {
    const h = bootPage();
    h.emit('page_pool_updated', JSON.stringify({
      total: 1, steady: 1, busy: 0, cooling: 0, free: 1, pages: [worker({ browser: 'firefox' })],
    }));
    const html = h.run('CDPRender')._connCellHtml(
      { id: 'u1', url: FF_URL, tab_id: FF_ID }, noMatchStore);
    assert.match(html, /uivision/);
    assert.match(html, /🦊/);
  });

  test('a Chrome-matched row keeps its match chip and names cdp', () => {
    const store = {
      tabs: [{ url: FF_URL }],
      findBestTabForUrl: () => ({ kind: 'exact', score: 500, title: 'Arena', url: FF_URL }),
    };
    const html = connHtml({ id: 'u2', url: FF_URL, tab_id: '' }, store);
    assert.match(html, /cdp/);
    assert.match(html, /exact/);
    assert.ok(!html.includes('uivision'), html);
  });
});
