/* sash_harness.mjs — load the REAL sash-grid JS (all part files + facade)
   into a minimal DOM with a CSS-flexbox layout engine, for Tier-A Node tests.

   Mirrors how index.html wires the app: sash-core → ui-helpers → parts →
   sash-grid.js facade, then SashGrid.init() against a #sashGrid that holds
   the real panel elements. No browser, no Qt.
*/
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { El, layoutGrid } from './fake_dom.mjs';

const WEB = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../app/ui/web');
const read = (f) => fs.readFileSync(path.join(WEB, 'js', f), 'utf-8');

export const ALL_WINDOW_IDS = [
  'url_list', 'folder', 'queue', 'prompt', 'run', 'progress', 'watcher', 'log',
  'settings', 'captcha', 'browser', 'action_blocks', 'block_config', 'arena_presets', 'recordings',
];

export function panelIdOf(id) {
  // mirrors the ids in app/ui/web/index.html (camelCase: url_list → winUrlList)
  return 'win' + id.split('_').map((p) => p[0].toUpperCase() + p.slice(1)).join('');
}

/* Secondary title items (buttons/badges) per window, mirroring index.html:
   `pre` items sit before the spacer, `post` items after it. These are the
   items the title-fit routine may drop when a window narrows. */
export const TITLE_SECONDARIES = {
  url_list: { pre: ['urlReparseBtn', 'urlPopupBtn'], post: ['urlCount'] },
  queue: { pre: [], post: ['queueCount'] },
  prompt: { pre: [], post: ['promptSaveBtn'] },
  watcher: { pre: [], post: ['watcherStatusBadge'] },
  log: { pre: [], post: ['clearLogBtn'] },
  settings: { pre: [], post: ['settingsSaveBtn'] },
  captcha: { pre: [], post: ['captchaSaveBtn', 'captchaStatsBtn'] },
  recordings: { pre: [], post: ['recRefreshBtn'] },
  browser: { pre: [], post: ['browserClearBtn'] },
  action_blocks: { pre: [], post: ['actionBlocksCount'] },
  block_config: { pre: [], post: ['closeBlockConfigBtn'] },
  arena_presets: { pre: [], post: ['arenaPresetsCount'] },
};
const BADGE_LIKE = new Set(['urlCount', 'queueCount', 'watcherStatusBadge',
  'actionBlocksCount', 'arenaPresetsCount']);

function makePanel(id) {
  const p = new El('div');
  p.className = 'panel';
  p.id = panelIdOf(id);
  const title = new El('h3');
  title.className = 'win-title';
  const grip = new El('span');
  grip.className = 'win-grip material-icons';
  grip.textContent = 'drag_indicator';
  title.appendChild(grip);
  const icon = new El('span');
  icon.className = 'material-icons';
  icon.textContent = 'icon';
  title.appendChild(icon);
  // bare text node (as in index.html) — the wrap target
  title.appendText(' ' + id.replace(/_/g, ' ').toUpperCase() + ' ');
  const sec = TITLE_SECONDARIES[id];
  if (sec) {
    for (const sid of sec.pre) {
      const b = new El(BADGE_LIKE.has(sid) ? 'span' : 'button');
      b.id = sid; b.textContent = sid;
      title.appendChild(b);
    }
    const sp = new El('span');
    sp.className = 'spacer';
    title.appendChild(sp);
    for (const sid of sec.post) {
      const b = new El(BADGE_LIKE.has(sid) ? 'span' : 'button');
      b.id = sid; b.textContent = sid;
      title.appendChild(b);
    }
  }
  p.appendChild(title);
  return p;
}

