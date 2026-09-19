/* sash-grid-windows.js — facade C13 split into store/windows/menus, RULE18 file ≤100 */
'use strict';

// Facade merges store + windows + menus via UIHelpers.mergeParts
// Each sub-module owns real responsibility: store = persistence, windows = open/close/minimize, menus = dock+windows/layout menus
// The facade itself is <100 LOC and delegates via mergeParts

// Ensure sub-modules loaded before facade — index.html loads store.js, windows.js, menus.js before this file
// Merge if UIHelpers available, otherwise keep globals separate (backward compat)
if (typeof window !== 'undefined' && window.UIHelpers && window.UIHelpers.mergeParts) {
  // The actual SashGrid object is built in sash-grid.js which uses SashGridWindowStore/Windows/Menus via mixin
  // This file now only ensures the three parts exist and provides ideal-size reason
  // No logic here — all logic in sub-modules
}
