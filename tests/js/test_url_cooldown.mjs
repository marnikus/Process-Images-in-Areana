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
const baseDir = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list');
const files = ['store.js','render.js','matching.js','cooldown.js','actions.js','../url-list.js'];
const panelPath = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list.js');

function loadAllCode() {
  return files.map(f => fs.readFileSync(path.resolve(baseDir, f), 'utf-8')).join('\n');
}

function loadUrlList() {
  const sandbox = { console, JSON, Math, Object, Array, Map, Set, Error, URL,
    document: undefined, PagePoolPanel: undefined, LogConsole: { log: ()=>{} } };
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  const allCode = loadAllCode();
  vm.runInContext(allCode + '\nthis.__U = UrlList;', sandbox, { filename: 'url-list.js' });
  // init delegates
  if (sandbox.__U && sandbox.__U._store === null) {
    sandbox.__U._store = sandbox.UrlListStore;
    sandbox.__U._render = sandbox.UrlListRender;
    sandbox.__U._matching = sandbox.UrlListMatching;
    sandbox.__U._actions = sandbox.UrlListActions;
    sandbox.__U._cooldown = sandbox.UrlListCooldown;
  }
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

describe('sticky row-tab binding (F10)', () => {
  const srow = (url, tabId) => ({ dataset: { url, tabId } });

  test('bound tab wins over a URL-score tie', () => {
    const rows = [srow('https://arena.ai/same', 'B')];
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/same' },
                   { tab_id: 'B', url: 'https://arena.ai/same' }];
    const claimed = UrlList.assignPoolPages(rows, pages);
    assert.equal(claimed.get(0), 1); // own tab, not the first twin
  });

  test('bound tab wins even when its URL scores lower', () => {
    const rows = [srow('https://arena.ai/job', 'B')];
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/job' },
                   { tab_id: 'B', url: 'https://arena.ai/job?sid=new' }];
    const claimed = UrlList.assignPoolPages(rows, pages);
    assert.equal(claimed.get(0), 1);
  });

  test('vanished bound tab falls back to greedy', () => {
    const rows = [srow('https://arena.ai/same', 'ZZ')];
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/same' }];
    const claimed = UrlList.assignPoolPages(rows, pages);
    assert.equal(claimed.get(0), 0);
  });

  test('unbound rows keep greedy best-match', () => {
    const rows = [srow('https://arena.ai/x?m=b', '')];
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/x?m=a' },
                   { tab_id: 'B', url: 'https://arena.ai/x?m=b' }];
    const claimed = UrlList.assignPoolPages(rows, pages);
    assert.equal(claimed.get(0), 1);
  });

  test('matchPoolPage prefers the bound tab', () => {
    const pages = [{ tab_id: 'A', url: 'https://arena.ai/same' },
                   { tab_id: 'B', url: 'https://arena.ai/same' }];
    const sandbox = { console, JSON, Math, Object, Array, Map, Set, Error, URL,
      document: undefined, PagePoolPanel: { snapshot: { pages } }, LogConsole: { log: ()=>{} } };
    sandbox.self = sandbox;
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    const allCode = loadAllCode();
    vm.runInContext(allCode + '\nthis.__U = UrlList;', sandbox);
    if (sandbox.__U && sandbox.__U._store === null) {
      sandbox.__U._store = sandbox.UrlListStore;
      sandbox.__U._render = sandbox.UrlListRender;
      sandbox.__U._matching = sandbox.UrlListMatching;
      sandbox.__U._actions = sandbox.UrlListActions;
      sandbox.__U._cooldown = sandbox.UrlListCooldown;
    }
    assert.equal(sandbox.__U.matchPoolPage('https://arena.ai/same', 'B').tab_id, 'B');
    assert.equal(sandbox.__U.matchPoolPage('https://arena.ai/same', '').tab_id, 'A');
  });
});

describe('rate-limit penalty field (3rd cooldown input)', () => {
  function loadWithDom(elements, bridgeState) {
    const captured = {};
    const bridge = {
      set_cooldown_config: (json, cb) => { captured.saved = JSON.parse(json); cb(JSON.stringify({ ok: true })); },
      get_cooldown_config: (cb) => { cb(JSON.stringify({ ok: true, config: bridgeState })); },
    };
    const sandbox = { console, JSON, Math, Object, Array, Map, Set, Error, URL,
      document: { getElementById: (id) => elements[id] || null },
      App: { bridge },
      LogConsole: { log: () => {} }, PagePoolPanel: undefined };
    sandbox.self = sandbox; sandbox.window = sandbox; sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    const allCode = loadAllCode();
    vm.runInContext(allCode + '\nthis.__U = UrlList;', sandbox, { filename: 'url-list.js' });
    if (sandbox.__U && sandbox.__U._store === null) {
      sandbox.__U._store = sandbox.UrlListStore;
      sandbox.__U._render = sandbox.UrlListRender;
      sandbox.__U._matching = sandbox.UrlListMatching;
      sandbox.__U._actions = sandbox.UrlListActions;
      sandbox.__U._cooldown = sandbox.UrlListCooldown;
    }
    return { u: sandbox.__U, captured, elements };
  }

  test('saveCooldownConfig carries rate_limit_penalty_seconds in the payload', () => {
    const elements = {
      urlCooldownEnabled: { checked: true },
      urlCooldownMin: { value: '5' },
      urlCooldownPenalty: { value: '15' },
      urlCooldownRateLimit: { value: '30' },
    };
    const { u, captured } = loadWithDom(elements, {});
    u.saveCooldownConfig();
    assert.equal(captured.saved.enabled, true);
    assert.equal(captured.saved.min_seconds, 300);
    assert.equal(captured.saved.captcha_penalty_seconds, 900);
    assert.equal(captured.saved.rate_limit_penalty_seconds, 1800); // 30m
  });

  test('saveCooldownConfig falls back to 30m when the input is empty', () => {
    const elements = {
      urlCooldownEnabled: { checked: true },
      urlCooldownMin: { value: '' },
      urlCooldownPenalty: { value: '' },
      urlCooldownRateLimit: { value: '' },
    };
    const { u, captured } = loadWithDom(elements, {});
    u.saveCooldownConfig();
    assert.equal(captured.saved.rate_limit_penalty_seconds, 1800);
  });

  test('loadCooldownConfig populates the rate-limit input from config', () => {
    const elements = {
      urlCooldownEnabled: { checked: false },
      urlCooldownMin: { value: '' },
      urlCooldownPenalty: { value: '' },
      urlCooldownRateLimit: { value: '' },
    };
    const state = { enabled: true, min_minutes: 5, captcha_penalty_minutes: 15, rate_limit_penalty_minutes: 30 };
    const { u } = loadWithDom(elements, state);
    u.loadCooldownConfig();
    assert.equal(elements.urlCooldownEnabled.checked, true);
    assert.equal(elements.urlCooldownMin.value, 5);
    assert.equal(elements.urlCooldownPenalty.value, 15);
    assert.equal(elements.urlCooldownRateLimit.value, 30);
  });
});
