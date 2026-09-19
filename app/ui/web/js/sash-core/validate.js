/* sash-core/validate.js — validation, prune, migrate (C7) */
'use strict';

function sashEvenSizes(count) {
  const base = Math.floor(100 / count);
  const out = new Array(count).fill(base);
  out[0] += 100 - base * count;
  return out;
}

function sashCheckLeaf(node) {
  if (typeof node.id !== 'string' || !node.id) return 'leaf without id';
  return null;
}

function sashCheckSplitDir(node) {
  if (node.dir !== 'row' && node.dir !== 'col') return 'bad dir';
  return null;
}

function sashCheckSplitChildren(node) {
  if (!Array.isArray(node.children) || node.children.length < 2) return 'split needs ≥2 children';
  if (!Array.isArray(node.sizes) || node.sizes.length !== node.children.length) return 'sizes must match children';
  return null;
}

function sashCheckSplitSizes(node, minSize) {
  for (const s of node.sizes) if (!Number.isFinite(s) || s < minSize) return 'bad size value';
  const sum = node.sizes.reduce((a, b) => a + b, 0);
  if (sum < 99.5 || sum > 100.5) return 'sizes must sum to 100 (got ' + sum + ')';
  return null;
}

function sashCheckNode(node, depth, maxDepth, minSize) {
  if (depth > maxDepth) return 'tree too deep';
  if (window.SashCoreTraverse.isLeaf(node)) return sashCheckLeaf(node);
  if (!window.SashCoreTraverse.isSplit(node)) return 'unknown node type';
  const dirErr = sashCheckSplitDir(node);
  if (dirErr) return dirErr;
  const childErr = sashCheckSplitChildren(node);
  if (childErr) return childErr;
  const sizeErr = sashCheckSplitSizes(node, minSize);
  if (sizeErr) return sizeErr;
  for (const c of node.children) {
    const err = sashCheckNode(c, depth + 1, maxDepth, minSize);
    if (err) return err;
  }
  return null;
}

function sashValidate(root, expectedIds) {
  const C = window.SashCoreConstants;
  const expect = (expectedIds || C.WINDOW_IDS).slice().sort();
  const err = sashCheckNode(root, 0, C.MAX_DEPTH, C.MIN_SIZE);
  if (err) return err;
  const got = window.SashCoreTraverse.leafIds(root).slice().sort();
  if (got.length !== expect.length) return 'leaf count mismatch';
  for (let i = 0; i < expect.length; i++) if (got[i] !== expect[i]) return 'leaf id mismatch (' + got[i] + ' ≠ ' + expect[i] + ')';
  return null;
}

function sashPruneLeaf(node, seen, allowed) {
  if (typeof node.id !== 'string' || !allowed.has(node.id)) return null;
  if (seen.has(node.id)) return null;
  seen.add(node.id);
  return window.SashCoreTree.leaf(node.id);
}

function sashPruneSplit(node, seen, allowed) {
  if (!window.SashCoreTraverse.isSplit(node) || !Array.isArray(node.children)) return null;
  const kids = [], sizes = [];
  node.children.forEach((child, i) => {
    const kept = sashPruneTree(child, seen, allowed);
    if (!kept) return;
    kids.push(kept);
    const size = Array.isArray(node.sizes) ? Number(node.sizes[i]) : NaN;
    sizes.push(Number.isFinite(size) && size > 0 ? size : window.SashCoreConstants.MIN_SIZE);
  });
  if (!kids.length) return null;
  if (kids.length === 1) return kids[0];
  return { t: 'split', dir: node.dir === 'col' ? 'col' : 'row', children: kids, sizes: window.SashCoreTree.normalizeSizes(sizes) };
}

function sashPruneTree(node, seen, allowed) {
  const C = window.SashCoreConstants;
  seen = seen || new Set();
  allowed = allowed || new Set(C.WINDOW_IDS);
  if (window.SashCoreTraverse.isLeaf(node)) return sashPruneLeaf(node, seen, allowed);
  return sashPruneSplit(node, seen, allowed);
}

function sashMigrateMissing(pruned, missing) {
  const C = window.SashCoreConstants;
  const extra = missing.length === 1 ? window.SashCoreTree.leaf(missing[0]) : { t: 'split', dir: 'row', children: missing.map(window.SashCoreTree.leaf), sizes: sashEvenSizes(missing.length) };
  const share = Math.min(40, Math.max(C.MIN_SIZE, missing.length * 9));
  return { t: 'split', dir: 'col', children: [pruned, extra], sizes: [100 - share, share] };
}

function sashMigrate(tree) {
  const pruned = sashPruneTree(tree);
  if (!pruned || !window.SashCoreTraverse.isSplit(pruned)) return window.SashCoreTree.defaultTree();
  const present = new Set(window.SashCoreTraverse.leafIds(pruned));
  const missing = window.SashCoreConstants.WINDOW_IDS.filter(id => !present.has(id));
  if (!missing.length) return sashValidate(pruned) ? window.SashCoreTree.defaultTree() : pruned;
  const out = sashMigrateMissing(pruned, missing);
  return sashValidate(out) ? window.SashCoreTree.defaultTree() : out;
}

function sashSerialize(tree) {
  return JSON.stringify({ v: window.SashCoreConstants.VERSION, tree });
}

function sashParseJson(str) {
  try { return { ok: true, obj: JSON.parse(str) }; }
  catch (e) { return { ok: false, error: 'unparseable: ' + e.message }; }
}

function sashDeserializeVersioned(obj, expectedIds) {
  const version = obj.v;
  const tree = obj.tree;
  const C = window.SashCoreConstants;
  if (!Number.isInteger(version) || version < 1 || version > C.VERSION) return { ok: false, error: 'unsupported version ' + version };
  if (version !== C.VERSION) return null;
  const err = sashValidate(tree, expectedIds);
  if (!err) return { ok: true, tree: window.SashCoreTree.clone(tree) };
  if (!err.includes('leaf') && !err.includes('mismatch')) return { ok: false, error: err };
  try {
    const migrated = sashMigrate(tree);
    const err2 = sashValidate(migrated, expectedIds);
    if (!err2) return { ok: true, tree: migrated, migrated: true };
    return { ok: true, tree: window.SashCoreTree.defaultTree(), migrated: true };
  } catch {
    return { ok: true, tree: window.SashCoreTree.defaultTree(), migrated: true };
  }
}

function sashDeserializeLegacy(tree, expectedIds) {
  const structural = sashValidate(tree, window.SashCoreTraverse.leafIds(tree));
  if (structural) return { ok: false, error: structural };
  const upgraded = sashMigrate(tree);
  const err = sashValidate(upgraded, expectedIds);
  return err ? { ok: false, error: err } : { ok: true, tree: upgraded, migrated: true };
}

function sashDeserialize(str, expectedIds) {
  const parsed = sashParseJson(str);
  if (!parsed.ok) return parsed;
  const obj = parsed.obj;
  const versioned = obj && typeof obj === 'object' && !obj.t;
  if (versioned) {
    const res = sashDeserializeVersioned(obj, expectedIds);
    if (res) return res;
    return sashDeserializeLegacy(obj.tree, expectedIds);
  }
  return sashDeserializeLegacy(obj, expectedIds);
}

window.SashCoreValidate = {
  validate: sashValidate,
  pruneTree: sashPruneTree,
  migrate: sashMigrate,
  serialize: sashSerialize,
  deserialize: sashDeserialize,
  evenSizes: sashEvenSizes,
};
