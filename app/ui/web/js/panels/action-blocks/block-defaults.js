/* block-defaults.js — default blocks are always restorable (BUG 03.2)
   RULE18: file 150-300, func <= 30, CC <= 10

   Two defects fixed here:
   1. The panel rendered into #panel-action-blocks, but index.html ships
      #winActionBlocks / #actionBlocksStack — the container never resolved,
      so the stack looked "gone" even when Python held 16 blocks.
   2. Python owned reset_action_blocks() but no button ever called it, so an
      emptied stack could not be brought back from the UI.

   This module owns: container resolution, the empty state, the
   "Restore defaults" / "Re-add missing" controls, and the image-processing
   chain guarantee.
*/
'use strict';

window.BlockDefaults = {
  requires: ['actionBlocksStack'],

  /* The image-processing chain — must always be offered for restore. */
  REQUIRED: ['OBSERVE_BASELINE', 'ATTACH_IMAGE', 'VERIFY_ATTACHMENT',
    'INSERT_PROMPT', 'VERIFY_PROMPT', 'SUBMIT', 'WAIT_OUTPUT',
    'DOWNLOAD', 'VALIDATE', 'SAVE', 'ADVANCE'],

  init() {
    this.mountToolbar();
    this.renderEmptyStateIfNeeded([]);
  },

  _log(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level || 'info');
  },

  /* Container lookup with the historical id as a fallback, so the panel
     works against old and new markup. */
  stackEl() {
    return document.getElementById('actionBlocksStack')
      || document.querySelector('#winActionBlocks .ab-stack')
      || document.getElementById('panel-action-blocks');
  },

  toolbarEl() {
    const stack = this.stackEl();
    if (!stack) return null;
    let bar = document.getElementById('actionBlocksDefaultsBar');
    if (bar) return bar;
    bar = document.createElement('div');
    bar.id = 'actionBlocksDefaultsBar';
    bar.className = 'ab-defaults-bar';
    bar.style.cssText = 'display:flex; gap:6px; margin:0 0 8px 0; flex-wrap:wrap;';
    stack.parentNode.insertBefore(bar, stack);
    return bar;
  },

  mountToolbar() {
    const bar = this.toolbarEl();
    if (!bar || bar.dataset.bound === '1') return;
    bar.innerHTML = `
      <button id="blocksRestoreDefaultsBtn" class="btn-small btn-primary"
        title="Replace the stack with the default image-processing chain">↺ Restore defaults</button>
      <button id="blocksAddMissingBtn" class="btn-small"
        title="Keep custom blocks, re-add only the missing required ones">＋ Re-add missing</button>
      <span id="blocksDefaultsHint" style="font-size:11px; color:var(--text-muted); align-self:center;"></span>`;
    bar.dataset.bound = '1';
    document.getElementById('blocksRestoreDefaultsBtn')
      .addEventListener('click', () => this.restoreDefaults(false));
    document.getElementById('blocksAddMissingBtn')
      .addEventListener('click', () => this.restoreDefaults(true));
  },

  /* ---- actions ---- */
  restoreDefaults(mergeMissing) {
    const go = () => BridgeCall.run('restore_default_blocks', [!!mergeMissing], {
      failPrefix: 'Restore default blocks failed',
      success: (r) => (mergeMissing
        ? `🧱 Re-added ${(r.added || []).length} missing block(s)`
        : `🧱 Default block stack restored (${(r.blocks || []).length} blocks)`),
      onOk: (r) => this.afterRestore(r),
    });
    if (mergeMissing) { go(); return; }
    if (window.Dialog && Dialog.confirm) {
      Dialog.confirm('Restore default blocks',
        'Replace the current stack with the default image-processing chain?',
        'Restore', go);
    } else go();
  },

  afterRestore(r) {
    const blocks = r.blocks || [];
    if (window.ActionBlocksPanel && ActionBlocksPanel.onBlocksUpdated) {
      ActionBlocksPanel.onBlocksUpdated(JSON.stringify(blocks));
    }
    this.renderEmptyStateIfNeeded(blocks);
    this.updateHint(blocks);
  },

  /* ---- state rendering ---- */
  missingRequired(blocks) {
    const have = new Set((blocks || []).map((b) => b.block_id || b.type));
    return this.REQUIRED.filter((id) => !have.has(id));
  },

  updateHint(blocks) {
    const hint = document.getElementById('blocksDefaultsHint');
    if (!hint) return;
    const missing = this.missingRequired(blocks);
    hint.textContent = missing.length
      ? `${missing.length} required block(s) missing: ${missing.slice(0, 3).join(', ')}${missing.length > 3 ? '…' : ''}`
      : 'image-processing chain complete';
    hint.style.color = missing.length ? 'var(--warn, #d08770)' : 'var(--text-muted)';
  },

  renderEmptyStateIfNeeded(blocks) {
    const stack = this.stackEl();
    if (!stack) { this._log('❌ Action blocks container not found in DOM', 'error'); return; }
    this.updateHint(blocks);
    if (blocks && blocks.length) return;
    stack.innerHTML = `<div class="ab-empty" style="padding:14px; text-align:center; font-size:12px; color:var(--text-muted);">
        No action blocks in the stack.

        <b>Restore defaults</b> brings back the full image-processing chain.
      </div>`;
  },

  /* Called by ActionBlocksPanel whenever Python pushes a new stack. */
  onBlocks(blocks) {
    this.mountToolbar();
    this.renderEmptyStateIfNeeded(blocks || []);
  },
};
