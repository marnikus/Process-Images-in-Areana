import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { CDPStore } from '../../app/ui/web/js/panels/cdp/cdp-store.esm.mjs';

describe('cdp-store-esm', () => {
  test('isDevTab', () => {
    assert.equal(CDPStore.isDevTab({ url: 'devtools://foo' }), true);
    assert.equal(CDPStore.isDevTab({ url: 'https://arena.ai' }), false);
    assert.equal(CDPStore.isDevTab(null), true);
  });
  test('getRealTabs', () => {
    const tabs = [{ url: 'https://arena.ai' }, { url: 'devtools://x' }];
    assert.equal(CDPStore.getRealTabs(tabs).length, 1);
  });
  test('_extractUrl', () => {
    assert.equal(CDPStore._extractUrl('[https://example.com/page]'), 'https://example.com/page');
    assert.equal(CDPStore._extractUrl('https://example.com'), 'https://example.com');
  });
  test('findBestTabForUrl', () => {
    CDPStore.tabs = [
      { id: '1', url: 'https://arena.ai/create', ws_url: 'ws1' },
      { id: '2', url: 'https://other.com', ws_url: 'ws2' },
    ];
    const best = CDPStore.findBestTabForUrl('https://arena.ai/create');
    assert.ok(best);
    assert.equal(best.id, '1');
  });
  test('dedupTabs', () => {
    const tabs = [
      { id: 'a', ws_url: 'ws://127.0.0.1/1', url: 'https://a.com' },
      { id: 'a', ws_url: 'ws://localhost/1', url: 'https://a.com' },
    ];
    const deduped = CDPStore.dedupTabs(tabs);
    assert.equal(deduped.length, 1);
  });
});
