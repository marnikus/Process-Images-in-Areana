import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { UrlListStore } from '../../app/ui/web/js/panels/url-list/store.esm.mjs';
import { UrlListMatching } from '../../app/ui/web/js/panels/url-list/matching.esm.mjs';

describe('url-list-store-esm', () => {
  test('esc', () => {
    assert.equal(UrlListStore.esc('<a>'), '&lt;a&gt;');
  });
  test('extractUrl', () => {
    assert.equal(UrlListStore.extractUrl('[https://example.com]'), 'https://example.com');
    assert.equal(UrlListStore.extractUrl('https://example.com'), 'https://example.com');
  });
  test('shouldDebounce', () => {
    UrlListStore._lastConnectUrl = '';
    UrlListStore._lastConnectTs = 0;
    assert.equal(UrlListStore.shouldDebounce('https://a.com'), false);
    assert.equal(UrlListStore.shouldDebounce('https://a.com'), true);
  });
});

describe('url-list-matching-esm', () => {
  test('scorePoolPage', () => {
    assert.equal(UrlListMatching.scorePoolPage('https://a.com', 'https://a.com'), 500);
    assert.equal(UrlListMatching.scorePoolPage('https://a.com/page', 'https://a.com'), 300);
    assert.equal(UrlListMatching.scorePoolPage('https://a.com', 'https://b.com'), 0);
  });
  test('jobLineForTab', () => {
    const pages = [{ tab_id: 't1', current_image: 'img.png' }];
    assert.equal(UrlListMatching.jobLineForTab(pages, 't1'), '▶ img.png');
    assert.equal(UrlListMatching.jobLineForTab(pages, 't2'), '');
  });
  test('assignPoolPages sticky', () => {
    const rows = [{ dataset: { tabId: 't1', url: 'https://a.com' } }, { dataset: { tabId: '', url: 'https://a.com' } }];
    const pages = [{ tab_id: 't1', url: 'https://a.com' }, { tab_id: 't2', url: 'https://a.com' }];
    const claimed = UrlListMatching.assignPoolPages(rows, pages);
    assert.ok(claimed.has(0));
    assert.equal(claimed.get(0), 0);
  });
});
