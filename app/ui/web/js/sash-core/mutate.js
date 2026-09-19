/* sash-core/mutate.js — tree mutation ops (C7) */
'use strict';

function sashGetTree() { return window.SashCoreTree; }
function sashGetTrav() { return window.SashCoreTraverse; }

function sashSplitLeaf(specOrRoot) {
  let spec;
  if (specOrRoot && typeof specOrRoot === 'object' && specOrRoot.root) spec = specOrRoot;
  else {
    const args = arguments;
    spec = { root: args[0], targetId: args[1], newId: args[2], dir: args[3], newFirst: args[4] };
  }
  const { root, targetId, newId, dir, newFirst } = spec;
  const f = sashGetTrav().findNode(root, targetId);
  if (!f) throw new Error('splitLeaf unknown ' + targetId);
  const leaf = sashGetTree().leaf(newId);
  const newSplit = sashGetTree().split(dir, newFirst ? [leaf, f.node] : [f.node, leaf], [50, 50]);
  if (f.parent) { f.parent.children[f.index] = newSplit; return root; }
  return newSplit;
}

function sashResolveDonor(root, donorId, parent) {
  const d = sashGetTrav().findNode(root, donorId);
  if (!d || d.parent !== parent) throw new Error('donor not in split');
  return d.index;
}

function sashValidateInsertIndex(p, index) {
  if (!Number.isInteger(index) || index < 0 || index > p.children.length) throw new Error('bad index');
}

function sashGetDonorIdx(root, donorId, parent, index) {
  if (donorId) return sashResolveDonor(root, donorId, parent);
  return index > 0 ? index - 1 : 0;
}

function sashApplyInsert(p, index, newId, donorIdx) {
  const half = p.sizes[donorIdx] / 2;
  p.children.splice(index, 0, sashGetTree().leaf(newId));
  p.sizes.splice(index, 0, half);
  const adjust = donorIdx >= index ? donorIdx + 1 : donorIdx;
  p.sizes[adjust] = half;
  p.sizes = sashGetTree().normalizeSizes(p.sizes);
}

function sashInsertAtSplitIndex(specOrRoot) {
  let spec;
  if (specOrRoot && typeof specOrRoot === 'object' && specOrRoot.root) spec = specOrRoot;
  else {
    const args = arguments;
    spec = { root: args[0], refChildId: args[1], index: args[2], newId: args[3], donorId: args[4] };
  }
  const { root, refChildId, index, newId, donorId } = spec;
  const f = sashGetTrav().findNode(root, refChildId);
  if (!f) throw new Error('no parent');
  if (!f.parent) throw new Error('no parent');
  const p = f.parent;
  sashValidateInsertIndex(p, index);
  const donorIdx = sashGetDonorIdx(root, donorId, p, index);
  if (donorId) {
    const isAdjacent = donorIdx === index || donorIdx === index - 1;
    if (!isAdjacent) throw new Error('donor not adjacent');
  }
  sashApplyInsert(p, index, newId, donorIdx);
  return root;
}

function sashInsertSibling(root, targetId, newId, side) {
  const f = sashGetTrav().findNode(root, targetId);
  if (!f) throw new Error('unknown ' + targetId);
  if (!f.parent) return sashSplitLeaf({ root, targetId, newId, dir: 'row', newFirst: side !== 'after' });
  const pos = side === 'before' ? f.index : f.index + 1;
  return sashInsertAtSplitIndex({ root, refChildId: targetId, index: pos, newId, donorId: targetId });
}

function sashInsertBetween(root, leftId, newId) {
  const f = sashGetTrav().findNode(root, leftId);
  if (!f || !f.parent) throw new Error('no sibling');
  const p = f.parent;
  if (f.index >= p.children.length - 1) throw new Error('last child');
  const rightId = sashGetTrav().firstLeafId(p.children[f.index + 1]);
  return sashInsertAtSplitIndex({ root, refChildId: leftId, index: f.index + 1, newId, donorId: rightId });
}

function sashSetSplitSizes(root, childId, sizes) {
  const f = sashGetTrav().findNode(root, childId);
  if (!f || !f.parent) throw new Error('no parent');
  if (sizes.length !== f.parent.children.length) throw new Error('size mismatch');
  f.parent.sizes = sashGetTree().normalizeSizes(sizes);
  return root;
}

