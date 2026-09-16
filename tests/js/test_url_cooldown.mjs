/**
 * Tier A — Logic tests for url-list.js cooldown matching (Node.js, no browser).
 * Regression cover for the isolation fixes: greedy 1:1 assignment must never
 * render one tab's timer on another row; strict fallback takes unclaimed pages
 * with exact/prefix match only.
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

const UrlList = loadUrlList();
const row = (url) => ({ dataset: { url } });

describe('scorePoolPage', () => {
  test('exact match scores 500', () => {
    assert.equal(UrlList.scorePoolPage('https://arena.ai/x?m=1', 'https://arena.ai/x?m=1'), 500);
  });
  test('prefix either way scores 300', () => {
    assert.equal(UrlList.scorePoolPage('https://arena.ai/x?m=1', 'https://arena.ai/x'), 300);
    assert.equal(UrlList.scorePoolPage('https://arena.ai/x', 'https://arena.ai/x?m=1'), 300);
  });
  test('same host scores 200', () => {
    assert.equal(UrlList.scorePoolPage('https://arena.ai/aaa', 'https://arena.ai/bbb'), 200);
  });
  test('empty or unrelated scores 0', () => {
    assert.equal(UrlList.scorePoolPage('https://arena.ai/x', ''), 0);
    assert.equal(UrlList.scorePoolPage('', 'https://arena.ai/x'), 0);
    assert.equal(UrlList.scorePoolPage('https://a.example/', 'https://b.example/'), 0);
  });
});

describe('assignPoolPages greedy 1:1', () => {
  const rows = [row('https://arena.ai/x?m=a'), row('https://arena.ai/x?m=b')];

  test('exact urls attribute correctly', () => {
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/x?m=a' },
                   { tab_id: 'B', url: 'https://arena.ai/x?m=b' }];
    const claimed = UrlList.assignPoolPages(rows, pages);
    assert.equal(claimed.get(0), 0);
    assert.equal(claimed.get(1), 1);
  });

  test('bare-url ties split 1:1 (cooling tab stays visible)', () => {
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/x' },
                   { tab_id: 'B', url: 'https://arena.ai/x' }];
    const claimed = UrlList.assignPoolPages(rows, pages);
    assert.equal(claimed.size, 2);
    assert.notEqual(claimed.get(0), claimed.get(1));
  });

  test('single page claims first row only', () => {
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/x?m=a' }];
    const claimed = UrlList.assignPoolPages(rows, pages);
    assert.equal(claimed.get(0), 0);
    assert.ok(!claimed.has(1));
  });
});

describe('_fillJobsCell', () => {
  const fakeRow = () => {
    const cell = {};
    return { cell, tr: { querySelector: (sel) => sel === '.url-jobs-cell' ? cell : null } };
  };

  test('renders the matched tab counter', () => {
    const { cell, tr } = fakeRow();
    UrlList._fillJobsCell(tr, { jobs_completed: 3 });
    assert.match(cell.innerHTML, />3</);
  });

  test('missing counter renders 0, unmatched row renders dash', () => {
    const r1 = fakeRow();
    UrlList._fillJobsCell(r1.tr, {});
    assert.match(r1.cell.innerHTML, />0</);
    const r2 = fakeRow();
    UrlList._fillJobsCell(r2.tr, null);
    assert.match(r2.cell.innerHTML, /—/);
  });
});

describe('matchUnclaimedPage strict fallback', () => {
  const rows = [row('https://arena.ai/x?m=a'), row('https://arena.ai/x?m=b')];

  test('never re-renders a claimed page', () => {
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/x?m=a', status: 'cooldown' },
                   { tab_id: 'B', url: '', status: 'steady' }];
    const claimed = UrlList.assignPoolPages(rows, pages);
    assert.equal(claimed.get(0), 0);
    // B has no URL identity: row 2 gets nothing, NOT A's timer
    assert.equal(UrlList.matchUnclaimedPage(rows[1].dataset.url, pages, claimed), null);
  });

  test('unclaimed exact/prefix still matches', () => {
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/x?m=a' },
                   { tab_id: 'B', url: 'https://arena.ai/x?m=b' }];
    const claimed = new Map(); // nothing claimed (e.g. fresh rows)
    assert.equal(UrlList.matchUnclaimedPage(rows[1].dataset.url, pages, claimed).tab_id, 'B');
  });

  test('host-only match refused (too weak across accounts)', () => {
    const pages = [{ tab_id: 'C', url: 'https://arena.ai/other' }];
    assert.equal(UrlList.matchUnclaimedPage(rows[0].dataset.url, pages, new Map()), null);
  });
});
