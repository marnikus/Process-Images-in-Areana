/* prompt-presets.js — Save / Restore / Remove prompt presets (BUG 03.6)
   RULE18: file 150-300, func <= 30, CC <= 10

   Root cause: arena-presets/actions.js injected its own preset bar into
   #winPrompt with ids promptPresetName / promptPresetSelect, while
   index.html already ships promptPresetNameInput / promptPresetSaveBtn /
   promptPresetsList inside #winArenaPresets. Two elements shared the id
   promptPresetSaveBtn, so getElementById() returned the *static* one — the
   one nobody had bound. Restore and Remove existed only in the injected bar.

   This module binds the static markup, injects nothing, and owns the three
   actions end to end.
*/
'use strict';

window.PromptPresets = {
  requires: ['promptPresetNameInput', 'promptPresetSaveBtn', 'promptPresetsList'],
  _presets: [],

  init() {
    const save = document.getElementById('promptPresetSaveBtn');
    const name = document.getElementById('promptPresetNameInput');
    const list = document.getElementById('promptPresetsList');
    save.addEventListener('click', () => this.save());
    name.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.save(); });
    list.addEventListener('click', (e) => this._onListClick(e));
    this.refresh();
  },

  _log(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level || 'info');
  },

  _textarea() {
    return document.getElementById('promptTextarea')
      || document.getElementById('promptInput');
  },

  esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },

  /* ---- actions ---- */
  save() {
    const nameEl = document.getElementById('promptPresetNameInput');
    const name = (nameEl.value || '').trim();
    if (!name) { this._log('⚠ Enter a prompt preset name first', 'warn'); nameEl.focus(); return; }
    const ta = this._textarea();
    const template = ta ? ta.value : '';
    if (!template.trim()) { this._log('⚠ Prompt is empty — nothing to save', 'warn'); return; }
    BridgeCall.run('save_prompt_preset', [name, template], {
      failPrefix: 'Save prompt preset failed',
      success: () => `💾 Prompt preset saved: ${name}`,
      onOk: () => { nameEl.value = ''; this.refresh(); },
    });
  },

  restore(name) {
    BridgeCall.invoke('load_prompt_preset', [name], (r) => {
      if (r.ok === false) { this._log(`Restore failed: ${r.error || name}`, 'error'); return; }
      const ta = this._textarea();
      if (!ta) { this._log('Prompt editor not mounted', 'error'); return; }
      ta.value = r.template !== undefined ? r.template : (r.value || '');
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      this._log(`↩ Prompt preset restored: ${name}`, 'success');
    });
  },

  remove(name) {
    const go = () => BridgeCall.run('delete_prompt_preset', [name], {
      failPrefix: 'Remove prompt preset failed',
      success: () => `🗑 Prompt preset removed: ${name}`,
      onOk: () => this.refresh(),
    });
    if (window.Dialog && Dialog.confirm) Dialog.confirm('Remove preset', `Remove "${name}"?`, 'Remove', go);
    else go();
  },

  /* ---- list ---- */
  refresh() {
    BridgeCall.invoke('list_prompt_presets', [], (r) => {
      this._presets = this._normalise(r);
      this.render();
    });
  },

  _normalise(r) {
    const raw = Array.isArray(r) ? r : (r.presets || r.value || []);
    if (!Array.isArray(raw)) return [];
    return raw.map((p) => (typeof p === 'string'
      ? { name: p, template: '' }
      : { name: p.name || '', template: p.template || '' })).filter((p) => p.name);
  },

  _row(p) {
    const preview = this.esc((p.template || '').slice(0, 60));
    return `<div class="preset-row" data-name="${this.esc(p.name)}">
      <span class="preset-name" title="${preview}">${this.esc(p.name)}</span>
      <span class="preset-actions">
        <button class="btn-small" data-preset-action="restore">Restore</button>
        <button class="btn-small" data-preset-action="remove">Remove</button>
      </span>
    </div>`;
  },

  render() {
    const list = document.getElementById('promptPresetsList');
    if (!list) return;
    list.innerHTML = this._presets.length
      ? this._presets.map((p) => this._row(p)).join('')
      : '<div class="preset-empty" style="padding:6px; font-size:11px; color:var(--text-muted)">No prompt presets yet — type a name and press Save Prompt.</div>';
    const count = document.getElementById('promptPresetsCount');
    if (count) count.textContent = `${this._presets.length} prompt presets`;
  },

  _onListClick(e) {
    const btn = e.target.closest('button[data-preset-action]');
    if (!btn) return;
    const row = btn.closest('.preset-row');
    const name = row && row.dataset.name;
    if (!name) return;
    if (btn.dataset.presetAction === 'restore') this.restore(name);
    else this.remove(name);
  },
};
