/* highlight.js — rect drawing above clicked element for several seconds, saved in preset JSON, using old app's highlight service */
'use strict';

const HighlightOverlay = {
  _timer: null,
  _activeDivs: [],

  init() {
    let overlay = document.getElementById('highlightOverlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'highlightOverlay';
      overlay.style.cssText = 'position:fixed; inset:0; pointer-events:none; z-index:99999;';
      document.body.appendChild(overlay);
    }
  },

  show(rect) {
    // rect: {x, y, width, height, duration, label, color}
    const overlay = document.getElementById('highlightOverlay');
    if (!overlay) return;
    const div = document.createElement('div');
    div.className = 'highlight-rect';
    div.style.position = 'absolute';
    div.style.left = (rect.x || 0) + 'px';
    div.style.top = (rect.y || 0) + 'px';
    div.style.width = (rect.width || 100) + 'px';
    div.style.height = (rect.height || 100) + 'px';
    div.style.border = `2px solid ${rect.color || '#FF0000'}`;
    div.style.background = `${rect.color || '#FF0000'}22`;
    div.style.boxSizing = 'border-box';
    div.style.borderRadius = '3px';
    div.style.pointerEvents = 'none';
    div.style.transition = 'opacity 0.3s';
    div.style.zIndex = '99999';
    if (rect.label) {
      div.title = rect.label;
      const caption = document.createElement('div');
      caption.textContent = rect.label;
      caption.style.cssText = `position:absolute; top:-20px; left:0; background:${rect.color||'#FF0000'}; color:white; font-size:10px; font-weight:600; padding:1px 6px; border-radius:3px; white-space:nowrap;`;
      div.appendChild(caption);
    }
    overlay.appendChild(div);
    this._activeDivs.push(div);

    const duration = (rect.duration || 3) * 1000;
    setTimeout(() => {
      div.style.opacity = '0';
      setTimeout(()=>{ if(div.parentNode) div.parentNode.removeChild(div); }, 300);
    }, duration);
    // auto-clear after duration + 0.5s also from array
    setTimeout(()=> {
      this._activeDivs = this._activeDivs.filter(d=>d!==div);
    }, duration + 500);
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
          if (r.fallback) {
            // UI fallback already emitted highlight_rect
          }
        } catch {}
      });
    } else {
      // fallback UI only
      this.show({x:200,y:200,width:320,height:180,duration:durSec,label:caption||selector,color:color||'#FF0000'});
    }
  }
};
