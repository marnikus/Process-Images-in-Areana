/* highlight.js — rect drawing above clicked element for several seconds */
'use strict';

const HighlightOverlay = {
  _timer: null,

  init() {
    let overlay = document.getElementById('highlightOverlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'highlightOverlay';
      document.body.appendChild(overlay);
    }
  },

  show(rect) {
    // rect: {x, y, width, height, duration, label}
    const overlay = document.getElementById('highlightOverlay');
    if (!overlay) return;
    overlay.innerHTML = '';
    const div = document.createElement('div');
    div.className = 'highlight-rect';
    div.style.left = (rect.x || 0) + 'px';
    div.style.top = (rect.y || 0) + 'px';
    div.style.width = (rect.width || 100) + 'px';
    div.style.height = (rect.height || 100) + 'px';
    if (rect.label) {
      div.title = rect.label;
      div.textContent = rect.label;
      div.style.display = 'flex';
      div.style.alignItems = 'center';
      div.style.justifyContent = 'center';
      div.style.fontSize = '11px';
      div.style.color = 'var(--accent)';
      div.style.fontWeight = '600';
    }
    overlay.appendChild(div);

    const duration = (rect.duration || 3) * 1000;
    if (this._timer) clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      div.style.opacity = '0';
      setTimeout(()=>{ if(div.parentNode) div.parentNode.removeChild(div); }, 300);
    }, duration);
  }
};
