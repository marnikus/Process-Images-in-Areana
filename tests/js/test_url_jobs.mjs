/**
 * Tier A — Logic tests for url-list.js per-tab job line (Node.js, no browser).
 * The job line shows which image a tab is processing; the Stop button
 * aborts that tab's job. Pure lookup covered here; DOM wiring is thin.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const panelPath = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list.js');
const panelCode = fs.readFileSync(panelPath, 'utf-8');

function loadUrlList() {
  const sandbox = { console, JSON, Math, Object, Array, Map, Set, Error, URL,
    document: undefined };
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(panelCode + '\nthis.__U = UrlList;', sandbox, { filename: 'url-list.js' });
  return sandbox.__U;
}

const pages = [
  { tab_id: 'aaa', current_image: '03-c.jpeg' },
  { tab_id: 'bbb', current_image: '' },
  { tab_id: 'ccc' },
];

describe('jobLineForTab', () => {
  test('shows the running image for the linked tab', () => {
    const U = loadUrlList();
    assert.equal(U.jobLineForTab(pages, 'aaa'), '▶ 03-c.jpeg');
  });

  test('empty when idle, unknown, or unlinked', () => {
    const U = loadUrlList();
    assert.equal(U.jobLineForTab(pages, 'bbb'), '');
    assert.equal(U.jobLineForTab(pages, 'ccc'), '');
    assert.equal(U.jobLineForTab(pages, 'ghost'), '');
    assert.equal(U.jobLineForTab(pages, ''), '');
    assert.equal(U.jobLineForTab(pages, null), '');
    assert.equal(U.jobLineForTab([], 'aaa'), '');
    assert.equal(U.jobLineForTab(null, 'aaa'), '');
  });

  test('never renders another tab image (isolation)', () => {
    const U = loadUrlList();
    assert.ok(!U.jobLineForTab(pages, 'bbb').includes('03-c.jpeg'));
    assert.ok(!U.jobLineForTab(pages, 'ghost').includes('03-c.jpeg'));
  });
});