function sashValidatePathIndex(p, index, donorIdx) {
  if (!Number.isInteger(index) || index < 0 || index > p.children.length) throw new Error('bad index');
  if (!Number.isInteger(donorIdx) || donorIdx < 0 || donorIdx >= p.children.length) throw new Error('bad donor');
  if (donorIdx !== index && donorIdx !== index - 1) throw new Error('donor not adjacent');
}

function sashInsertAtSplitPath(specOrRoot) {
  let spec;
  if (specOrRoot && typeof specOrRoot === 'object' && specOrRoot.root) spec = specOrRoot;
  else {
    const args = arguments;
    spec = { root: args[0], splitPath: args[1], index: args[2], newId: args[3], donorIdx: args[4] };
  }
  const { root, splitPath, index, newId, donorIdx } = spec;
  const p = sashGetTrav().nodeAtPath(root, splitPath);
  if (!p || !sashGetTrav().isSplit(p)) throw new Error('no split at path');
  sashValidatePathIndex(p, index, donorIdx);
  const half = p.sizes[donorIdx] / 2;
  p.children.splice(index, 0, sashGetTree().leaf(newId));
  p.sizes.splice(index, 0, half);
  p.sizes[donorIdx >= index ? donorIdx + 1 : donorIdx] = half;
  p.sizes = sashGetTree().normalizeSizes(p.sizes);
  return root;
}

function sashSetSplitSizesByPath(root, splitPath, sizes) {
  const p = sashGetTrav().nodeAtPath(root, splitPath);
  if (!p || !sashGetTrav().isSplit(p)) throw new Error('no split at path');
  if (!Array.isArray(sizes) || sizes.length !== p.children.length) throw new Error('size mismatch');
  p.sizes = sashGetTree().normalizeSizes(sizes);
  return root;
}

function sashRemoveNode(root, node) {
  const removeFrom = (n) => {
    if (n === node) return undefined;
    if (sashGetTrav().isLeaf(n)) return n;
    for (let i = 0; i < n.children.length; i++) {
      const res = removeFrom(n.children[i]);
      if (res === undefined) {
        n.children.splice(i, 1);
        n.sizes.splice(i, 1);
        if (n.children.length === 1) return n.children[0];
        n.sizes = sashGetTree().normalizeSizes(n.sizes);
        return n;
      }
      n.children[i] = res;
    }
    return n;
  };
  const res = removeFrom(root);
  if (res === undefined) throw new Error('node not in tree');
  return res;
}

function sashRemoveLeaf(root, id) {
  const f = sashGetTrav().findNode(root, id);
  if (!f) throw new Error('unknown ' + id);
  return sashRemoveNode(root, f.node);
}

function sashInsertOuterLeaf(root, newId, wantDir, newFirst) {
  const leaf = sashGetTree().leaf(newId);
  return sashGetTree().split(wantDir, newFirst ? [leaf, root] : [root, leaf], [20, 80]);
}

function sashInsertOuterExisting(root, newId) {
  const isFirst = arguments[2] === true || arguments[1] === true;
  const wantDir = arguments[2] || 'col';
  const newFirst = isFirst;
  const idx = newFirst ? 0 : root.children.length;
  const donorIdx = newFirst ? 0 : root.children.length - 1;
  const half = root.sizes[donorIdx] / 2;
  root.children.splice(idx, 0, sashGetTree().leaf(newId));
  root.sizes.splice(idx, 0, half);
  const donorPos = donorIdx >= idx ? donorIdx + 1 : donorIdx;
  root.sizes[donorPos] = half;
  root.sizes = sashGetTree().normalizeSizes(root.sizes);
  return root;
}

function sashOuterDir(side) {
  const isTop = side === 'top';
  const isBottom = side === 'bottom';
  const wantCol = isTop || isBottom;
  return { wantDir: wantCol ? 'col' : 'row', newFirst: isTop || side === 'left' };
}

function sashInsertOuterSameDir(root, newId, newFirst) {
  const idx = newFirst ? 0 : root.children.length;
  const donorIdx = newFirst ? 0 : root.children.length - 1;
  const half = root.sizes[donorIdx] / 2;
  root.children.splice(idx, 0, sashGetTree().leaf(newId));
  root.sizes.splice(idx, 0, half);
  const donorPos = donorIdx >= idx ? donorIdx + 1 : donorIdx;
  root.sizes[donorPos] = half;
  root.sizes = sashGetTree().normalizeSizes(root.sizes);
  return root;
}

