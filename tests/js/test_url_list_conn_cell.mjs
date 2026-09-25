/**
 * Conn cell + Tab icon — one row states its browser honestly (D-10, owner §2.3).
 *
 * A pooled Firefox row reads `🦊 uivision`, a pooled Chrome row `🌐 cdp`, and
 * both lock their cell against chrome's own matcher repaint; an unlinked row
 * keeps the matcher's answer. The Tab cell carries 🦊/🌐 and the profile name
 * in its tooltip (the profile IS the logged-in account for the uivision lane).
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { El } from './fake_dom.mjs';
import { bootPage } from './page_harness.mjs';

const FF = { tab_id: '9THrgpBc.Profile1_tab6', browser: 'firefox', profile: 'Profile1',
  url: 'https://chatgpt.com/', title: 'ChatGPT' };
const CHROME = { tab_id: '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d', browser: 'chrome',
  url: 'https://arena.ai/c/1' };
const LEGACY = { tab_id: '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d' };  // pre-D-4 snapshot: no browser

function bootWithRows(count = 1) {
  const h = bootPage();
  const tbody = h.anyEl('urlTableBody');
  const rows = Array.from({ length: count }, () => {
    const tr = new El('tr');
    const conn = new El('td'); conn.className = 'url-conn-status';
    const tab = new El('td'); tab.className = 'url-tab-cell';
    tr.appendChild(conn); tr.appendChild(tab);
    tbody.appendChild(tr);
    return tr;
  });
  const conn = h.run('window.UrlListConn');
  assert.ok(conn, 'conn.js loaded from index.html');
  return { h, rows, conn, cells: h.run('window.UrlListCells') };
}

describe('URL list conn cell (D-10)', () => {
  test('a pooled firefox row reads 🦊 uivision and locks its cell', () => {
    const { rows, conn } = bootWithRows();
    conn.fillConnCell(rows[0], FF);
    assert.match(rows[0].querySelector('.url-conn-status').innerHTML, /🦊 uivision/);
    assert.equal(rows[0].dataset.connlocked, '1');
  });

  test('a pooled chrome row reads 🌐 cdp', () => {
    const { rows, conn } = bootWithRows();
    conn.fillConnCell(rows[0], CHROME);
    assert.match(rows[0].querySelector('.url-conn-status').innerHTML, /🌐 cdp/);
    assert.equal(rows[0].dataset.connlocked, '1');
  });

  test('chrome matcher repaint skips a locked firefox row', () => {
    const { h, rows, conn } = bootWithRows();
    conn.fillConnCell(rows[0], FF);
    h.run(`window.App = { state: { urls: [{ id: 'u1', url: 'https://chatgpt.com/' }] } }`);
    h.run('CDPPanel.updateUrlRowsConnection()');
    assert.match(rows[0].querySelector('.url-conn-status').innerHTML, /🦊 uivision/,
      'the locked firefox row survives chrome\'s own repaint');
  });

  test('chrome matcher still paints an unlinked row', () => {
    const { h, rows } = bootWithRows();
    h.run(`window.App = { state: { urls: [{ id: 'u2', url: 'https://arena.ai/c/1' }] } }`);
    h.run('CDPPanel.updateUrlRowsConnection()');
    assert.match(rows[0].querySelector('.url-conn-status').innerHTML, /no chrome/,
      'an unlocked row is still chrome\'s matcher to paint');
  });

  test('dropping the pool page unlocks the row again', () => {
    const { rows, conn } = bootWithRows();
    conn.fillConnCell(rows[0], FF);
    assert.equal(rows[0].dataset.connlocked, '1');
    conn.fillConnCell(rows[0], null);
    assert.ok(!('connlocked' in rows[0].dataset), 'unlinked rows return to the matcher');
  });

  test('repaintChrome survives a page without App state', () => {
    const { h, conn } = bootWithRows();
    const before = h.errors.length;
    conn.repaintChrome();
    assert.equal(h.errors.length, before, 'no console.error from the guarded repaint');
  });
});

describe('URL list tab cell icon (D-10)', () => {
  test('firefox rows show 🦊 and the profile in the tooltip', () => {
    const { rows, cells } = bootWithRows();
    cells.fillTabCell(rows[0], FF);
    const html = rows[0].querySelector('.url-tab-cell').innerHTML;
    assert.ok(html.startsWith('🦊 '), html);
    assert.ok(html.includes('title="9THrgpBc.Profile1_tab6 — Profile1"'), html);
  });

  test('chrome rows show 🌐; legacy snapshots without a browser stay text-only', () => {
    const { rows, cells } = bootWithRows(2);
    cells.fillTabCell(rows[0], CHROME);
    cells.fillTabCell(rows[1], LEGACY);
    assert.ok(rows[0].querySelector('.url-tab-cell').innerHTML.startsWith('🌐 '));
    assert.ok(rows[1].querySelector('.url-tab-cell').innerHTML.startsWith('<span'),
      'an old snapshot gains no icon');
  });
});
