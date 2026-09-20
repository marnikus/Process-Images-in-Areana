/**
 * Live Worker & Queue Debug — the 16th window (S8: registration + the L-5 rescue;
 * S9 appends the content tests). Real sash grid in the fake DOM; real index.html.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';
import { createSashGrid, ALL_WINDOW_IDS } from './sash_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');

describe('winLiveDebug registration (S8)', () => {
  test('the grid mounts winLiveDebug and an unregistered panel is the one that gets dropped', () => {
    assert.ok(ALL_WINDOW_IDS.includes('live_debug'));
    const h = createSashGrid();
    const win = h.gridEl.querySelector('.sash-window[data-win="live_debug"]');
    assert.ok(win, 'registered window must live inside #sashGrid after init/render');
    assert.equal(win.querySelector(':scope > .panel').id, 'winLiveDebug');
    // the L-5 mechanism: a panel with an id no registry knows is not mounted anywhere
    const orphan = new El('div'); orphan.id = 'winPagePool'; orphan.dataset.window = 'page_pool';
    h.body.appendChild(orphan);
    h.SashGrid.render();
    assert.equal(h.gridEl.querySelector('.sash-window[data-win="page_pool"]'), null);
    assert.equal(h.gridEl.querySelectorAll('.sash-window').length, ALL_WINDOW_IDS.length);
  });

  test('the pool panel still finds its ids inside the rescued window', () => {
    const start = html.indexOf('id="winLiveDebug"');
    const end = html.indexOf('<!-- ACTIVITY LOG -->', start);
    const block = html.slice(start, end);
    for (const id of ['poolStatusBadge', 'poolRefreshBtn', 'poolConnectBtn', 'poolClearBtn', 'poolTableBody', 'poolTotal', 'poolFree']) {
      assert.ok(block.includes(`id="${id}"`), id);
    }
    assert.ok(!html.includes('data-window="page_pool"'));
    assert.ok(block.includes('Live Worker &amp; Queue Debug') || block.includes('Live Worker & Queue Debug'));
  });

  test('_PANEL_INITS includes LiveDebugPanel and the module publishes itself', () => {
    const app = fs.readFileSync(path.join(WEB, 'js/arena-app.js'), 'utf8');
    const block = app.split('_PANEL_INITS = [')[1].split('];')[0];
    assert.ok(block.includes("'LiveDebugPanel'"));
    const panel = fs.readFileSync(path.join(WEB, 'js/panels/live-debug.js'), 'utf8');
    assert.ok(/window\.LiveDebugPanel\s*=\s*LiveDebugPanel/.test(panel));
    assert.ok(html.includes('js/panels/live-debug.js'));
  });
});
