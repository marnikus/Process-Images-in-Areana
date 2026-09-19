/* sash-grid part — sash-grid-drag-resize.js (bug5 sash fix)
Sash resize with pixel allocation, ≤250 LOC.
*/

const SashGridResize = {
  _cleanStuckDrag() {
    if (document.body.classList.contains('sash-dragging')) {
      document.body.classList.remove('sash-dragging');
    }
  },

  _collectChildEls(pEl) {
    const childEls = [];
    for (let i = 0; i * 2 < pEl.children.length; i++) childEls.push(pEl.children[i * 2]);
    return childEls;
  },

  _measureAxis(isRow) {
    return (el) => { const r = el.getBoundingClientRect(); return isRow ? r.width : r.height; };
  },

  _buildResizeCtx(pEl, sashEl, sIdx, ev) {
    const isRow = pEl.classList.contains('sash-row');
    const childEls = this._collectChildEls(pEl);
    const axisSize = this._measureAxis(isRow);
    const childSizes = childEls.map(axisSize);
    const sashSizes = Array.from(pEl.children).filter((el) => el.classList.contains('sash')).map(axisSize);
    let rIdx = sIdx + 1;
    while (rIdx < childSizes.length && childSizes[rIdx] <= 1) rIdx++;
    const z = { pEl, sashEl, sIdx, rIdx, isRow, childEls, pointerId: ev.pointerId, childSizes, sashSizes, otherWidths: {}, originalFlex: childEls.map((child) => child.style.flex), pointerCaptured: false };
    for (let i = 0; i < childSizes.length; i++) { if (i === sIdx || i === rIdx) continue; z.otherWidths[i] = childSizes[i]; }
    return z;
  },

  _bindResizeListeners(sashEl, isRow, ev) {
    sashEl.classList.add('sash-active');
    document.body.classList.add(isRow ? 'sash-resizing-row' : 'sash-resizing-col');
    this._onResizeMove = this._resizeMove.bind(this);
    this._onResizeUp = this._resizeUp.bind(this);
    this._onResizeBlur = () => this._cancelResize(true);
    document.addEventListener('pointermove', this._onResizeMove, { passive: false });
    document.addEventListener('pointerup', this._onResizeUp);
    document.addEventListener('pointercancel', this._onResizeCancel = () => this._cancelResize(true));
    document.addEventListener('keydown', this._onResizeKey = (keyEvent) => {
      if (keyEvent.key === 'Escape') { keyEvent.preventDefault(); this._cancelResize(true); }
    }, true);
    window.addEventListener('blur', this._onResizeBlur);
    document.addEventListener('visibilitychange', this._onResizeBlur);
    ev.preventDefault();
  },

  _startResize(sashEl, ev) {
    this._cleanStuckDrag();
    const pEl = sashEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) return;
    const sIdx = parseInt(sashEl.dataset.idx, 10);
    const z = this._buildResizeCtx(pEl, sashEl, sIdx, ev);
    this._resize = z;
    if (ev.pointerId != null && typeof sashEl.setPointerCapture === 'function') {
      try { sashEl.setPointerCapture(ev.pointerId); z.pointerCaptured = true; } catch (e) {}
    }
    this._bindResizeListeners(sashEl, z.isRow, ev);
  },

  _resizePixelAllocation(z, pointer, rect) {
    if (z.rIdx >= z.childSizes.length) return null;
    const axis = z.isRow ? rect.width : rect.height;
    const sashTotal = z.sashSizes.reduce((sum, size) => sum + Math.max(0, size), 0);
    let others = 0;
    for (const k of Object.keys(z.otherWidths)) others += Math.max(0, z.otherWidths[k]);
    const span = axis - others - sashTotal;
    if (span < this.MIN_PX * 2) return null;
    let prefix = 0;
    for (let i = 0; i < z.sIdx; i++) { prefix += Math.max(0, z.childSizes[i]); prefix += Math.max(0, z.sashSizes[i] || 0); }
    const start = (z.isRow ? rect.left : rect.top) + prefix;
    const requested = pointer - start;
    const first = Math.min(Math.max(requested, this.MIN_PX), span - this.MIN_PX);
    const allocation = z.childSizes.slice();
    allocation[z.sIdx] = first;
    allocation[z.rIdx] = span - first;
    return allocation;
  },

  _resizeMove(ev) {
    const z = this._resize;
    if (!z) return;
    ev.preventDefault();
    const rect = z.pEl.getBoundingClientRect();
    const allocation = this._resizePixelAllocation(z, z.isRow ? ev.clientX : ev.clientY, rect);
    if (!allocation) return;
    z.childEls.forEach((child, i) => { const px = allocation[i]; child.style.flex = px > 0 ? `0 0 ${px}px` : '0 0 0px'; });
    this._fitTitleBars();
  },

  _resizeUp() {
    const z = this._resize;
    if (!z) return;
    this._cancelResize(false);
    const path = this._parsePath(z.pEl.dataset.path);
    const p = SashCore.nodeAtPath(this.root, path);
    const sizes = this._commitResizeSizes(z, p ? p.sizes : null);
    this.root = SashCore.setSplitSizesByPath(this.root, path, sizes);
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') LogConsole.log('📏 Grid resized', 'info');
  },

  _commitResizeSizes(z, prev) {
    const kids = z.childEls.map((el, i) => {
      const r = el.getBoundingClientRect();
      const w = Math.max(0, z.isRow ? r.width : r.height);
      return { i, w, shown: w > 1 };
    });
    const shownSum = kids.reduce((a, k) => a + (k.shown ? k.w : 0), 0);
    const hiddenSum = kids.reduce((a, k) => a + (k.shown ? 0 : (prev ? prev[k.i] || 0 : 0)), 0);
    const budget = Math.max(0, 100 - hiddenSum);
    return kids.map((k) => k.shown
      ? (shownSum > 0 ? (k.w / shownSum) * budget : 100 / kids.length)
      : (prev ? prev[k.i] : 100 / kids.length));
  },

  _cleanupResizeBody() {
    try { document.body.classList.remove('sash-resizing-row', 'sash-resizing-col', 'sash-dragging'); } catch (e) {}
  },

  _removeResizeListeners() {
    try { document.removeEventListener('pointermove', this._onResizeMove, { passive: false }); } catch (e) {}
    try { document.removeEventListener('pointerup', this._onResizeUp); } catch (e) {}
    try { document.removeEventListener('pointercancel', this._onResizeCancel); } catch (e) {}
    try { document.removeEventListener('keydown', this._onResizeKey, true); } catch (e) {}
    try { window.removeEventListener('blur', this._onResizeBlur); } catch (e) {}
    try { document.removeEventListener('visibilitychange', this._onResizeBlur); } catch (e) {}
  },

  _restoreResizeFlex(z) {
    try { z.childEls.forEach((child, i) => { child.style.flex = z.originalFlex[i]; }); } catch (e) {}
  },

  _releaseResizeCapture(z) {
    if (!z.pointerCaptured) return;
    if (typeof z.sashEl.releasePointerCapture !== 'function') return;
    try { z.sashEl.releasePointerCapture(z.pointerId); } catch (e) {}
  },

  _cancelResize(restore = true) {
    const z = this._resize;
    this._cleanupResizeBody();
    if (!z) { this._resize = null; return; }
    this._removeResizeListeners();
    if (restore) this._restoreResizeFlex(z);
    this._releaseResizeCapture(z);
    try { z.sashEl.classList.remove('sash-active'); } catch (e) {}
    this._resize = null;
  },

  _onDblClick(ev) {
    const sashEl = ev.target.closest('.sash');
    if (!sashEl) return;
    const pEl = sashEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) return;
    const n = (pEl.children.length + 1) / 2;
    const path = this._parsePath(pEl.dataset.path);
    this.root = SashCore.setSplitSizesByPath(this.root, path, new Array(n).fill(100 / n));
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') LogConsole.log('📏 Split reset to even sizes', 'info');
  },

  simulateResize(pathStr, firstPct) {
    const path = this._parsePath(pathStr);
    const p = SashCore.nodeAtPath(this.root, path);
    if (!p) throw new Error('simulateResize: bad path ' + pathStr);
    const sizes = p.sizes.slice();
    const min = SashCore.MIN_SIZE || 4;
    const maxFirst = 100 - min * (sizes.length - 1);
    sizes[0] = Math.max(min, Math.min(Number(firstPct) || min, maxFirst));
    const rest = 100 - sizes[0];
    const restSum = sizes.slice(1).reduce((a, b) => a + b, 0) || 1;
    for (let i = 1; i < sizes.length; i++) sizes[i] = rest * (sizes[i] / restSum);
    this.root = SashCore.setSplitSizesByPath(this.root, path, sizes);
    this.render();
    this._save();
    return this.getTree();
  },
};
