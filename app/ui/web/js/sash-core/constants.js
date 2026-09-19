/* sash-core/constants.js — window definitions (C7) */
'use strict';
window.SashCoreConstants = (() => {
  const WINDOWS = [
    { id: 'url_list', title: 'URL List' },
    { id: 'folder', title: 'Folder Picker' },
    { id: 'queue', title: 'Image Queue' },
    { id: 'prompt', title: 'Prompt Editor' },
    { id: 'run', title: 'Run Controls' },
    { id: 'progress', title: 'Progress' },
    { id: 'watcher', title: 'Watcher — Generation & Captcha' },
    { id: 'log', title: 'Activity Log' },
    { id: 'settings', title: 'Settings' },
    { id: 'captcha', title: 'Captcha — 2Captcha Control' },
    { id: 'captcha_records', title: 'Captcha Session Records' },
    { id: 'browser', title: 'Browser Preview' },
    { id: 'action_blocks', title: 'Action Blocks — Stacking Jobs' },
    { id: 'block_config', title: 'Block Config — Security Check' },
    { id: 'arena_presets', title: 'Arena Presets' },
  ];
  const WINDOW_IDS = WINDOWS.map(w => w.id);
  const WINDOW_TITLES = Object.fromEntries(WINDOWS.map(w => [w.id, w.title]));
  return { WINDOWS, WINDOW_IDS, WINDOW_TITLES, V1_WINDOW_IDS: WINDOW_IDS, V2_WINDOW_IDS: WINDOW_IDS, V3_WINDOW_IDS: WINDOW_IDS, VERSION: 5, MAX_DEPTH: 12, MIN_SIZE: 4 };
})();
