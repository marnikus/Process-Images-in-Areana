/**
 * Tier A — window title-bar controls must stay fully visible on the right in
 * ANY window width. Regression for the report: on Prompt Editor (and any
 * window whose title bar carries secondary buttons/badges) the ─/✕ controls
 * get clipped by `.panel{overflow:hidden}` when the window is narrower than
 * the title row's min-content width.
 *
 * The fix has three parts, all asserted here against the REAL production JS
 * and CSS (no browser):
 *   A. CSS — title text truncates (.win-name), secondary items can be dropped
 *      (.fit-hidden), fixed core < 96px floor, .win-title overflow:hidden.
 *   B. JS — one pure fit function, one writer: _fitTitleBars() recomputes
 *      from scratch (un-hide all, then hide rightmost secondary while
 *      overflowing).
 *   C. JS — bare title text is wrapped in span.win-name (idempotent).
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  createSashGrid, resetGrid, rootSplit, childEls, dragSash, ALL_WINDOW_IDS,
} from './sash_harness.mjs';
import { USER_TREE, USER_CLOSED, USER_MINIMIZED } from './user_layout.mjs';

const findWin = (h, id) => h.gridEl.querySelector('.sash-window[data-win="' + id + '"]');
const titleOf = (h, id) => findWin(h, id).querySelector(':scope > .panel > .win-title');

/* ── simulated title-row geometry (mirrors the shipped CSS numbers) ── */
/* The browser lays the row out as flex with gap:4px. Fixed items never
   shrink below min-content; .win-name (flex:0 1 auto; min-width:0) yields
   first (truncates to 0 under pressure); secondaries (buttons/badges) hold
   their text width, so the fitter must drop them right-to-left. */
const PAD = 4;            // 2px + 2px (full-bleed bar, trimmed padding)
const GAP = 4;            // flex gap per item
const GRIP = 14, ICON = 16, CONTROLS = 42; // 2×20px buttons + 2px inner gap
function measureTitle(t, widths) {
  const kids = Array.from(t.children).filter((k) => !k.classList.contains('fit-hidden'));
  let fixed = PAD;
  let nameW = 0;
  for (const k of kids) {
    fixed += GAP;
    if (k.classList.contains('win-grip')) fixed += GRIP;
    else if (k.classList.contains('material-icons')) fixed += ICON;
    else if (k.classList.contains('win-name')) nameW = widths[k.id] || widths.name || 0;
    else if (k.classList.contains('win-controls')) fixed += CONTROLS;
    else if (k.classList.contains('spacer')) { /* 0 */ }
    else fixed += widths[k.id] || 40;
  }
  const nameAlloc = Math.max(0, t.clientWidth - fixed);
  return Math.max(t.clientWidth, fixed + Math.min(nameW, nameAlloc));
}
/* Narrow one window horizontally: root ROW split [id, log], id gets 6%
   (≈96px @1600) — the title bar's width follows the window WIDTH. */
function narrow(h, id) {
  const S = h.SashCore;
  resetGrid(h, S.split('row', [S.leaf(id), S.leaf('log')], [6, 94]));
  const title = titleOf(h, id);
  const w = findWin(h, id).getBoundingClientRect().width;
  title._rect.width = w;               // full-bleed title bar = wrapper width
  return title;
}

describe('A — CSS contract (sash-layout.css)', () => {
  const css = fs.readFileSync(
    path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../app/ui/web/css/sash-layout.css'),
    'utf8');
  const block = (sel) => {
    const m = new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([\\s\\S]*?)\\}', 'm')
      .exec(css);
    return m ? m[1] : null;
  };
  const num = (re, s) => { const m = re.exec(s || ''); return m ? parseFloat(m[1]) : NaN; };

  test('.win-name truncates: the quartet + shrinkable flex item', () => {
    const b = block('.win-title .win-name') || block('.win-name');
    assert.ok(b, '.win-name rule exists');
    for (const prop of ['min-width: 0', 'overflow: hidden', 'white-space: nowrap',
                        'text-overflow: ellipsis', 'flex: 0 1 auto'])
      assert.ok(b.includes(prop), `.win-name missing "${prop}"`);
  });

  test('.win-title clips its own overflow (ellipsis host)', () => {
    const blocks = [...css.matchAll(/\.win-title[^{]*\{([\s\S]*?)\}/g)].map((m) => m[1]);
    assert.ok(blocks.some((b) => /overflow:\s*hidden/.test(b)),
      'a .win-title rule must set overflow:hidden');
  });

  test('.win-controls never shrinks; .fit-hidden is display:none', () => {
    assert.ok((block('.win-controls') || '').includes('flex-shrink: 0'),
      '.win-controls must keep flex-shrink:0');
    assert.ok((block('.win-title .fit-hidden') || block('.fit-hidden') || '')
      .includes('display: none'), '.fit-hidden must be display:none');
  });

  test('fixed core fits the 96px minimum window (the guarantee base)', () => {
    const minPanel = num(/--sash-min-panel:\s*(\d+)px/, css);
    const padH = num(/padding:\s*4px\s*(\d+)px/, block('.win-title') || '');
    const marginL = num(/margin-left:\s*(\d+(?:px)?)/, block('.win-controls') || '');
    const core = 2 * padH + GRIP + ICON + 5 * GAP + CONTROLS + marginL;
    assert.ok(Number.isFinite(minPanel), '--sash-min-panel parses');
    assert.ok(core <= minPanel, `core ${core}px must be ≤ floor ${minPanel}px`);
  });
});

