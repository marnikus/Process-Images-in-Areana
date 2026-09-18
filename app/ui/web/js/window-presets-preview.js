/* window-presets-preview.js — file picker + preview for WindowPresets facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const WindowPresetsPreview = {
  _openFilePicker() {
    const input = document.getElementById('windowPresetFileInput');
    if (input) input.click();
  },

  _readFile(event) {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = SashGrid.validatePortablePreset(reader.result);
      if (!result.ok) { this._message('Import rejected: ' + result.error, 'error'); return; }
      this._showPreview(result.document, 'import');
    };
    reader.onerror = () => this._message('Import failed: the file could not be read.', 'error');
    reader.readAsText(file);
  },

  _showPreview(preset, action) {
    const result = SashGrid.validatePortablePreset(preset);
    if (!result.ok) { this._message('Preview unavailable: ' + result.error, 'error'); return; }
    this.pending = { document: result.document, action };
    const menu = document.getElementById('layoutMenu');
    if (menu) menu.classList.add('hidden');
    const modal = documentById('windowPresetPreviewModal');
    const title = documentById('windowPresetPreviewTitle');
    const meta = documentById('windowPresetPreviewMeta');
    const canvas = documentById('windowPresetPreviewCanvas');
    if (!modal || !title || !meta || !canvas) return;
    title.textContent = 'Preview: ' + result.document.name;
    meta.textContent = this._previewMeta(result.document, result.warning);
    canvas.replaceChildren();
    if (result.document.screen && result.document.screen.synthetic) {
      // Legacy preset: no per-window bounds were saved — full-size tiles would
      // just overlap, so show the note instead (layout + states still apply).
      const note = document.createElement('div');
      note.className = 'window-preset-preview-note';
      note.textContent = 'Legacy preset — saved before per-window positions. Layout and window states will be applied.';
      canvas.appendChild(note);
    } else {
      result.document.windows.forEach((item) => {
        const tile = document.createElement('div');
        tile.className = 'window-preset-preview-tile state-' + item.state;
        tile.style.left = (item.bounds.x * 100) + '%';
        tile.style.top = (item.bounds.y * 100) + '%';
        tile.style.width = (item.bounds.width * 100) + '%';
        tile.style.height = (item.bounds.height * 100) + '%';
        tile.textContent = item.title || item.id;
        canvas.appendChild(tile);
      });
    }
    modal.classList.remove('hidden');
  },

  _previewMeta(document, warning) {
    const parts = [];
    const synthetic = !!(document.screen && document.screen.synthetic);
    if (synthetic) {
      parts.push(document.grid.window_count + ' windows · legacy preset (no per-window positions)');
    } else {
      const resolution = document.screen.width + '×' + document.screen.height;
      const note = SashGrid._screenSnapshot(SashGrid.gridEl && SashGrid.gridEl.getBoundingClientRect ? SashGrid.gridEl.getBoundingClientRect() : { width: 1, height: 1 });
      parts.push(document.grid.window_count + ' windows · source screen ' + resolution);
      if (note.width !== document.screen.width || note.height !== document.screen.height) parts.push('target screen differs; percentages will adapt');
    }
    if (warning) parts.push(warning);
    return parts.join(' · ');
  },

  _applyPreview() {
    if (!this.pending) return;
    const pending = this.pending;
    this._closePreview();
    if (!SashGrid.applyPortablePreset(pending.document)) return;
    if (pending.action === 'import') this._persistDocument(pending.document, true);
  },

  _closePreview() {
    const modal = documentById('windowPresetPreviewModal');
    if (modal) modal.classList.add('hidden');
    this.pending = null;
  },
};

function documentById(id) { return document.getElementById(id); }

if (typeof window !== 'undefined') window.WindowPresetsPreview = WindowPresetsPreview;
