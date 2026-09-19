/**
 * test_cdp_store.mjs — tests for cdp-store split (C7/C8)
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';
import vm from 'node:vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const storePath = path.resolve(__dirname, '../../app/ui/web/js/panels/cdp/cdp-store.js');
const code = fs.readFileSync(storePath, 'utf-8');

function loadStore() {
  const dom = new JSDOM('<!DOCTYPE html>');
  const window = dom.window;
  const sandbox = { window, document: window.document, console, String, Array, Object, JSON, Math, Set };
  sandbox.window = window;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.window.CDPStore;
}

const CDPStore = loadStore();

describe('cdp-store', () => {
  test('isDevTab detects devtools', () => {
    assert.equal(CDPStore.isDevTab({ url: 'devtools://foo' }), true);
    assert.equal(CDPStore.isDevTab({ url: 'https://arena.ai' }), false);
    assert.equal(CDPStore.isDevTab({ url: 'chrome://settings' }), true);
    assert.equal(CDPStore.isDevTab(null), true);
  });

  test('getRealTabs filters dev', () => {
    const tabs = [
      { url: 'https://arena.ai', title: 'Arena' },
      { url: 'devtools://x', title: 'DevTools' },
    ];
    const real = CDPStore.getRealTabs(tabs);
    assert.equal(real.length, 1);
    assert.equal(real[0].url, 'https://arena.ai');
  });

  test('_extractUrl extracts http', () => {
    assert.equal(CDPStore._extractUrl('[https://example.com/page]'), 'https://example.com/page');
    assert.equal(CDPStore._extractUrl('(https://example.com)'), 'https://example.com');
    assert.equal(CDPStore._extractUrl('https://example.com'), 'https://example.com');
  });

  test('findBestTabForUrl scores', () => {
    CDPStore.tabs = [
      { id: '1', url: 'https://arena.ai/create', title: 'Create', ws_url: 'ws1' },
      { id: '2', url: 'https://other.com', title: 'Other', ws_url: 'ws2' },
    ];
    const best = CDPStore.findBestTabForUrl('https://arena.ai/create');
    assert.ok(best);
    assert.equal(best.id, '1');
  });

  test('dedupTabs dedupes by id', () => {
    const tabs = [
      { id: 'a', ws_url: 'ws://127.0.0.1/1', url: 'https://a.com' },
      { id: 'a', ws_url: 'ws://localhost/1', url: 'https://a.com' },
    ];
    const deduped = CDPStore.dedupTabs(tabs);
    assert.equal(deduped.length, 1);
    assert.ok(deduped[0].ws_url.includes('127.0.0.1'));
  });
});