function sashInsertOuter(root, newId, side) {
  const { wantDir, newFirst } = sashOuterDir(side);
  if (sashGetTrav().isLeaf(root)) return sashInsertOuterLeaf(root, newId, wantDir, newFirst);
  if (sashGetTrav().isSplit(root) && root.dir === wantDir) return sashInsertOuterSameDir(root, newId, newFirst);
  const leaf = sashGetTree().leaf(newId);
  if (newFirst) return sashGetTree().split(wantDir, [leaf, root], [20, 80]);
  return sashGetTree().split(wantDir, [root, leaf], [80, 20]);
}

function sashMoveOuter(root, draggedId, side, origNode) {
  if (!['top', 'bottom', 'left', 'right'].includes(side)) throw new Error('bad side');
  const without = sashRemoveNode(root, origNode);
  return sashInsertOuter(without, draggedId, side);
}

function sashMoveSash(root, draggedId, drop) {
  const paths = sashGetTrav().leafPaths(root);
  const a = paths[drop.left], b = paths[drop.right];
  if (!a || !b) throw new Error('anchors not found');
  let k = 0;
  while (k < a.length && k < b.length && a[k] === b[k]) k++;
  const lca = sashGetTrav().nodeAtPath(root, a.slice(0, k));
  const iA = a[k], iB = b[k];
  if (!lca || !sashGetTrav().isSplit(lca) || Math.abs(iA - iB) !== 1) throw new Error('anchors not adjacent');
  const insertIdx = Math.max(iA, iB);
  const half = lca.sizes[insertIdx] / 2;
  lca.children.splice(insertIdx, 0, sashGetTree().leaf(draggedId));
  lca.sizes.splice(insertIdx, 0, half);
  lca.sizes[insertIdx + 1] = half;
  lca.sizes = sashGetTree().normalizeSizes(lca.sizes);
  return root;
}

function sashMoveEdge(root, draggedId, drop) {
  return sashSplitLeaf({ root, targetId: drop.target, newId: draggedId, dir: drop.dir, newFirst: drop.newFirst });
}

function sashMoveSibling(root, draggedId, drop) {
  const f = sashGetTrav().findNode(root, drop.target);
  if (!f) throw new Error('unknown target ' + drop.target);
  if (!f.parent) return sashSplitLeaf({ root, targetId: drop.target, newId: draggedId, dir: 'row', newFirst: drop.side !== 'after' });
  const pos = drop.side === 'before' ? f.index : f.index + 1;
  return sashInsertAtSplitIndex({ root, refChildId: drop.target, index: pos, newId: draggedId, donorId: drop.target });
}

function sashMoveWindow(root, draggedId, drop) {
  if (drop.target && drop.target === draggedId) throw new Error('drop on itself');
  const orig = sashGetTrav().findNode(root, draggedId);
  if (!orig) throw new Error('unknown ' + draggedId);
  const origNode = orig.node;
  if (drop.kind === 'outer') return sashMoveOuter(root, draggedId, drop.side, origNode);
  if (drop.kind === 'edge') root = sashMoveEdge(root, draggedId, drop);
  else if (drop.kind === 'sibling') root = sashMoveSibling(root, draggedId, drop);
  else if (drop.kind === 'sash') root = sashMoveSash(root, draggedId, drop);
  else throw new Error('unknown drop kind ' + drop.kind);
  return sashRemoveNode(root, origNode);
}

window.SashCoreMutate = {
  splitLeaf: sashSplitLeaf,
  insertAtSplitIndex: sashInsertAtSplitIndex,
  insertSibling: sashInsertSibling,
  insertBetween: sashInsertBetween,
  setSplitSizes: sashSetSplitSizes,
  insertAtSplitPath: sashInsertAtSplitPath,
  setSplitSizesByPath: sashSetSplitSizesByPath,
  removeLeaf: sashRemoveLeaf,
  insertOuter: sashInsertOuter,
  moveWindow: sashMoveWindow,
  removeNode: sashRemoveNode,
};