export function createSashGrid() {
  const body = new El('body');
  const gridEl = new El('main');
  gridEl.id = 'sashGrid';
  gridEl.className = 'sash-grid';
  body.appendChild(gridEl);
  ALL_WINDOW_IDS.forEach((id) => body.appendChild(makePanel(id)));

  const sandbox = {
    console,
    Math, JSON, Object, Array, Set, Map, Error, Number, String, Promise,
    setTimeout: () => 0,
    clearTimeout: () => {},
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    getComputedStyle: () => ({ display: 'block' }),
    MutationObserver: class { constructor(cb) { this.cb = cb; } observe() {} disconnect() {} },
  };
  const docListeners = {};
  sandbox.document = {
    body,
    createElement: (t) => new El(t),
    getElementById: (id) => {
      const find = (n) => {
        if (n.id === id) return n;
        for (const c of n.children) { const r = find(c); if (r) return r; }
        return null;
      };
      return find(body);
    },
    addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); },
    removeEventListener: (t, f) => {
      docListeners[t] = (docListeners[t] || []).filter((x) => x !== f);
    },
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.addEventListener = (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); };
  sandbox.removeEventListener = () => {};
  sandbox.innerWidth = 1600;
  vm.createContext(sandbox);

  const load = (file) => vm.runInContext(read(file), sandbox, { filename: file });
  load('sash-core.js');
  load('core/ui-helpers.js');
  load('sash-grid-tree.js');
  load('sash-grid-drag-core.js');
  load('sash-grid-drag-spec.js');
  load('sash-grid-drag-resize.js');
  load('sash-grid-windows.js');
  load('sash-grid-presets.js');
  const SashGrid = vm.runInContext(read('sash-grid.js') + '\n;SashGrid', sandbox, { filename: 'sash-grid.js' });
  SashGrid.init();

  return {
    SashGrid,
    SashCore: sandbox.SashCore,
    gridEl,
    body,
    layout: (w = 1600, h = 1000) => layoutGrid(gridEl, w, h),
  };
}

/* Put a fresh split tree into the grid with given closed/minimized windows. */
export function resetGrid(h, tree, closed = [], minimized = []) {
  h.SashGrid.root = h.SashCore.clone(tree);
  h.SashGrid.closedWindows = new Set(closed);
  h.SashGrid.minimizedWindows = new Set(minimized);
  h.SashGrid.render();
  h.layout();
}

export function rootSplit(h) { return h.gridEl.children[0]; }
export function childEls(splitEl) {
  const out = [];
  for (let i = 0; i * 2 < splitEl.children.length; i++) out.push(splitEl.children[i * 2]);
  return out;
}
export function sashesOf(splitEl) {
  return splitEl.children.filter((c) => c.classList.contains('sash'));
}
export function winIdOf(el) {
  if (el.dataset && el.dataset.win) return el.dataset.win;
  const w = el.querySelector && el.querySelector('.sash-window');
  return w ? w.dataset.win : null;
}
export function axisSize(el, isRow) {
  const r = el.getBoundingClientRect();
  return isRow ? r.width : r.height;
}
export function childTops(splitEl) {
  const tops = [];
  for (const c of childEls(splitEl)) tops.push(c.getBoundingClientRect().top);
  return tops;
}

/* Simulate one sash drag: start on sash, move delta px along its axis, release.
   Returns { before, after, model } in model-units (percent). */
export function dragSash(h, sashEl, deltaPx) {
  const isRow = sashEl.classList.contains('sash-v');
  const splitEl = sashEl.parentElement;
  const before = childEls(splitEl).map((c) => +axisSize(c, isRow).toFixed(2));
  const sashRect = sashEl.getBoundingClientRect();
  const sx = sashRect.left + sashRect.width / 2;
  const sy = sashRect.top + sashRect.height / 2;
  const sIdx = parseInt(sashEl.dataset.idx, 10);
  // pointer starts just past the sash edge; end point is delta beyond it
  const edge = isRow
    ? sashRect.left + sashRect.width
    : sashRect.top + sashRect.height;
  h.SashGrid._startResize(sashEl, { button: 0, pointerId: 1, clientX: sx, clientY: sy + 1, preventDefault() {} });
  for (const f of [0.33, 0.67, 1]) {
    const p = isRow ? edge + deltaPx * f : sy;
    const q = isRow ? sy : edge + deltaPx * f;
    h.SashGrid._resizeMove({ clientX: p, clientY: q, preventDefault() {} });
    h.layout();
  }
  h.SashGrid._resizeUp();
  h.layout();
  const after = childEls(splitEl).map((c) => +axisSize(c, isRow).toFixed(2));
  return { before, after, model: h.SashGrid.getTree().sizes, sIdx };
}
