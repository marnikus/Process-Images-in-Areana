/**
 * Folder Picker — the pushed state must reach the panel, not only the boot pull.
 *
 * Owner report (2026-10-01): "folder picker display nothing". The panel rendered
 * the folder only from the ONE boot pull (`get_arena_state` →
 * `arena-app.js::_restoreArenaPanels`); every later report of the same state
 * arrives as an `arena_state_updated` push, and the live-apply list in
 * `arena-app/listeners.js` (`LIVE_STATE_PANELS`) did not name FolderPicker. So
 * after a scan, a Clear List, a New Batch or a workspace restore the panel kept
 * showing the pre-change path and "0 images · 0 pending" while the Image Queue
 * next to it updated — the folder area looked empty/broken.
 *
 * Whole page, real boot path (RULE 8 / RULE 16.6): the assertions run the same
 * `arena_state_updated` → 250 ms debounce → panel.restore chain the page runs.
 * Deleting FolderPicker from LIVE_STATE_PANELS fails tests 1, 2 and 4; deleting
 * the active-element guard in `_showPath` fails tests 3 and 6.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { bootPage } from './page_harness.mjs';

const FOLDER_PANEL_IDS = ['folderPathDisplay', 'folderPathInput', 'folderStats'];

function arenaState({ root = '', images = [] } = {}) {
  return {
    version: 3,
    folder: { root_path: root, supported_types: ['.png', '.jpg'], ignore_ai_suffix: true },
    images,
    urls: [],
    prompt: { template: '' },
    settings: {},
    progress: { total: images.length, completed: 0, failed: 0, skipped: 0 },
    jobs: [],
    run_state: 'idle',
  };
}

const img = (id, status = 'pending') => ({ id, filename: `${id}.png`, status, selected: true });

function boot({ state = arenaState(), replies = {} } = {}) {
  const page = bootPage({
    prepare: (anyEl) => {
      FOLDER_PANEL_IDS.forEach((id) => anyEl(id));
      anyEl('folderPathDisplay').textContent = 'No folder selected';
    },
    replies: { get_arena_state: state, ...replies },
  });
  page.flushTimers();
  return page;
}

const shown = (page) => ({
  path: page.anyEl('folderPathDisplay').textContent,
  input: page.anyEl('folderPathInput').value,
  stats: page.anyEl('folderStats').innerHTML,
});

/* The one thing under test: report the state the way the app reports it. */
function push(page, state) {
  page.emit('arena_state_updated', JSON.stringify(state));
  page.flushTimers();
}

describe('Folder Picker — live arena_state push (the panel must not go blank)', () => {
  test('a pushed folder + scanned images reach the panel (scan lands as a push)', () => {
    const page = boot({ state: arenaState() });
    assert.deepEqual(shown(page), {
      path: 'No folder selected', input: '',
      stats: '<span><b>0</b> images</span><span><b>0</b> pending</span>',
    });

    push(page, arenaState({ root: 'C:/imgs', images: [img('a'), img('b', 'completed')] }));

    assert.equal(shown(page).path, 'C:/imgs');
    assert.equal(shown(page).input, 'C:/imgs');
    assert.equal(shown(page).stats, '<span><b>2</b> images</span><span><b>1</b> pending</span>');
  });

  test('a restored folder replaces the stale path (workspace restore pushes the same signal)', () => {
    const page = boot({ state: arenaState({ root: 'C:/imgs' }) });
    assert.equal(shown(page).path, 'C:/imgs');

    push(page, arenaState({ root: 'D:/restored' }));

    assert.equal(shown(page).path, 'D:/restored');
    assert.equal(shown(page).input, 'D:/restored');
  });

  test('a push never eats what the owner is typing; the read-only parts still update', () => {
    const page = boot({ state: arenaState({ root: 'C:/imgs' }) });
    const input = page.anyEl('folderPathInput');
    page.sb.document.activeElement = input;      // the caret is in the box
    input.value = 'D:/half-typed';

    push(page, arenaState({ root: 'C:/imgs', images: [img('a')] }));

    assert.equal(input.value, 'D:/half-typed', 'the debounced push must not overwrite the box');
    assert.equal(shown(page).path, 'C:/imgs', 'the read-only line still follows the state');
    assert.equal(shown(page).stats, '<span><b>1</b> images</span><span><b>1</b> pending</span>');

    page.sb.document.activeElement = null;       // caret leaves the box
    push(page, arenaState({ root: 'E:/after-blur', images: [img('a')] }));
    assert.equal(input.value, 'E:/after-blur', 'once focus is gone the box follows again');
  });

  test('boot pull and live push render the panel identically (one rule, RULE 10)', () => {
    const state = arenaState({ root: 'C:/imgs', images: [img('a'), img('b', 'completed')] });
    const page = boot({ state });
    const afterBoot = shown(page);

    push(page, state);

    assert.deepEqual(shown(page), afterBoot, 'a re-push of the same state changes nothing');
    assert.deepEqual(page.errors, [], 'the panel restore must not throw');
  });

  test('an emptied queue renders 0/0 — never the stale counts (RULE 4: empty is its own answer)', () => {
    const page = boot({ state: arenaState({ root: 'C:/imgs', images: [img('a'), img('b')] }) });
    assert.match(shown(page).stats, /<b>2<\/b> images/);

    push(page, arenaState({ root: 'C:/imgs', images: [] }));

    assert.equal(shown(page).stats, '<span><b>0</b> images</span><span><b>0</b> pending</span>');
  });

  test('an owner act writes the box it is not sitting in; a focused box keeps the typing', () => {
    const page = boot({
      state: arenaState(),
      replies: { set_folder_path: { ok: true, path: 'C:/trimmed' } },
    });
    const input = page.anyEl('folderPathInput');
    page.sb.document.activeElement = input;
    input.value = '  C:/trimmed  ';
    input.dispatch('keydown', { key: 'Enter', target: input });

    assert.equal(input.value, '  C:/trimmed  ', 'the box under the caret is never rewritten');
    assert.equal(shown(page).path, 'C:/trimmed', 'the read-only line shows the committed path');

    page.sb.document.activeElement = null;                 // the owner clicked away
    input.dispatch('keydown', { key: 'Enter', target: input });
    assert.equal(input.value, 'C:/trimmed', 'with the caret elsewhere the box snaps to the path');
  });
});
