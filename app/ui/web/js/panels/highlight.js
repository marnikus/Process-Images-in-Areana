/* highlight.js — DEPRECATED APP OVERLAY — visual rect should draw ONLY on webpage via CDP
   User requested: visual rectangle confirmation are drawing not in webpage but in App directly.
   It should Draw only on web page! fix — so this overlay is now disabled.
   CDP highlighting via dom_highlight.py injects rects directly into webpage DOM via evaluate.
   This file remains for compatibility but show() is no-op.
*/
'use strict';

const HighlightOverlay = {
  _timer: null,
  _activeDivs: [],

  init() {
    // Disabled: do not create #highlightOverlay in app — should draw only on webpage
    // Keep for backward compat: ensure no overlay exists or clear it
    const existing = document.getElementById('highlightOverlay');
    if (existing) {
      existing.innerHTML = '';
      existing.style.display = 'none';
    }
    if (typeof LogConsole !== 'undefined') {
      // optional debug
      // LogConsole.log('HighlightOverlay disabled — rects draw only on webpage via CDP', 'info');
    }
  },

  show(rect) {
    // NO-OP: do not draw in app, only on webpage via CDP
    // Log for debugging but do not create divs in app
    if (rect && rect.label) {
      // console.debug('HighlightOverlay.show suppressed (webpage only):', rect);
    }
    return;
  },

  clearAll() {
    const overlay = document.getElementById('highlightOverlay');
    if (overlay) overlay.innerHTML = '';
    this._activeDivs = [];
  },

  // called from bridge highlight_selector that uses CDP dom_highlight.py logic
  highlightViaCDP(selector, color, durationMs, caption) {
    const durSec = (durationMs || 2000) / 1000;
    if (App.bridge && App.bridge.highlight_selector) {
      App.bridge.highlight_selector(selector, color || '#FF0000', durationMs || 2000, caption || selector, (res) => {
        try {
          const r = JSON.parse(res);
          // r.fallback no longer triggers app overlay — webpage highlight via CDP is primary
        } catch {}
      });
    } else {
      // No bridge — cannot highlight webpage, do not fallback to app overlay per user request
      if (typeof LogConsole !== 'undefined') {
        LogConsole.log(`Highlight requested for webpage only but bridge missing: ${selector}`, 'warn');
      }
    }
  }
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.HighlightOverlay = HighlightOverlay;
