/**
 * The 19th window `workspace` ("Global Saving System") — mount + flow (RULE 8).
 *
 * Whole-page: every index.html script runs in order (real boot path), so the
 * test proves the window mounts through _PANEL_INITS (never an L-5 orphan) and
 * that Save/Load-last/preview/restore/Open-folder clicks reach the real slots.
 * Several of these fail on the pre-fix code (panel missing/unwired).
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { bootPage, WEB } from './page_harness.mjs';
import { createSashGrid, ALL_WINDOW_IDS, panelIdOf } from './sash_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');

const STATE = {
  default_dir: '/cfg/workspaces',
  recent: ['/cfg/workspaces/my-setup_20260925-180000'],
  last_snapshot: '/cfg/workspaces/my-setup_20260925-180000',
  last_restore: {},
};
const PREVIEW = {
  ok: true, root: '/cfg/workspaces/my-setup_20260925-180000', name: 'my-setup',
  description: '', snapshot_kind: 'full', created_utc: '2026-09-25T18:00:00Z',
  app: { build: 'f5cb06e' },
  domains: [
    { domain_id: 'arena_state', display_name: 'Queue, URLs, Folder, Prompt, Jobs', status: 'ok', required: true },
    { domain_id: 'undo', display_name: 'Undo History', status: 'ok', required: false },
    { domain_id: 'captcha_keys', display_name: 'Captcha Solver Keys', status: 'excluded', note: 'secret' },
  ],
  path_remap_needed: [],
};
const RESTORED = {
  ok: true, result: 'success_with_warnings',
  restored: ['arena_state', 'undo', 'session_settings', 'cooldowns'], migrated: [],
  skipped: [{ domain_id: 'captcha_keys', stage: 'apply', policy: true,
              cause: 'secret', recommended_action: 'Re-enter the API key' }],
  reconciled: [], backup: '/cfg/workspace_recovery/20260925-180001',
  workspace: PREVIEW.root,
};

function boot() {
  return bootPage({
    replies: {
      // static replies are objects — the harness JSON-encodes them once, exactly
      // like a real @Slot(str, result=str) reply arrives on the JS side
      get_workspace_state: STATE,
      get_arena_state: { version: 1, urls: [], images: [],
        folder: { root_path: '/imgs' }, prompt: { template: 'restored!' },
        settings: { timeouts: { generation: 111 } }, progress: {}, jobs: [] },
      get_grid_layout: { v: 9, tree: { t: 'leaf', id: 'queue' } },
      get_window_states: { closed: ['log'], minimized: [] },
      get_firefox_auto_config: { config: {}, paths: {}, running: false },
      get_cdp_config: {},
      get_chrome_launch_command: '',
      get_action_blocks: [],
      get_watcher_config: {},
      get_cooldown_config: { ok: true, config: {} },
      preview_workspace: (root) => JSON.stringify(root === PREVIEW.root ? PREVIEW : { ok: false, error: 'not a snapshot' }),
      restore_workspace: () => JSON.stringify(RESTORED),
      save_workspace: { ok: true, result: 'success', path: '/cfg/workspaces/w_1', domains: [], errors: [] },
      browse_workspace_folder: { ok: true, path: PREVIEW.root },
    },
  });
}

function findInGrid(grid, id) {
  const find = (n) => {
    if (n.id === id) return n;
    for (const c of n.children || []) { const r = find(c); if (r) return r; }
    return null;
  };
  return find(grid.body);
}

describe('workspace window (mount)', () => {
  test('index.html registers winWorkspace with the flow controls', () => {
    assert.ok(html.includes('id="winWorkspace" data-window="workspace"'), 'panel present');
    assert.ok(html.includes('js/panels/workspace.js'), 'script loaded');
    for (const id of ['wsSaveBtn', 'wsSaveAsBtn', 'wsBrowseBtn', 'wsLoadLastBtn',
                      'wsPreview', 'wsRestoreAllBtn', 'wsRestoreSelectedBtn', 'wsRecentList']) {
      assert.ok(html.includes(`id="${id}"`), id);
    }
  });

  test('winWorkspace joins the sash grid without being an orphan', () => {
    assert.ok(ALL_WINDOW_IDS.includes('workspace'), 'harness registry mirrors the python catalog');
    assert.equal(panelIdOf('workspace'), 'winWorkspace');
    const h = createSashGrid();
    h.SashGrid.render();
    const win = findInGrid(h, 'winWorkspace');
    assert.ok(win, 'winWorkspace exists after render');
    const inside = (n, root) => { for (let c = n; c; c = c.parent) if (c === root) return true; return false; };
    assert.ok(inside(win, h.gridEl), 'winWorkspace is inside #sashGrid');
    const countPanels = (n) => (String(n.className).includes('panel') ? 1 : 0)
      + (n.children || []).reduce((sum, c) => sum + countPanels(c), 0);
    assert.equal(countPanels(h.gridEl), 19, 'all 19 windows lay out inside the grid');
  });

  test('the panel publishes itself on window (I-35 global-name contract)', () => {
    const { sb } = boot();
    assert.equal(typeof sb.WorkspacePanel?.init, 'function');
  });

  test('_PANEL_INITS boots WorkspacePanel (real page order)', () => {
    const source = fs.readFileSync(path.join(WEB, 'js/arena-app.js'), 'utf8');
    assert.ok(/'WorkspacePanel'/.test(source), 'in the boot table');
  });

  test('boot pulls the workspace state (recent + last snapshot)', () => {
    const page = boot();
    const call = page.calls.find((c) => c.slot === 'get_workspace_state');
    assert.ok(call, 'get_workspace_state called on boot');
  });
});

const tick = () => new Promise((resolve) => setImmediate(resolve));

describe('workspace window (flow)', () => {
  test('Save Workspace… calls save_workspace with the name field', async () => {
    const page = boot();
    page.anyEl('wsName').value = 'my setup';
    page.anyEl('wsSaveBtn').dispatch('click', {});
    await tick();
    const call = page.calls.find((c) => c.slot === 'save_workspace');
    assert.ok(call, 'slot reached');
    const opts = JSON.parse(call.args[0]);
    assert.equal(opts.name, 'my setup');
    assert.ok(page.anyEl('wsResult').innerHTML.includes('Workspace saved'), 'result shown');
  });

  test('Load last → preview renders domains with checkboxes, Restore All applies', async () => {
    const page = boot();
    page.anyEl('wsLoadLastBtn').dispatch('click', {});
    await tick(); await tick();
    const previewCall = page.calls.find((c) => c.slot === 'preview_workspace');
    assert.ok(previewCall && previewCall.args[0] === PREVIEW.root, 'preview from last snapshot');
    assert.ok(page.anyEl('wsPreview').innerHTML.includes('Queue, URLs, Folder, Prompt, Jobs'),
              'domain rows rendered');
    assert.ok(page.anyEl('wsPreview').innerHTML.includes('excluded'), 'exclusion shown, never silent');
    page.anyEl('wsRestoreAllBtn').dispatch('click', {});
    await tick(); await tick();
    const restoreCall = page.calls.find((c) => c.slot === 'restore_workspace');
    assert.ok(restoreCall && restoreCall.args[0] === PREVIEW.root, 'restore on the previewed folder');
    assert.ok(page.anyEl('wsResult').innerHTML.includes('success_with_warnings'), 'result shown');
    assert.ok(page.anyEl('wsResult').innerHTML.includes('Re-enter the API key'),
              'recommended action shown');
  });

  test('Restore Selected… sends only the checked domains', async () => {
    const page = boot();
    page.anyEl('wsLoadLastBtn').dispatch('click', {});
    await tick(); await tick();
    // a browser resolves ".ws-domain:checked"; the stub pre-filters the same way
    page.sb.document.querySelectorAll = () => [
      { dataset: { domain: 'undo' }, checked: true },
    ];
    page.anyEl('wsRestoreSelectedBtn').dispatch('click', {});
    await tick(); await tick();
    const restoreCall = page.calls.find((c) => c.slot === 'restore_workspace');
    assert.deepEqual(JSON.parse(restoreCall.args[1]), { selected: ['undo'] });
  });

  test('Browse… picks a folder and previews it (restore-selected entry)', async () => {
    const page = boot();
    page.anyEl('wsBrowseBtn').dispatch('click', {});
    await tick(); await tick();
    assert.ok(page.calls.find((c) => c.slot === 'browse_workspace_folder'));
    assert.ok(page.calls.find((c) => c.slot === 'preview_workspace'), 'preview after browse');
  });

  test('Open-folder affordances call open_workspace_path (recent + result)', async () => {
    const page = boot();
    page.anyEl('wsLoadLastBtn').dispatch('click', {});
    await tick(); await tick();
    page.anyEl('wsRestoreAllBtn').dispatch('click', {});
    await tick(); await tick();
    assert.ok(page.anyEl('wsResult').innerHTML.includes('Open folder'), 'affordance rendered');
    // closest that answers like a real DOM node (only its own selector matches)
    const fromData = (attr, value) => (sel) => sel === `[data-${attr}]` ? { dataset: { [attr]: value } } : null;
    // result panel: delegated click on [data-open]
    page.anyEl('wsResult').dispatch('click',
      { target: { closest: fromData('open', RESTORED.workspace) } });
    // recent list: the "open" link
    page.anyEl('wsRecentList').dispatch('click',
      { target: { closest: fromData('open', STATE.recent[0]) }, preventDefault: () => {} });
    const opens = page.calls.filter((c) => c.slot === 'open_workspace_path').map((c) => c.args[0]);
    assert.ok(opens.includes(RESTORED.workspace), 'result Open folder opens the workspace');
    assert.ok(opens.includes(STATE.recent[0]), 'recent-list link opens the snapshot');
  });
});

describe('workspace window (RULE 24 live sync)', () => {
  const tick = () => new Promise((resolve) => setImmediate(resolve));

  test('each recent checkpoint has a load link that opens the restore preview', async () => {
    const page = boot();
    for (let i = 0; i < 4; i++) await tick();          // boot pull renders the list
    const recent = page.anyEl('wsRecentList').innerHTML;
    assert.match(recent, /data-load="[^"]*my-setup_20260925-180000"/, 'load link present');
    assert.match(recent, /data-open=/, 'open link still present');
    page.anyEl('wsRecentList').dispatch('click', {
      preventDefault: () => {},
      target: { closest: (sel) => sel === '[data-load]'
        ? { dataset: { load: STATE.recent[0] } } : null },
    });
    for (let i = 0; i < 4; i++) await tick();
    const previewCall = page.calls.find((c) => c.slot === 'preview_workspace');
    assert.ok(previewCall && previewCall.args[0] === STATE.recent[0], 'load previews that folder');
    assert.ok(page.anyEl('wsRestoreActions'), 'restore actions shown');
  });

  test('restore re-runs every config-driven loader (no stale fields until restart)', async () => {
    const page = boot();
    for (let i = 0; i < 4; i++) await tick();          // settle boot-time pulls
    const before = page.calls.length;
    page.anyEl('wsLoadLastBtn').dispatch('click', {});
    for (let i = 0; i < 4; i++) await tick();
    page.anyEl('wsRestoreAllBtn').dispatch('click', {});
    for (let i = 0; i < 8; i++) await tick();
    const after = page.calls.slice(before);
    const slots = after.map((c) => c.slot);
    for (const slot of ['get_firefox_auto_config', 'get_cdp_config', 'get_action_blocks',
                        'get_watcher_config', 'get_cooldown_config']) {
      assert.ok(slots.includes(slot), `${slot} re-pulled after restore`);
    }
  });

  test('restore re-renders prompt + folder fields from the fresh arena payload', async () => {
    const page = boot();
    for (let i = 0; i < 4; i++) await tick();
    page.anyEl('wsLoadLastBtn').dispatch('click', {});
    for (let i = 0; i < 4; i++) await tick();
    page.anyEl('wsRestoreAllBtn').dispatch('click', {});
    for (let i = 0; i < 8; i++) await tick();
    assert.equal(page.anyEl('promptTextarea').value, 'restored!', 'prompt field refreshed');
    assert.equal(page.anyEl('folderPathDisplay').textContent, '/imgs', 'folder field refreshed');
  });
});

describe('workspace window (live refresh after restore)', () => {
  const tick = () => new Promise((resolve) => setImmediate(resolve));

  test('Restore All without a preview auto-loads the LAST snapshot (never silent)', async () => {
    const page = boot();
    page.anyEl('wsRestoreAllBtn').dispatch('click', {});
    await tick(); await tick();
    const previewCall = page.calls.find((c) => c.slot === 'preview_workspace');
    assert.ok(previewCall && previewCall.args[0] === PREVIEW.root, 'auto-preview from last');
    await tick(); await tick();
    assert.ok(page.calls.find((c) => c.slot === 'restore_workspace'), 'restore ran');
  });

  test('Restore All with no snapshot shows a visible refusal (never silent)', async () => {
    const page = bootPage({ replies: {
      get_workspace_state: { default_dir: '/cfg', recent: [], last_snapshot: '' },
    } });
    page.anyEl('wsRestoreAllBtn').dispatch('click', {});
    await tick(); await tick();
    assert.match(page.anyEl('wsResult').innerHTML, /Nothing to restore/);
  });

  test('a successful restore re-renders the live panels from fresh arena state', async () => {
    const page = boot();
    const seen = { url: [], settings: [] };
    for (const [name, sink] of [['UrlList', seen.url], ['SettingsPanel', seen.settings]]) {
      const panel = page.sb[name];
      assert.ok(panel?.restore, `${name} publishes restore()`);
      const original = panel.restore.bind(panel);
      page.sb[name].restore = (state) => { sink.push(state); return original(state); };
    }
    page.anyEl('wsLoadLastBtn').dispatch('click', {});
    await tick(); await tick();
    page.anyEl('wsRestoreAllBtn').dispatch('click', {});
    await tick(); await tick(); await tick();
    assert.ok(seen.url.length >= 1, 'UrlList re-rendered');
    assert.equal(seen.settings.at(-1).prompt.template, 'restored!');
    assert.equal(seen.settings.at(-1).settings.timeouts.generation, 111);
  });

  test('grid_window restore re-renders the live sash grid', async () => {
    const applied = {};
    const page2 = bootPage({
      replies: {
        restore_workspace: () => JSON.stringify({ ok: true, result: 'success',
          restored: ['grid_window'], skipped: [], migrated: [] }),
        get_workspace_state: STATE,
        preview_workspace: (root) => JSON.stringify({ ok: true, root, name: 'a',
          created_utc: 't', app: {}, snapshot_kind: 'full',
          domains: [{ domain_id: 'grid_window', display_name: 'Grid', status: 'ok' }] }),
        get_arena_state: {},
        get_grid_layout: { v: 9, tree: { t: 'leaf', id: 'queue' } },
        get_window_states: { closed: ['log'], minimized: [] },
      },
    });
    const grid = page2.sb.SashGrid;
    assert.ok(grid, 'the page runs the real sash grid');
    grid._restoreWinElsVisibility = () => { applied.visibility = true; };
    grid.render = () => { applied.render = true; };
    grid._save = () => { applied.saved = true; };
    grid._saveWindowStates = () => { applied.states = true; };
    page2.anyEl('wsLoadLastBtn').dispatch('click', {});
    for (let i = 0; i < 4; i++) await tick();
    page2.anyEl('wsRestoreAllBtn').dispatch('click', {});
    for (let i = 0; i < 8; i++) await tick();
    assert.ok(applied.render && applied.saved, 'grid re-rendered and persisted');
    assert.equal(page2.sb.SashGrid.closedWindows.has('log'), true, 'closed set restored');
    const leaves = [];
    const walk = (n) => n.t === 'leaf' ? leaves.push(n.id) : n.children.forEach(walk);
    walk(page2.sb.SashGrid.root);
    assert.equal(leaves.length, 19, 'tree validated/migrated through SashCore');
  });
});
