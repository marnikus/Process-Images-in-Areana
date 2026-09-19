/* sash-core.js — facade merging split modules (C7)
   Loads constants/tree/traverse/mutate/validate.
   RULE18: file 150-300 ideal, ≤500 hard limit
*/
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SashCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const C = (typeof self !== 'undefined' ? self : window).SashCoreConstants || {};
  const T = (typeof self !== 'undefined' ? self : window).SashCoreTree || {};
  const Trav = (typeof self !== 'undefined' ? self : window).SashCoreTraverse || {};
  const Mut = (typeof self !== 'undefined' ? self : window).SashCoreMutate || {};
  const V = (typeof self !== 'undefined' ? self : window).SashCoreValidate || {};

  // Merge with fallback to local definitions if modules not loaded (for tests)
  const merged = {};
  [C, T, Trav, Mut, V].forEach(part => {
    if (part) Object.keys(part).forEach(k => { merged[k] = part[k]; });
  });

  // Ensure essential APIs exist even if modules missing
  if (!merged.leaf) merged.leaf = (id) => ({ t: 'leaf', id });
  if (!merged.clone) merged.clone = (n) => JSON.parse(JSON.stringify(n));
  if (!merged.normalizeSizes) merged.normalizeSizes = (s) => s;

  return merged;
});