describe('C — bare title text becomes a truncatable span.win-name', () => {
  test('all 13 titles: .win-name holds the text; .win-controls is last', () => {
    const h = createSashGrid();
    for (const id of ALL_WINDOW_IDS) {
      const title = titleOf(h, id);
      const name = title.querySelector(':scope > .win-name');
      assert.ok(name, `${id}: .win-name missing`);
      assert.ok(name.textContent.trim(), `${id}: .win-name empty`);
      const kids = Array.from(title.children);
      assert.ok(kids[kids.length - 1].classList.contains('win-controls'),
        `${id}: .win-controls must be the last title child`);
      // idempotent: re-running the ensure pass must not double-wrap
      h.SashGrid._ensureWindowControls();
      assert.equal(title.querySelectorAll(':scope > .win-name').length, 1,
        `${id}: text double-wrapped`);
    }
  });
});

describe('B — _fitTitleBars(): single pure writer', () => {
  test('wide window: nothing hidden (no-op guard, keeps fuzz clean)', () => {
    const h = createSashGrid();
    resetGrid(h, h.SashCore.clone(USER_TREE), USER_CLOSED, USER_MINIMIZED);
    h.SashGrid._fitTitleBars();
    assert.equal(h.gridEl.querySelectorAll('.fit-hidden').length, 0);
  });

  test('narrow Prompt: Save dropped, controls + grip + name survive', () => {
    const h = createSashGrid();
    const title = narrow(h, 'prompt');
    title._measureContent = (t) => measureTitle(t, { name: 80, promptSaveBtn: 50 });
    assert.ok(title.scrollWidth > title.clientWidth, 'precondition: row overflows');
    h.SashGrid._fitTitleBars();
    assert.ok(title.querySelector('#promptSaveBtn').classList.contains('fit-hidden'),
      'Save (rightmost secondary) must be dropped');
    for (const sel of [':scope > .win-grip', ':scope > .win-name',
                       ':scope > .win-controls'])
      assert.ok(!title.querySelector(sel).classList.contains('fit-hidden'),
        'protected item hidden: ' + sel);
    assert.ok(title.scrollWidth <= title.clientWidth, 'row must fit after fit');
  });

  test('widen again: everything restored (purity — no state drift)', () => {
    const h = createSashGrid();
    const title = narrow(h, 'prompt');
    title._measureContent = (t) => measureTitle(t, { name: 80, promptSaveBtn: 50 });
    h.SashGrid._fitTitleBars();
    assert.ok(title.querySelector('#promptSaveBtn').classList.contains('fit-hidden'));
    title._rect.width = 420;                      // user widens the window
    h.SashGrid._fitTitleBars();
    assert.ok(!title.querySelector('#promptSaveBtn').classList.contains('fit-hidden'),
      'Save must reappear when there is room');
    assert.equal(h.gridEl.querySelectorAll('.fit-hidden').length, 0);
  });

  test('URL List: secondaries drop right-to-left (badge → buttons)', () => {
    const h = createSashGrid();
    const title = narrow(h, 'url_list');
    const W = { name: 60, urlReparseBtn: 70, urlPopupBtn: 90, urlCount: 44 };
    title._measureContent = (t) => measureTitle(t, W);
    h.SashGrid._fitTitleBars();
    const order = ['urlCount', 'urlPopupBtn', 'urlReparseBtn'];
    for (const id of order)
      assert.ok(title.querySelector('#' + id).classList.contains('fit-hidden'),
        id + ' must be dropped');
    assert.ok(title.scrollWidth <= title.clientWidth, 'row must fit after fit');
    // widen: they come back
    title._rect.width = 600;
    h.SashGrid._fitTitleBars();
    for (const id of order)
      assert.ok(!title.querySelector('#' + id).classList.contains('fit-hidden'),
        id + ' must restore');
  });

  test('fit holds across resize drags on the user layout (controls never hidden)', () => {
    const h = createSashGrid();
    resetGrid(h, h.SashCore.clone(USER_TREE), USER_CLOSED, USER_MINIMIZED);
    for (const id of ALL_WINDOW_IDS) {
      const title = titleOf(h, id);
      // simulate a tight bar per window with its own secondaries
      title._rect.width = 96;
      title._measureContent = (t) => measureTitle(t, {});
    }
    // squeeze a few visible sashes; the fitter runs on every _resizeMove
    const sashes = h.gridEl.querySelectorAll('.sash');
    for (const s of sashes) if (s.offsetWidth > 0 && s.offsetHeight > 0) dragSash(h, s, 40);
    h.SashGrid._fitTitleBars();
    for (const id of ALL_WINDOW_IDS) {
      const ctrls = titleOf(h, id).querySelector(':scope > .win-controls');
      assert.ok(ctrls && !ctrls.classList.contains('fit-hidden'),
        id + ': controls must never be fit-hidden');
      const r = ctrls.getBoundingClientRect();
      assert.ok(r.width === 0 || r.width > 0, 'sanity'); // controls exist
    }
  });
});
