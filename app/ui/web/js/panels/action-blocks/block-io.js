/* action-blocks/block-io.js — save/export/import, ≤100 LOC, CC≤10 */
'use strict';
window.ActionBlocksIO = {
  _store() { return window.ActionBlocksStore; },
  _render() { return window.ActionBlocksRender; },

  save(panel) {
    panel._store.save();
    panel.saveDebouncedPush();
  },

  saveDebouncedPush(panel) {
    clearTimeout(panel._saveTimer);
    panel._saveTimer = setTimeout(() => {
      try {
        const bridge = window.App && window.App.bridge;
        if (bridge && bridge.push_global_history) bridge.push_global_history('action_blocks', JSON.stringify(panel.blocks));
      } catch {}
    }, 600);
  },

  exportBlocks(blocks) {
    const payload = JSON.stringify(blocks, null, 2);
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.export_action_blocks) {
      try { const res = bridge.export_action_blocks(payload); if (typeof res === 'string') { this._onExported(res); return; } } catch {}
      try { bridge.export_action_blocks(payload, r => this._onExported(r)); return; } catch {}
    }
    const blob = new Blob([payload], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `arena-action-blocks-${new Date().toISOString().slice(0,10)}.json`; a.click();
    URL.revokeObjectURL(url);
  },

  importBlocks(panel, onLoaded) {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.json';
    input.onchange = (e) => {
      const file = e.target.files[0]; if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          const data = JSON.parse(ev.target.result);
          if (Array.isArray(data)) onLoaded(data);
        } catch {}
      };
      reader.readAsText(file);
    };
    input.click();
  },

  _onExported(res) {
    try {
      const r = typeof res === 'string' ? JSON.parse(res) : res;
      if (r && r.ok && typeof LogConsole !== 'undefined') LogConsole.log(`📤 Exported to ${r.path || ''}`, 'success');
    } catch {}
  },
};
