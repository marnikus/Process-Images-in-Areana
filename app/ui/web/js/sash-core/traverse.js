/* sash-core/traverse.js — traversal helpers (C7) */
'use strict';

function sashIsLeaf(node) { return node && node.t === 'leaf'; }
function sashIsSplit(node) { return node && node.t === 'split'; }

function sashFirstLeafId(node) {
  if (sashIsLeaf(node)) return node.id;
  return sashFirstLeafId(node.children[0]);
}

function sashForEachLeaf(root, cb) {
  const walk = (node, parent, index) => {
    if (sashIsLeaf(node)) { if (cb(node, parent, index) === false) return; return; }
    if (sashIsSplit(node)) node.children.forEach((c, i) => walk(c, node, i));
  };
  walk(root, null, -1);
}

function sashLeafIds(root) {
  const out = [];
  sashForEachLeaf(root, l => out.push(l.id));
  return out;
}

function sashFindNode(root, id) {
  let found = null;
  sashForEachLeaf(root, (node, parent, index) => {
    if (node.id === id) { found = { node, parent, index }; return false; }
    return true;
  });
  return found;
}

function sashParentSplit(root, id) {
  const f = sashFindNode(root, id);
  return f ? f.parent : null;
}

function sashNormalizePath(p) {
  if (Array.isArray(p)) return p.map(Number);
  return String(p == null ? '' : p).split('-').filter(s => s !== '').map(Number);
}

function sashNodeAtPath(root, path) {
  let n = root;
  for (const i of sashNormalizePath(path)) {
    if (!sashIsSplit(n) || !n.children[i]) return null;
    n = n.children[i];
  }
  return n;
}

function sashParentPath(root, leafId) {
  let out = null;
  const walk = (node, path) => {
    if (out) return;
    if (sashIsSplit(node)) node.children.forEach((c, i) => walk(c, path.concat(i)));
    else if (sashIsLeaf(node) && node.id === leafId) out = path.slice(0, -1);
  };
  walk(root, []);
  return out;
}

function sashLeafPaths(root) {
  const out = {};
  const walk = (node, path) => {
    if (sashIsLeaf(node)) { out[node.id] = path; return; }
    node.children.forEach((c, i) => walk(c, path.concat(i)));
  };
  walk(root, []);
  return out;
}

window.SashCoreTraverse = {
  isLeaf: sashIsLeaf,
  isSplit: sashIsSplit,
  firstLeafId: sashFirstLeafId,
  forEachLeaf: sashForEachLeaf,
  leafIds: sashLeafIds,
  findNode: sashFindNode,
  parentSplit: sashParentSplit,
  normalizePath: sashNormalizePath,
  nodeAtPath: sashNodeAtPath,
  parentPath: sashParentPath,
  leafPaths: sashLeafPaths,
};
