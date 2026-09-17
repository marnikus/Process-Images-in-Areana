/**
 * Tier A — regression tests for the 2026-09-17 watcher/grid bug fixes.
 * Runs the REAL sash-grid JS (facade + parts) under Node (no browser):
 *   bug 01: watcher window renders its panel (was a blank frame)
 *   bug 02: dragging a divider resizes ONLY its two adjacent rows, even when
 *           the split contains hidden (closed/minimized) children
 *   bug 04: sash visibility follows ONE rule (hidden iff previous sibling is
 *           hidden) after renders, close/open, minimize/restore, drops, resizes
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import {
  createSashGrid, resetGrid, rootSplit, childEls, sashesOf, winIdOf,
  dragSash, panelIdOf, ALL_WINDOW_IDS,
} from './sash_harness.mjs';
import { USER_TREE, USER_CLOSED, USER_MINIMIZED } from './user_layout.mjs';

const col = (SashCore, ids, sizes, closed = []) =>
  SashCore.split('col', ids.map((id) => SashCore.leaf(id)), sizes);

function sashRuleViolations(h) {
  const hidden = (el) => !!el && (el.classList.contains('sash-win-hidden') ||
    el.classList.contains('sash-win-closed') || el.classList.contains('sash-split-hidden'));
  const bad = [];
  const walk = (splitEl) => {
    const kids = splitEl.children;
    for (let i = 0; i < kids.length; i++) {
      const el = kids[i];
      if (el.classList.contains('sash')) {
        const expected = hidden(kids[i - 1]);
        if (el.classList.contains('sash-hidden') !== expected)
          bad.push(`sash idx=${el.dataset.idx} hidden=${el.classList.contains('sash-hidden')} expected=${expected}`);
      } else if (el.classList.contains('sash-split')) walk(el);
    }
  };
  walk(rootSplit(h));
  return bad;
}

/* real drop: cache rects, compute spec, apply, re-render */
function dropAt(h, dragId, x, y) {
  const g = h.SashGrid;
  g._drag = {
    active: true, id: dragId, startX: x, startY: y, lastX: x, lastY: y,
    clone: { classList: { contains: () => false }, style: {} },
    badge: { style: {}, textContent: '' }, indicator: { style: {} },
    rects: null, sashes: null, lastSpec: null, lastSpecKey: null, targetEl: null,
    gridRect: h.gridEl.getBoundingClientRect(), pointerCaptured: false,
  };
  g._cacheDragRects();
  const spec = g._computeSpec(x, y);
  g._cleanupDrag();
  if (!spec) return null;
  g._applyDrop(dragId, spec);
  g.render();
  h.layout();
  return spec;
}
function findWin(h, id) {
  return h.gridEl.querySelector('.sash-window[data-win="' + id + '"]');
}
function sashCenter(h, pred) {
  const s = h.gridEl.querySelectorAll('.sash').find(pred);
  if (!s) throw new Error('sash not found');
  const r = s.getBoundingClientRect();
  return { s, x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

describe('bug 01 — watcher window renders its panel', () => {
  test('every window keeps its panel inside its grid frame after render', () => {
    const h = createSashGrid(); // renders SashCore.defaultTree()
    h.layout();
    for (const id of ALL_WINDOW_IDS) {
      const wrap = findWin(h, id);
      assert.ok(wrap, `wrapper for ${id} missing`);
      const panel = wrap.querySelector(':scope > .panel');
      assert.ok(panel, `panel missing inside wrapper for ${id}`);
      assert.equal(panel.id, panelIdOf(id));
    }
    // the watcher panel must live inside #sashGrid (not be orphaned away)
    const watcher = document_id(h, 'winWatcher');
    assert.ok(watcher.isConnected, '#winWatcher must be in the DOM after render');
    assert.equal(findWin(h, 'watcher').querySelector(':scope > .panel'), watcher);
  });
});

function document_id(h, id) {
  const find = (n) => {
    if (n.id === id) return n;
    for (const c of n.children) { const r = find(c); if (r) return r; }
    return null;
  };
  return find(h.body);
}

describe('bug 02 — divider drag resizes only its two adjacent rows', () => {
  test('all-visible 4 rows: dragging each divider moves only the adjacent rows', () => {
    const h = createSashGrid();
    const ids = ['row_a', 'row_b', 'row_c', 'row_d'];
    resetGrid(h, col(h.SashCore, ids, [30, 25, 20, 25]));
    const split = rootSplit(h);
    for (const sIdx of [0, 1, 2]) {
      resetGrid(h, col(h.SashCore, ids, [30, 25, 20, 25]));
      const sash = sashesOf(rootSplit(h))[sIdx];
      const { before, after, model } = dragSash(h, sash, 60);
      for (let i = 0; i < 4; i++) {
        if (i === sIdx || i === sIdx + 1) continue;
        assert.ok(Math.abs(before[i] - after[i]) <= 0.5,
          `row ${i + 1} moved: ${before[i]} -> ${after[i]}`);
      }
      assert.ok(after[sIdx] - before[sIdx] > 50, 'upper row should grow');
      assert.ok(before[sIdx + 1] - after[sIdx + 1] > 50, 'lower row should shrink');
    }
  });

  test('hidden first child (user layout shape): every visible divider is safe', () => {
    const h = createSashGrid();
    const ids = ['browser', 'queue', 'log', 'watcher'];
    for (const sIdx of [1, 2]) { // sash 0 touches the hidden child
      resetGrid(h, col(h.SashCore, ids, [25, 25, 25, 25]), ['browser']);
      const sash = sashesOf(rootSplit(h))[sIdx];
      assert.ok(!sash.classList.contains('sash-hidden'), 'test sash must be visible');
      const { before, after, model } = dragSash(h, sash, 60);
      for (let i = 0; i < 4; i++) {
        if (i === sIdx || i === sIdx + 1) continue;
        assert.ok(Math.abs(before[i] - after[i]) <= 0.5,
          `row ${i + 1} moved: ${before[i]} -> ${after[i]}`);
      }
      // hidden child keeps its stored size; visible children sum to the rest
      assert.ok(Math.abs(model[0] - 25) < 0.01, 'hidden child size preserved');
      const visibleSum = [1, 2, 3].reduce((a, i) => a + model[i], 0);
      assert.ok(Math.abs(visibleSum - 75) < 0.01, 'visible children sum to 100 - hidden');
    }
  });

  test('hidden child in the middle: boundary sash skips it, no row drift', () => {
    const h = createSashGrid();
    const ids = ['a', 'b', 'c'];
    resetGrid(h, col(h.SashCore, ids, [30, 20, 50]), ['b']);
    // new sash rule: sash a|b (prev=a visible) is the draggable boundary
    const sash = sashesOf(rootSplit(h))[0];
    assert.ok(!sash.classList.contains('sash-hidden'), 'boundary sash must be visible');
    const { before, after, model } = dragSash(h, sash, 40);
    // invisible b occupies no space: a grows, the next VISIBLE row (c) gives it
    assert.ok(after[0] - before[0] > 30, `row a should grow: ${before[0]} -> ${after[0]}`);
    assert.ok(before[2] - after[2] > 30, `row c should give the space: ${before[2]} -> ${after[2]}`);
    // and no jump on re-render: dragged px are what the model stores
    assert.ok(Math.abs((after[0] - before[0]) - (before[2] - after[2])) <= 1, 'a/c must trade space 1:1');
    assert.ok(Math.abs(model[1] - 20) < 0.01, 'hidden row b model size preserved');
    assert.ok(Math.abs(model[0] + model[1] + model[2] - 100) < 0.01, 'sizes still sum to 100');
  });

  test('user real layout: dragging the queue|watcher divider is safe', () => {
    const h = createSashGrid();
    resetGrid(h, h.SashCore.clone(USER_TREE), USER_CLOSED, USER_MINIMIZED);
    const sashEl = h.gridEl.querySelectorAll('.sash')
      .find((s) => {
        if (s.classList.contains('sash-hidden')) return false;
        const p = s.parentElement;
        const l = winIdOf(p.children[+s.dataset.idx * 2]);
        const r = winIdOf(p.children[+s.dataset.idx * 2 + 2]);
        return l === 'queue' && r === 'watcher';
      });
    assert.ok(sashEl, 'queue|watcher sash must exist and be visible');
    const split = sashEl.parentElement;
    const before = childEls(split).map((c) => c.getBoundingClientRect().height);
    dragSash(h, sashEl, 40);
    const after = childEls(split).map((c) => c.getBoundingClientRect().height);
    const idx = parseInt(sashEl.dataset.idx, 10);
    for (let i = 0; i < before.length; i++) {
      if (i === idx || i === idx + 1) continue;
      assert.ok(Math.abs(before[i] - after[i]) <= 0.5,
        `sibling ${i} moved: ${before[i]} -> ${after[i]}`);
    }
  });
});

describe('bug 04 — sash visibility follows one rule after operations', () => {
  test('rule holds across close/open/minimize/restore/drop/resize on user layout', () => {
    const h = createSashGrid();
    resetGrid(h, h.SashCore.clone(USER_TREE), USER_CLOSED, USER_MINIMIZED);
    const ops = [
      () => sashRuleViolations(h),
      () => { h.SashGrid.openWindow('browser'); return sashRuleViolations(h); },
      () => { h.SashGrid.closeWindow('browser'); return sashRuleViolations(h); },
      () => { h.SashGrid.minimizeWindow('queue'); return sashRuleViolations(h); },
      () => { h.SashGrid.restoreMinimized('queue'); return sashRuleViolations(h); },
      () => { h.SashGrid.minimizeWindow('log'); h.SashGrid.closeWindow('watcher'); return sashRuleViolations(h); },
      () => { h.SashGrid.openWindow('watcher'); h.SashGrid.restoreMinimized('log'); return sashRuleViolations(h); },
      () => {
        // drop 'log' onto the queue|watcher sash
        resetGrid(h, h.SashCore.clone(USER_TREE), USER_CLOSED, USER_MINIMIZED);
        const { x, y } = sashCenter(h, (s) => {
          if (s.classList.contains('sash-hidden')) return false;
          const p = s.parentElement;
          return winIdOf(p.children[+s.dataset.idx * 2]) === 'queue' &&
            winIdOf(p.children[+s.dataset.idx * 2 + 2]) === 'watcher';
        });
        const spec = dropAt(h, 'log', x, y);
        assert.ok(spec && spec.kind === 'sash', 'drop must land on the sash');
        return sashRuleViolations(h);
      },
      () => {
        // resize a random visible sash, then check the rule
        const s = h.gridEl.querySelectorAll('.sash').find((x2) =>
          !x2.classList.contains('sash-hidden') && x2.offsetHeight > 0 && x2.offsetWidth > 0);
        dragSash(h, s, 30);
        return sashRuleViolations(h);
      },
    ];
    for (const op of ops) {
      assert.deepEqual(op(), [], 'sash rule violated');
    }
  });

  test('hidden window between two visible windows keeps a visible boundary sash', () => {
    const h = createSashGrid();
    const ids = ['run', 'queue', 'log', 'browser'];
    resetGrid(h, col(h.SashCore, ids, [30, 20, 25, 25]), ['queue']);
    const sashes = sashesOf(rootSplit(h));
    assert.ok(!sashes[0].classList.contains('sash-hidden'),
      'sash run|queue (prev visible) must stay visible — draggable boundary');
    assert.ok(sashes[1].classList.contains('sash-hidden'),
      'sash queue|log (prev hidden) must be hidden');
    // drop another window onto the boundary sash: boundary must still exist
    const { x, y } = sashCenter(h, (s) => !s.classList.contains('sash-hidden'));
    const spec = dropAt(h, 'browser', x, y);
    assert.ok(spec, 'drop landed');
    assert.deepEqual(sashRuleViolations(h), [], 'rule holds after drop');
    const split = rootSplit(h);
    // every adjacent visible pair must have a visible sash between it
    const kids = childEls(split).map(winIdOf);
    for (let i = 0; i < kids.length - 1; i++) {
      const visiblePair = !split.children[i * 2].classList.contains('sash-win-hidden') &&
        !split.children[(i + 1) * 2].classList.contains('sash-win-hidden');
      const sashVisible = !split.children[i * 2 + 1].classList.contains('sash-hidden');
      if (visiblePair) assert.ok(sashVisible, `missing sash between ${kids[i]} and ${kids[i + 1]}`);
    }
  });
});
