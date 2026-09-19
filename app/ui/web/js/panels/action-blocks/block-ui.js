/* block-ui.js — C12 split: pause overlay + drag cleanup + global handlers + keydown
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksUI = {
  _cleanSashLeftovers() {
    try {
      const body = document.body;
      const needsClean = body.classList.contains('sash-dragging') || body.classList.contains('sash-resizing-row');
      if (!needsClean) return;
      const sg = window.SashGrid;
      if (!sg || (!sg._drag && !sg._resize)) {
        body.classList.remove('sash-dragging', 'sash-resizing-row', 'sash-resizing-col');
      }
    } catch {}
  },

  _cleanupDragState(panel) {
    try {
      panel._dragSrc = null;
      const cont = document.getElementById('actionBlocksStack');
      if (cont) cont.querySelectorAll('.ab-block').forEach(el => el.classList.remove('dragging', 'drag-over'));
      document.body.classList.remove('sash-dragging', 'sash-resizing-row', 'sash-resizing-col');
      document.querySelectorAll('.sash-active').forEach(el => el.classList.remove('sash-active'));
      document.querySelectorAll('.sash-drag-clone, .sash-drag-ghost').forEach(el => { if (el.parentNode) el.parentNode.removeChild(el); });
    } catch {}
  },

  ensurePauseOverlay() {
    if (document.getElementById('pauseCornerOverlay')) return;
    const div = document.createElement('div');
    div.id = 'pauseCornerOverlay';
    div.innerHTML = '<span class="material-icons">hourglass_top</span><div><div style="font-size:12px;">ON PAUSE</div><div id="pauseCornerReason" style="font-size:10px; opacity:0.8;">Captcha detected</div></div>';
    document.body.appendChild(div);
  },

  attachGlobalHandlers(panel) {
    window.addEventListener('arena-presets-updated', () => panel.load());
    document.addEventListener('keydown', (e) => panel.handleKeydown(e));
    window.addEventListener('blur', () => this._cleanupDragState(panel));
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this._cleanupDragState(panel);
    });
    document.addEventListener('pointerup', () => this._cleanSashLeftovers());
  },

  handleKeydown(panel, e) {
    if (!e.altKey) return;
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    const stack = document.getElementById('actionBlocksStack');
    if (!stack || panel.selectedIdx < 0) return;
    e.preventDefault();
    if (e.key === 'ArrowUp' && panel.selectedIdx > 0) panel.moveBlock(panel.selectedIdx, panel.selectedIdx - 1);
    if (e.key === 'ArrowDown' && panel.selectedIdx < panel.blocks.length - 1) panel.moveBlock(panel.selectedIdx, panel.selectedIdx + 1);
  },
};

if (typeof window !== 'undefined') window.ActionBlocksUI = window.ActionBlocksUI;
