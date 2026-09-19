/* sash-grid part — sash-grid-drag-core.js (Issue 4 row creation + bug5 sash fix)
Core drag lifecycle, ≤200 LOC.
*/

const SashGridDrag = {
  _isDragBlocked() {
    if (this._drag) return true;
    if (this._resize) return true;
    return false;
  },

  _tryStartResize(ev) {
    const sashEl = ev.target.closest('.sash');
    if (!sashEl) return false;
    this._startResize(sashEl, ev);
    return true;
  },

  _findDragWin(ev) {
    const title = ev.target.closest('.win-title');
    if (!title) return null;
    if (!this.gridEl.contains(title)) return null;
    if (ev.target.closest('button, input, select, textarea, a, .chip, .win-controls, .win-btn')) return null;
    const winEl = title.closest('.sash-window');
    if (!winEl) return null;
    if (winEl.classList.contains('sash-win-hidden')) return null;
    if (winEl.classList.contains('sash-win-closed')) return null;
    return winEl;
  },

  _pointerDown(ev) {
    if (ev.button !== 0) return;
    if (this._isDragBlocked()) return;
    if (this._tryStartResize(ev)) return;
    const winEl = this._findDragWin(ev);
    if (!winEl) return;
    this._startDrag(winEl, ev);
  },

  _cleanStuckBody() {
    if (document.body.classList.contains('sash-dragging')) {
      document.body.classList.remove('sash-dragging');
    }
  },

  _bindDragListeners() {
    this._onDragMove = this._dragMove.bind(this);
    this._onDragUp = this._dragUp.bind(this);
    this._onDragKey = (e) => { if (e.key === 'Escape') this._cancelDrag(); };
    this._onDragBlur = () => this._cancelDrag();
    document.addEventListener('pointermove', this._onDragMove, { passive: false });
    document.addEventListener('pointerup', this._onDragUp);
    document.addEventListener('pointercancel', this._onDragCancel = this._cancelDrag.bind(this));
    document.addEventListener('keydown', this._onDragKey, true);
    window.addEventListener('blur', this._onDragBlur);
    document.addEventListener('visibilitychange', this._onDragBlur);
  },

  _tryCapturePointer(winEl, ev) {
    try {
      if (ev.pointerId != null && winEl.setPointerCapture) {
        winEl.setPointerCapture(ev.pointerId);
        this._drag.pointerCaptured = true;
        this._drag.capturedEl = winEl;
      }
    } catch (e) {}
  },

  _startDrag(winEl, ev) {
    this._cleanStuckBody();
    this._drag = {
      active: false, winEl, id: winEl.dataset.win,
      startX: ev.clientX, startY: ev.clientY, pointerId: ev.pointerId,
      lastX: ev.clientX, lastY: ev.clientY,
      clone: null, badge: null, indicator: null,
      rects: null, sashes: null,
      lastSpec: null, lastSpecKey: null, targetEl: null,
    };
    this._bindDragListeners();
    this._tryCapturePointer(winEl, ev);
  },

  _beginDrag() {
    const d = this._drag;
    d.active = true;
    this._cacheDragRects();
    const rect = d.winEl.getBoundingClientRect();
    d.clone = this._buildDragVisual(d.winEl, d.id, rect);
    d.clone.style.transform = 'translate3d(' + rect.left + 'px,' + rect.top + 'px,0)';
    this._createDragVisuals();
    d.winEl.classList.add('sash-drag-source');
    document.body.classList.add('sash-dragging');
  },

  _cacheDragRects() {
    const d = this._drag;
    d.rects = {};
    d.gridRect = this.gridEl.getBoundingClientRect();
    this.gridEl.querySelectorAll('.sash-window').forEach((w) => {
      if (w.classList.contains('sash-win-hidden') || w.classList.contains('sash-win-closed')) return;
      if (!w.offsetWidth || !w.offsetHeight) return;
      d.rects[w.dataset.win] = w.getBoundingClientRect();
    });
    d.sashes = [];
    this.gridEl.querySelectorAll('.sash').forEach((s) => {
      if (!s.offsetWidth && !s.offsetHeight) return;
      if (s.classList.contains('sash-hidden')) return;
      d.sashes.push({
        el: s, rect: s.getBoundingClientRect(),
        leftId: this._winIdOf(s.parentElement.children[+s.dataset.idx * 2]),
        rightId: this._winIdOf(s.parentElement.children[+s.dataset.idx * 2 + 2]),
      });
    });
  },

  _createDragVisuals() {
    const d = this._drag;
    d.badge = document.createElement('div');
    d.badge.className = 'sash-drag-badge';
    document.body.appendChild(d.badge);
    d.indicator = document.createElement('div');
    d.indicator.className = 'sash-drop-indicator';
    d.indicator.style.display = 'none';
    document.body.appendChild(d.indicator);
  },

  _buildDragVisual(winEl, id, rect) {
    if (winEl.querySelectorAll('*').length < 350) {
      const c = winEl.cloneNode(true);
      c.classList.add('sash-drag-clone');
      c.style.width = rect.width + 'px';
      c.style.height = rect.height + 'px';
      document.body.appendChild(c);
      return c;
    }
    const g = document.createElement('div');
    g.className = 'sash-drag-ghost';
    g.innerHTML = '<span style=\"font-size:18px\">◫</span><span>' + (SashCore.WINDOW_TITLES[id] || id) + '</span>';
    document.body.appendChild(g);
    return g;
  },

  _winIdOf(el) {
    if (!el) return null;
    if (el.dataset && el.dataset.win) return el.dataset.win;
    const inner = el && el.querySelector ? el.querySelector('.sash-window') : null;
    return inner ? inner.dataset.win : null;
  },

  _dragMove(ev) {
    const d = this._drag;
    if (!d) return;
    if (!d.active) {
      if (Math.abs(ev.clientX - d.startX) < this.THRESHOLD && Math.abs(ev.clientY - d.startY) < this.THRESHOLD) return;
      this._beginDrag();
    }
    ev.preventDefault();
    d.lastX = ev.clientX;
    d.lastY = ev.clientY;
    if (d.clone.classList.contains('sash-drag-ghost')) {
      d.clone.style.transform = 'translate3d(' + (ev.clientX + 14) + 'px,' + (ev.clientY + 14) + 'px,0)';
    } else {
      const r = d.winEl.getBoundingClientRect();
      const dx = d.startX - r.left, dy = d.startY - r.top;
      d.clone.style.transform = 'translate3d(' + (ev.clientX - dx) + 'px,' + (ev.clientY - dy) + 'px,0)';
    }
    const spec = this._computeSpec(ev.clientX, ev.clientY);
    const key = spec ? JSON.stringify(spec) : '';
    if (key !== d.lastSpecKey) {
      d.lastSpecKey = key;
      d.lastSpec = spec;
      this._showSpec(spec);
    }
  },

  _dragUp() {
    const d = this._drag;
    if (!d) return;
    const spec = d.active ? d.lastSpec : null;
    this._cleanupDrag();
    if (spec) {
      this._applyDrop(d.id, spec);
      this.render();
      this._save();
      this._flashLanded(d.id);
      if (typeof LogConsole !== 'undefined') LogConsole.log('🧩 ' + (SashCore.WINDOW_TITLES[d.id] || d.id) + ' → ' + this._specText(spec) + ' (grid updated)', 'info');
    } else if (d.active) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('↩ Window drag cancelled — layout unchanged', 'warn');
    }
  },

  _cancelDrag() {
    const d = this._drag;
    if (!d) return;
    this._cleanupDrag();
    if (d.active && typeof LogConsole !== 'undefined') LogConsole.log('↩ Window drag cancelled — layout unchanged', 'warn');
  },

  _cleanupBodyClasses() {
    try {
      document.body.classList.remove('sash-dragging');
      document.body.classList.remove('sash-resizing-row', 'sash-resizing-col');
    } catch (e) {}
  },

  _removeDragListeners() {
    try { document.removeEventListener('pointermove', this._onDragMove, { passive: false }); } catch (e) {}
    try { document.removeEventListener('pointerup', this._onDragUp); } catch (e) {}
    try { document.removeEventListener('pointercancel', this._onDragCancel); } catch (e) {}
    try { document.removeEventListener('keydown', this._onDragKey, true); } catch (e) {}
    try { window.removeEventListener('blur', this._onDragBlur); } catch (e) {}
    try { document.removeEventListener('visibilitychange', this._onDragBlur); } catch (e) {}
  },

  _releasePointerCapture(d) {
    try {
      if (d.pointerCaptured && d.capturedEl && d.capturedEl.releasePointerCapture) {
        d.capturedEl.releasePointerCapture(d.pointerId);
      }
    } catch (e) {}
  },

  _removeClone(d) {
    if (d.clone?.parentNode) d.clone.parentNode.removeChild(d.clone);
  },
  _removeBadge(d) {
    if (d.badge?.parentNode) d.badge.parentNode.removeChild(d.badge);
  },
  _removeIndicator(d) {
    if (d.indicator?.parentNode) d.indicator.parentNode.removeChild(d.indicator);
  },
  _clearTargets(d) {
    if (d.targetEl) d.targetEl.classList.remove('sash-drag-target');
    try { this.gridEl.querySelectorAll('.sash-target').forEach((s) => s.classList.remove('sash-target')); } catch (e) {}
    if (d.winEl?.isConnected) d.winEl.classList.remove('sash-drag-source');
  },
  _removeDragVisuals(d) {
    this._removeClone(d);
    this._removeBadge(d);
    this._removeIndicator(d);
    this._clearTargets(d);
  },

  _cleanupDrag() {
    const d = this._drag;
    this._cleanupBodyClasses();
    if (!d) { this._drag = null; return; }
    this._removeDragListeners();
    this._releasePointerCapture(d);
    this._removeDragVisuals(d);
    this._drag = null;
  },

  _flashLanded(winId) {
    const el = this.gridEl.querySelector('.sash-window[data-win=\"' + winId + '\"]');
    if (!el) return;
    el.classList.remove('sash-landed');
    void el.offsetWidth;
    el.classList.add('sash-landed');
    setTimeout(() => el.classList.remove('sash-landed'), 700);
  },

  _dropForZone(targetId, zone) {
    const map = {
      'before': { kind: 'sibling', target: targetId, side: 'before' },
      'after': { kind: 'sibling', target: targetId, side: 'after' },
      'left': { kind: 'edge', target: targetId, dir: 'row', newFirst: true },
      'right': { kind: 'edge', target: targetId, dir: 'row', newFirst: false },
      'top': { kind: 'edge', target: targetId, dir: 'col', newFirst: true },
      'bottom': { kind: 'edge', target: targetId, dir: 'col', newFirst: false },
      'outer-top': { kind: 'outer', side: 'top' },
      'outer-bottom': { kind: 'outer', side: 'bottom' },
      'outer-left': { kind: 'outer', side: 'left' },
      'outer-right': { kind: 'outer', side: 'right' },
    };
    const drop = map[zone];
    if (!drop) throw new Error('simulateDrop: bad zone ' + zone);
    return drop;
  },

  simulateDrop(draggedId, targetId, zone) {
    const drop = this._dropForZone(targetId, zone);
    this.root = SashCore.moveWindow(this.root, draggedId, drop);
    this.render();
    this._save();
    return this.getTree();
  },
};
