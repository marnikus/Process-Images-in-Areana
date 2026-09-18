/* sash-core.js — Arena Image Processor grid model
   Reuses old logic but with arena-specific windows.
   Based on Old App sash-core.js, trimmed to our window set.
*/

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SashCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const WINDOWS = [
    { id: 'url_list', title: 'URL List' },
    { id: 'folder',   title: 'Folder Picker' },
    { id: 'queue',    title: 'Image Queue' },
    { id: 'prompt',   title: 'Prompt Editor' },
    { id: 'run',      title: 'Run Controls' },
    { id: 'progress', title: 'Progress' },
    { id: 'watcher',  title: 'Watcher — Generation & Captcha' },
    { id: 'log',      title: 'Activity Log' },
    { id: 'settings', title: 'Settings' },
    { id: 'captcha',  title: 'Captcha — 2Captcha Control' },
    { id: 'browser',  title: 'Browser Preview' },
    { id: 'action_blocks', title: 'Action Blocks — Stacking Jobs' },
    { id: 'block_config', title: 'Block Config — Security Check' },
    { id: 'arena_presets', title: 'Arena Presets' },
    { id: 'recordings', title: 'Recordings — Captcha Sessions' },
  ];
  const V1_WINDOW_IDS = WINDOWS.map(w=>w.id);
  const V2_WINDOW_IDS = V1_WINDOW_IDS;
  const V3_WINDOW_IDS = V1_WINDOW_IDS;
  const VERSION = 5;
  const WINDOW_IDS = WINDOWS.map((w) => w.id);
  const WINDOW_TITLES = Object.fromEntries(WINDOWS.map((w) => [w.id, w.title]));

  const MAX_DEPTH = 12;
  const MIN_SIZE = 4;

  const leaf = (id) => ({ t: 'leaf', id });

  function split(dir, children, sizes) {
    if (dir !== 'row' && dir !== 'col') throw new Error('bad split dir: ' + dir);
    if (!Array.isArray(children) || children.length < 2)
      throw new Error('split needs at least 2 children');
    if (!Array.isArray(sizes) || sizes.length !== children.length)
      throw new Error('split sizes must match children');
    return { t: 'split', dir, children, sizes: normalizeSizes(sizes) };
  }

  const clone = (node) => JSON.parse(JSON.stringify(node));

  function defaultTree() {
    return split('col', [
      split('row', [
        split('col', [leaf('url_list'), leaf('folder')], [55, 45]),
        split('col', [leaf('prompt'), leaf('run'), leaf('settings'), leaf('captcha')], [40, 22, 26, 12]),
      ], [60, 40]),
      split('row', [
        leaf('queue'),
        split('col', [leaf('action_blocks'), leaf('block_config')], [55, 45]),
        split('col', [leaf('browser'), leaf('arena_presets'), leaf('recordings'), leaf('progress'), leaf('watcher')], [24, 20, 20, 18, 18]),
      ], [45, 35, 20]),
      leaf('log'),
    ], [38, 40, 22]);
  }

  function layoutA() {
    return split('col', [
      leaf('url_list'), leaf('folder'), leaf('queue'),
      leaf('prompt'), leaf('run'), leaf('progress'), leaf('watcher'),
      leaf('log'), leaf('settings'), leaf('captcha'), leaf('browser'),
      leaf('action_blocks'), leaf('block_config'), leaf('arena_presets'),
      leaf('recordings'),
    ], [8, 5, 13, 10, 6, 6, 6, 6, 5, 5, 5, 6, 6, 9, 8]);
  }

  function layoutB() {
    return split('row', [
      split('col', [leaf('url_list'), leaf('folder'), leaf('queue'), leaf('action_blocks'), leaf('recordings')], [22, 14, 30, 20, 14]),
      split('col', [leaf('prompt'), leaf('block_config'), leaf('progress'), leaf('watcher'), leaf('log')], [25, 20, 15, 20, 20]),
      split('col', [leaf('browser'), leaf('settings'), leaf('captcha'), leaf('arena_presets'), leaf('run')], [35, 16, 16, 17, 16]),
    ], [35, 35, 30]);
  }

  function layoutC() {
    return split('col', [
      split('row', [
        split('col', [leaf('url_list'), leaf('prompt'), leaf('action_blocks')], [35, 35, 30]),
        split('col', [leaf('block_config'), leaf('browser')], [45, 55]),
      ], [45, 55]),
      split('row', [
        leaf('queue'),
        split('col', [leaf('folder'), leaf('run'), leaf('settings'), leaf('captcha'), leaf('progress'), leaf('watcher'), leaf('arena_presets'), leaf('recordings')], [13, 13, 15, 15, 12, 12, 11, 9]),
      ], [60, 40]),
      leaf('log'),
    ], [35, 48, 17]);
  }

  const PRESETS = {
    default: defaultTree,
    a: layoutA,
    b: layoutB,
    c: layoutC,
  };

  function normalizeSizes(sizes) {
    if (!Array.isArray(sizes) || !sizes.length) return sizes;
    const base = sizes.map((s) => {
      const n = Number(s);
      return Number.isFinite(n) && n > 0 ? n : MIN_SIZE;
    });
    const sum = base.reduce((a, b) => a + b, 0) || 1;
    if (Math.abs(sum - 100) < 1e-9 && base.every((s) => s >= MIN_SIZE)) return base;
    const scaled = base.map((s) => (s / sum) * 100);
    if (scaled.every((s) => s >= MIN_SIZE)) return scaled;
    const floorTotal = MIN_SIZE * base.length;
    if (floorTotal >= 100) return base.map(() => 100 / base.length);
    const excess = base.map((s) => Math.max(0, s - MIN_SIZE));
    const excessTotal = excess.reduce((a, b) => a + b, 0);
    const remaining = 100 - floorTotal;
    if (!excessTotal) return base.map(() => 100 / base.length);
    return excess.map((s) => MIN_SIZE + (s / excessTotal) * remaining);
  }

  function isLeaf(node) { return node && node.t === 'leaf'; }
  function isSplit(node) { return node && node.t === 'split'; }

  function firstLeafId(node) {
    if (isLeaf(node)) return node.id;
    return firstLeafId(node.children[0]);
  }

  function forEachLeaf(root, cb) {
    const walk = (node, parent, index) => {
      if (isLeaf(node)) { if (cb(node, parent, index) === false) return; return; }
      if (isSplit(node)) node.children.forEach((c, i) => walk(c, node, i));
    };
    walk(root, null, -1);
  }

  const leafIds = (root) => {
    const out = [];
    forEachLeaf(root, (l) => out.push(l.id));
    return out;
  };

  function findNode(root, id) {
    let found = null;
    forEachLeaf(root, (node, parent, index) => {
      if (node.id === id) { found = { node, parent, index }; return false; }
      return true;
    });
    return found;
  }

  const parentSplit = (root, id) => {
    const f = findNode(root, id);
    return f ? f.parent : null;
  };

  function splitLeaf(root, targetId, newId, dir, newFirst) {
    const f = findNode(root, targetId);
    if (!f) throw new Error('splitLeaf: unknown window ' + targetId);
    const newSplit = split(dir,
      newFirst ? [leaf(newId), f.node] : [f.node, leaf(newId)],
      [50, 50]);
    if (f.parent) f.parent.children[f.index] = newSplit;
    else root = newSplit;
    return root;
  }

  function insertAtSplitIndex(root, refChildId, index, newId, donorId) {
    const f = findNode(root, refChildId);
    if (!f || !f.parent)
      throw new Error('insertAtSplitIndex: ' + refChildId + ' has no parent split');
    const p = f.parent;
    if (!Number.isInteger(index) || index < 0 || index > p.children.length)
      throw new Error('insertAtSplitIndex: bad index ' + index);
    let donorIdx;
    if (donorId) {
      const d = findNode(root, donorId);
      if (!d || d.parent !== p)
        throw new Error('insertAtSplitIndex: donor not in this split');
      donorIdx = d.index;
      if (donorIdx !== index && donorIdx !== index - 1)
        throw new Error('insertAtSplitIndex: donor not adjacent to the gap');
    } else {
      donorIdx = index > 0 ? index - 1 : 0;
    }
    const half = p.sizes[donorIdx] / 2;
    p.children.splice(index, 0, leaf(newId));
    p.sizes.splice(index, 0, half);
    p.sizes[donorIdx >= index ? donorIdx + 1 : donorIdx] = half;
    p.sizes = normalizeSizes(p.sizes);
    return root;
  }

  function insertSibling(root, targetId, newId, side) {
    const f = findNode(root, targetId);
    if (!f) throw new Error('insertSibling: unknown window ' + targetId);
    if (!f.parent)
      return splitLeaf(root, targetId, newId, 'row', side !== 'after');
    const pos = side === 'before' ? f.index : f.index + 1;
    return insertAtSplitIndex(root, targetId, pos, newId, targetId);
  }

  function insertBetween(root, leftId, newId) {
    const f = findNode(root, leftId);
    if (!f || !f.parent)
      throw new Error('insertBetween: ' + leftId + ' has no sibling');
    const p = f.parent;
    if (f.index >= p.children.length - 1)
      throw new Error('insertBetween: ' + leftId + ' is the last child');
    const rightId = firstLeafId(p.children[f.index + 1]);
    return insertAtSplitIndex(root, leftId, f.index + 1, newId, rightId);
  }

  function setSplitSizes(root, childId, sizes) {
    const f = findNode(root, childId);
    if (!f || !f.parent) throw new Error('setSplitSizes: no parent split for ' + childId);
    if (sizes.length !== f.parent.children.length)
      throw new Error('setSplitSizes: size count mismatch');
    f.parent.sizes = normalizeSizes(sizes);
    return root;
  }

  function normalizePath(p) {
    if (Array.isArray(p)) return p.map(Number);
    return String(p == null ? '' : p).split('-').filter((s) => s !== '').map(Number);
  }

  function nodeAtPath(root, path) {
    let n = root;
    for (const i of normalizePath(path)) {
      if (!isSplit(n) || !Array.isArray(n.children) || !n.children[i]) return null;
      n = n.children[i];
    }
    return n;
  }

  function insertAtSplitPath(root, splitPath, index, newId, donorIdx) {
    const p = nodeAtPath(root, splitPath);
    if (!p || !isSplit(p))
      throw new Error('insertAtSplitPath: no split at path ' + JSON.stringify(splitPath));
    if (!Number.isInteger(index) || index < 0 || index > p.children.length)
      throw new Error('insertAtSplitPath: bad index ' + index);
    if (!Number.isInteger(donorIdx) || donorIdx < 0 || donorIdx >= p.children.length)
      throw new Error('insertAtSplitPath: bad donor index ' + donorIdx);
    if (donorIdx !== index && donorIdx !== index - 1)
      throw new Error('insertAtSplitPath: donor not adjacent to the gap');
    const half = p.sizes[donorIdx] / 2;
    p.children.splice(index, 0, leaf(newId));
    p.sizes.splice(index, 0, half);
    p.sizes[donorIdx >= index ? donorIdx + 1 : donorIdx] = half;
    p.sizes = normalizeSizes(p.sizes);
    return root;
  }

  function setSplitSizesByPath(root, splitPath, sizes) {
    const p = nodeAtPath(root, splitPath);
    if (!p || !isSplit(p))
      throw new Error('setSplitSizesByPath: no split at path ' + JSON.stringify(splitPath));
    if (!Array.isArray(sizes) || sizes.length !== p.children.length)
      throw new Error('setSplitSizesByPath: size count mismatch');
    p.sizes = normalizeSizes(sizes);
    return root;
  }

  function parentPath(root, leafId) {
    let out = null;
    const walk = (node, path) => {
      if (out) return;
      if (isSplit(node)) node.children.forEach((c, i) => walk(c, path.concat(i)));
      else if (isLeaf(node) && node.id === leafId) out = path.slice(0, -1);
    };
    walk(root, []);
    return out;
  }

  function leafPaths(root) {
    const out = {};
    const walk = (node, path) => {
      if (isLeaf(node)) { out[node.id] = path; return; }
      node.children.forEach((c, i) => walk(c, path.concat(i)));
    };
    walk(root, []);
    return out;
  }

  function removeNode(root, node) {
    const removeFrom = (n) => {
      if (n === node) return undefined;
      if (isLeaf(n)) return n;
      for (let i = 0; i < n.children.length; i++) {
        const res = removeFrom(n.children[i]);
        if (res === undefined) {
          n.children.splice(i, 1);
          n.sizes.splice(i, 1);
          if (n.children.length === 1) return n.children[0];
          n.sizes = normalizeSizes(n.sizes);
          return n;
        }
        n.children[i] = res;
      }
      return n;
    };
    const res = removeFrom(root);
    if (res === undefined) throw new Error('removeNode: node not in tree');
    return res;
  }

  function removeLeaf(root, id) {
    const f = findNode(root, id);
    if (!f) throw new Error('removeLeaf: unknown window ' + id);
    return removeNode(root, f.node);
  }

  function insertOuter(root, newId, side) {
    const isTop = side === 'top', isBottom = side === 'bottom';
    const isLeft = side === 'left', isRight = side === 'right';
    const wantCol = isTop || isBottom;
    const wantDir = wantCol ? 'col' : 'row';
    const newFirst = isTop || isLeft;

    if (isLeaf(root)) {
      return split(wantDir, newFirst ? [leaf(newId), root] : [root, leaf(newId)], [20, 80]);
    }
    if (isSplit(root) && root.dir === wantDir) {
      const idx = newFirst ? 0 : root.children.length;
      const donorIdx = newFirst ? 0 : root.children.length - 1;
      const half = root.sizes[donorIdx] / 2;
      root.children.splice(idx, 0, leaf(newId));
      root.sizes.splice(idx, 0, half);
      const donorPos = donorIdx >= idx ? donorIdx + 1 : donorIdx;
      root.sizes[donorPos] = half;
      root.sizes = normalizeSizes(root.sizes);
      return root;
    }
    return split(wantDir, newFirst ? [leaf(newId), root] : [root, leaf(newId)], newFirst ? [20, 80] : [80, 20]);
  }

  function moveWindow(root, draggedId, drop) {
    if (drop.target && drop.target === draggedId)
      throw new Error('moveWindow: dropping a window on itself');
    const orig = findNode(root, draggedId);
    if (!orig) throw new Error('moveWindow: unknown window ' + draggedId);
    const origNode = orig.node;

    if (drop.kind === 'outer') {
      const side = drop.side;
      if (!['top', 'bottom', 'left', 'right'].includes(side))
        throw new Error('moveWindow: bad outer side ' + side);
      const without = removeNode(root, origNode);
      return insertOuter(without, draggedId, side);
    }

    if (drop.kind === 'edge') {
      root = splitLeaf(root, drop.target, draggedId, drop.dir, drop.newFirst);
    } else if (drop.kind === 'sibling') {
      const f = findNode(root, drop.target);
      if (!f) throw new Error('moveWindow: unknown target ' + drop.target);
      if (!f.parent) {
        root = splitLeaf(root, drop.target, draggedId, 'row', drop.side !== 'after');
      } else {
        const pos = drop.side === 'before' ? f.index : f.index + 1;
        root = insertAtSplitIndex(root, drop.target, pos, draggedId, drop.target);
      }
    } else if (drop.kind === 'sash') {
      const paths = leafPaths(root);
      const a = paths[drop.left], b = paths[drop.right];
      if (!a || !b)
        throw new Error('moveWindow: sash anchors not found (' + drop.left + '/' + drop.right + ')');
      let k = 0;
      while (k < a.length && k < b.length && a[k] === b[k]) k++;
      const lca = nodeAtPath(root, a.slice(0, k));
      const iA = a[k], iB = b[k];
      if (!lca || !isSplit(lca) || Math.abs(iA - iB) !== 1)
        throw new Error('moveWindow: sash anchors not adjacent');
      const insertIdx = Math.max(iA, iB);
      const half = lca.sizes[insertIdx] / 2;
      lca.children.splice(insertIdx, 0, leaf(draggedId));
      lca.sizes.splice(insertIdx, 0, half);
      lca.sizes[insertIdx + 1] = half;
      lca.sizes = normalizeSizes(lca.sizes);
    } else {
      throw new Error('moveWindow: unknown drop kind ' + drop.kind);
    }

    return removeNode(root, origNode);
  }

  function validate(root, expectedIds) {
    const expect = (expectedIds || WINDOW_IDS).slice().sort();
    const check = (node, depth) => {
      if (depth > MAX_DEPTH) return 'tree too deep';
      if (isLeaf(node)) {
        if (typeof node.id !== 'string' || !node.id) return 'leaf without id';
        return null;
      }
      if (!isSplit(node)) return 'unknown node type';
      if (node.dir !== 'row' && node.dir !== 'col') return 'bad dir';
      if (!Array.isArray(node.children) || node.children.length < 2)
        return 'split needs ≥2 children';
      if (!Array.isArray(node.sizes) || node.sizes.length !== node.children.length)
        return 'sizes must match children';
      for (const s of node.sizes)
        if (!Number.isFinite(s) || s < MIN_SIZE)
          return 'bad size value (panel below minimum size)';
      const sum = node.sizes.reduce((a, b) => a + b, 0);
      if (sum < 99.5 || sum > 100.5) return 'sizes must sum to 100 (got ' + sum + ')';
      for (const c of node.children) {
        const err = check(c, depth + 1);
        if (err) return err;
      }
      return null;
    };
    const err = check(root, 0);
    if (err) return err;
    const got = leafIds(root).slice().sort();
    if (got.length !== expect.length) return 'leaf count mismatch';
    for (let i = 0; i < expect.length; i++)
      if (got[i] !== expect[i]) return 'leaf id mismatch (' + got[i] + ' ≠ ' + expect[i] + ')';
    return null;
  }

  /* Legacy ids for windows this app renamed. `captcha_records` (the parallel
     recording window of 2026-09-18) is the same feature as `recordings`, so a
     stored layout keeps its position + sizes instead of being rejected. */
  const LEGACY_WINDOW_IDS = { captcha_records: 'recordings' };
  const legacyId = (id) => LEGACY_WINDOW_IDS[id] || id;

  function pruneTree(node, seen, allowed) {
    seen = seen || new Set();
    allowed = allowed || new Set(WINDOW_IDS);
    if (isLeaf(node)) {
      if (typeof node.id !== 'string') return null;
      const id = legacyId(node.id);
      if (!allowed.has(id)) return null;
      if (seen.has(id)) return null;
      seen.add(id);
      return leaf(id);
    }
    if (!isSplit(node) || !Array.isArray(node.children)) return null;
    const kids = [], sizes = [];
    node.children.forEach((child, i) => {
      const kept = pruneTree(child, seen, allowed);
      if (!kept) return;
      kids.push(kept);
      const size = Array.isArray(node.sizes) ? Number(node.sizes[i]) : NaN;
      sizes.push(Number.isFinite(size) && size > 0 ? size : MIN_SIZE);
    });
    if (!kids.length) return null;
    if (kids.length === 1) return kids[0];
    return { t: 'split', dir: node.dir === 'col' ? 'col' : 'row',
             children: kids, sizes: normalizeSizes(sizes) };
  }

  function evenSizes(count) {
    const base = Math.floor(100 / count);
    const out = new Array(count).fill(base);
    out[0] += 100 - base * count;
    return out;
  }

  function migrate(tree) {
    const pruned = pruneTree(tree);
    if (!pruned || !isSplit(pruned)) return defaultTree();
    const present = new Set(leafIds(pruned));
    const missing = WINDOW_IDS.filter((id) => !present.has(id));
    if (!missing.length) return validate(pruned) ? defaultTree() : pruned;
    const extra = missing.length === 1
      ? leaf(missing[0])
      : { t: 'split', dir: 'row', children: missing.map(leaf),
          sizes: evenSizes(missing.length) };
    const share = Math.min(40, Math.max(MIN_SIZE, missing.length * 9));
    const out = { t: 'split', dir: 'col', children: [pruned, extra],
                  sizes: [100 - share, share] };
    return validate(out) ? defaultTree() : out;
  }

  const serialize = (tree) => JSON.stringify({ v: VERSION, tree });

  function deserialize(str, expectedIds) {
    let obj;
    try {
      obj = JSON.parse(str);
    } catch (e) {
      return { ok: false, error: 'unparseable: ' + e.message };
    }
    const versioned = obj && typeof obj === 'object' && !obj.t;
    const version = versioned ? obj.v : 1;
    const tree = versioned ? obj.tree : obj;
    if (!Number.isInteger(version) || version < 1 || version > VERSION)
      return { ok: false, error: 'unsupported layout version ' + version };
    if (version === VERSION) {
      const err = validate(tree, expectedIds);
      if (!err) return { ok: true, tree: clone(tree) };
      // If leaf mismatch, try to migrate (handles old 9-window layouts -> 11)
      if (err.includes('leaf') || err.includes('mismatch')) {
        try {
          const migrated = migrate(tree);
          const err2 = validate(migrated, expectedIds);
          if (!err2) return { ok: true, tree: migrated, migrated: true };
          console.warn('Migrate after mismatch still failed', err2, 'returning default');
          return { ok: true, tree: defaultTree(), migrated: true };
        } catch (e) {
          console.warn('Migrate failed', e, 'returning default');
          return { ok: true, tree: defaultTree(), migrated: true };
        }
      }
      return { ok: false, error: err };
    }
    const structural = validate(tree, leafIds(tree));
    if (structural) return { ok: false, error: structural };
    const upgraded = migrate(tree);
    const err = validate(upgraded, expectedIds);
    return err ? { ok: false, error: err }
               : { ok: true, tree: upgraded, migrated: true };
  }

  return {
    WINDOWS, WINDOW_IDS, WINDOW_TITLES, V1_WINDOW_IDS, V2_WINDOW_IDS,
    V3_WINDOW_IDS, VERSION,
    MAX_DEPTH, MIN_SIZE, pruneTree, migrate,
    leaf, split, clone, firstLeafId,
    defaultTree, layoutA, layoutB, layoutC, PRESETS,
    normalizeSizes,
    isLeaf, isSplit, forEachLeaf, leafIds, findNode, parentSplit,
    splitLeaf, insertAtSplitIndex, insertSibling, insertBetween,
    setSplitSizes,
    normalizePath, nodeAtPath, insertAtSplitPath, setSplitSizesByPath,
    parentPath, leafPaths, removeLeaf, moveWindow,
    validate, serialize, deserialize,
  };
});
