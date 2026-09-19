/* sash-core.js — facade merging split modules (C7) */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SashCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const g = typeof self !== 'undefined' ? self : window;
  const parts = [g.SashCoreConstants||{}, g.SashCoreTree||{}, g.SashCoreTraverse||{}, g.SashCoreMutate||{}, g.SashCoreValidate||{}];
  const m = Object.assign({}, parts[0], parts[1], parts[2], parts[3], parts[4]);
  if (!m.leaf) m.leaf = function(id){ return {t:'leaf',id:id}; };
  if (!m.clone) m.clone = function(n){ return JSON.parse(JSON.stringify(n)); };
  if (!m.normalizeSizes) m.normalizeSizes = function(s){ return s; };
  return m;
});
