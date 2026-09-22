/**
 * Browser-aware CDP labels (Firefox routing round).
 *
 * The tab list now mixes Chrome, Firefox and Edge tabs in one dropdown: every
 * row must be tagged with its browser, and the connection status lines must
 * NAME the browser instead of blaming Chrome for a Firefox failure.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { bootPage } from './page_harness.mjs';

const TABS = [
  { id: 'AAA', title: 'Arena', url: 'https://arena.ai/c/1',
    ws_url: 'ws://127.0.0.1:9222/devtools/page/AAA', browser: 'chrome' },
  { id: '11', title: 'Arena', url: 'https://arena.ai/c/2',
    ws_url: 'rdp://127.0.0.1:9223#11', browser: 'firefox' },
];

function booted(payload = TABS) {
  const h = bootPage();
  h.sb.CDPPanel.onTabsReceived(JSON.stringify(payload));
  return h;
}

const options = (h) => h.anyEl('tabSelect').children.map((o) => o.textContent);

describe('browser-aware CDP labels', () => {
  test('every tab row is tagged with its browser', () => {
    const rows = options(booted());
    assert.equal(rows.length, 2);
    assert.ok(rows.some((r) => r.startsWith('[Chrome] ')), `chrome tagged: ${rows}`);
    assert.ok(rows.some((r) => r.startsWith('[Firefox] ')), `firefox tagged: ${rows}`);
  });

  test('a tab without a browser tag renders untagged, never "[undefined]"', () => {
    const legacy = { id: 'X', title: 'Old', url: 'https://arena.ai/c/9',
      ws_url: 'ws://127.0.0.1:9222/devtools/page/X' };
    const rows = options(booted([legacy, ...TABS]));
    assert.equal(rows.length, 3);
    for (const r of rows) assert.ok(!r.includes('undefined'), r);
    assert.ok(rows.some((r) => !r.startsWith('[')), 'the legacy row has no tag');
  });

  test('connection status names the selected tab browser', () => {
    const h = booted();
    h.sb.CDPStore.selectedWs = 'rdp://127.0.0.1:9223#11';
    h.sb.CDPPanel.onConnectionStatus('error');
    assert.ok(h.logs.some((l) => l.includes('❌ Firefox connection error')), `logs: ${h.logs}`);
    assert.ok(!h.logs.some((l) => /Chrome/.test(l)), `never Chrome's fault: ${h.logs}`);
  });

  test('an unknown selection falls back to the neutral status text', () => {
    const h = booted();
    h.sb.CDPStore.selectedWs = '';
    h.sb.CDPStore._lastAutoConnectWs = '';
    h.sb.CDPPanel.onConnectionStatus('connected');
    assert.ok(h.logs.some((l) => l.includes('✅ connected')), `logs: ${h.logs}`);
  });
});
