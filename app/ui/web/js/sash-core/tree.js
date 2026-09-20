/* sash-core/tree.js — leaf/split and preset trees (C7) */
'use strict';

function sashNormalizeBase(sizes, minSize) {
  return sizes.map(s => {
    const n = Number(s);
    return Number.isFinite(n) && n > 0 ? n : minSize;
  });
}

function sashNormalizeScaled(base, minSize) {
  const sum = base.reduce((a, b) => a + b, 0) || 1;
  if (Math.abs(sum - 100) < 1e-9 && base.every(s => s >= minSize)) return base;
  const scaled = base.map(s => (s / sum) * 100);
  if (scaled.every(s => s >= minSize)) return scaled;
  return null;
}

function sashNormalizeFallback(base, minSize) {
  const floorTotal = minSize * base.length;
  if (floorTotal >= 100) return base.map(() => 100 / base.length);
  const excess = base.map(s => Math.max(0, s - minSize));
  const excessTotal = excess.reduce((a, b) => a + b, 0);
  const remaining = 100 - floorTotal;
  if (!excessTotal) return base.map(() => 100 / base.length);
  return excess.map(s => minSize + (s / excessTotal) * remaining);
}

function sashNormalizeSizes(sizes) {
  const C = window.SashCoreConstants;
  const minSize = C ? C.MIN_SIZE : 4;
  if (!Array.isArray(sizes) || !sizes.length) return sizes;
  const base = sashNormalizeBase(sizes, minSize);
  const scaled = sashNormalizeScaled(base, minSize);
  if (scaled) return scaled;
  return sashNormalizeFallback(base, minSize);
}

function sashLeaf(id) { return { t: 'leaf', id }; }
function sashClone(node) { return JSON.parse(JSON.stringify(node)); }

function sashSplit(dir, children, sizes) {
  if (dir !== 'row' && dir !== 'col') throw new Error('bad split dir: ' + dir);
  if (!Array.isArray(children) || children.length < 2) throw new Error('split needs at least 2 children');
  if (!Array.isArray(sizes) || sizes.length !== children.length) throw new Error('split sizes must match children');
  return { t: 'split', dir, children, sizes: sashNormalizeSizes(sizes) };
}

function sashDefaultTree() {
  return sashSplit('col', [
    sashSplit('row', [
      sashSplit('col', [sashLeaf('url_list'), sashLeaf('folder')], [55, 45]),
      sashSplit('col', [sashLeaf('prompt'), sashLeaf('run'), sashLeaf('settings'), sashLeaf('captcha'), sashLeaf('recordings')], [35, 20, 20, 12, 13]),
    ], [60, 40]),
    sashSplit('row', [
      sashLeaf('queue'),
      sashSplit('col', [sashLeaf('action_blocks'), sashLeaf('block_config')], [55, 45]),
      sashSplit('col', [sashLeaf('browser'), sashLeaf('arena_presets'), sashLeaf('progress'), sashLeaf('watcher'), sashLeaf('live_debug')], [25, 20, 15, 20, 20]),
    ], [45, 35, 20]),
    sashLeaf('log'),
  ], [38, 40, 22]);
}

function sashLayoutA() {
  return sashSplit('col', [
    sashLeaf('url_list'), sashLeaf('folder'), sashLeaf('queue'),
    sashLeaf('prompt'), sashLeaf('run'), sashLeaf('progress'), sashLeaf('watcher'),
    sashLeaf('log'), sashLeaf('settings'), sashLeaf('captcha'), sashLeaf('recordings'), sashLeaf('browser'),
    sashLeaf('action_blocks'), sashLeaf('block_config'), sashLeaf('arena_presets'), sashLeaf('live_debug'),
  ], [7, 5, 10, 8, 6, 6, 6, 7, 6, 6, 6, 6, 6, 6, 5, 4]);
}

function sashLayoutB() {
  return sashSplit('row', [
    sashSplit('col', [sashLeaf('url_list'), sashLeaf('folder'), sashLeaf('queue'), sashLeaf('action_blocks')], [25, 15, 35, 25]),
    sashSplit('col', [sashLeaf('prompt'), sashLeaf('block_config'), sashLeaf('progress'), sashLeaf('watcher'), sashLeaf('log')], [25, 20, 15, 20, 20]),
    sashSplit('col', [sashLeaf('browser'), sashLeaf('settings'), sashLeaf('captcha'), sashLeaf('recordings'), sashLeaf('arena_presets'), sashLeaf('run'), sashLeaf('live_debug')], [16, 14, 14, 14, 14, 14, 14]),
  ], [35, 35, 30]);
}

function sashLayoutC() {
  return sashSplit('col', [
    sashSplit('row', [
      sashSplit('col', [sashLeaf('url_list'), sashLeaf('prompt'), sashLeaf('action_blocks')], [35, 35, 30]),
      sashSplit('col', [sashLeaf('block_config'), sashLeaf('browser')], [45, 55]),
    ], [45, 55]),
    sashSplit('row', [
      sashLeaf('queue'),
      sashSplit('col', [sashLeaf('folder'), sashLeaf('run'), sashLeaf('settings'), sashLeaf('captcha'), sashLeaf('recordings'), sashLeaf('progress'), sashLeaf('watcher'), sashLeaf('arena_presets'), sashLeaf('live_debug')], [11, 11, 12, 12, 11, 11, 11, 11, 10]),
    ], [60, 40]),
    sashLeaf('log'),
  ], [35, 48, 17]);
}

window.SashCoreTree = {
  leaf: sashLeaf,
  split: sashSplit,
  clone: sashClone,
  normalizeSizes: sashNormalizeSizes,
  defaultTree: sashDefaultTree,
  layoutA: sashLayoutA,
  layoutB: sashLayoutB,
  layoutC: sashLayoutC,
  PRESETS: { default: sashDefaultTree, a: sashLayoutA, b: sashLayoutB, c: sashLayoutC },
};
