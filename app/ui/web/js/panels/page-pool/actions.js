/* page-pool/actions.js — bridge actions, ≤200 LOC, CC≤10 */
'use strict';
window.PagePoolActions = {
  _store() { return window.PagePoolStore; },
  _render() { return window.PagePoolRender; },
  _bridge() { return window.App && window.App.bridge; },

  refresh() {
    const b = this._bridge();
    if (!b?.get_page_pool_status) return;
    try {
      b.get_page_pool_status((res)=>{
        try {
          const snap = JSON.parse(res);
          if (snap.error) { LogConsole.log('Pool status error: '+snap.error, 'warn'); return; }
          this.onUpdate(JSON.stringify(snap));
        } catch(e){ LogConsole.log('Pool parse failed '+e, 'warn'); }
      });
    } catch(e) {
      try {
        const res = b.get_page_pool_status();
        if (res) this.onUpdate(res);
      } catch {}
    }
  },

  clear() {
    const b = this._bridge();
    if (!b?.clear_page_pool) return;
    b.clear_page_pool((res)=>{
      try {
        const r = JSON.parse(res);
        LogConsole.log(r.ok ? `Pool cleared ${r.cleared} pages` : 'Pool clear failed '+r.error, r.ok?'warn':'error');
        this.refresh();
      } catch {}
    });
  },

  connectFromSelect() {
    const sel = document.getElementById('tabSelect');
    const ws = sel ? sel.value : '';
    if (!ws) { LogConsole.log('⚠ Select a Chrome tab first to add to pool', 'warn'); return; }
    LogConsole.log(`🔗 Adding tab to pool ${ws.slice(0,60)}… steady mode`, 'info');
    const b = this._bridge();
    if (b?.connect_page_pool) {
      b.connect_page_pool(ws, (res)=>{
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? 'Pool connect queued' : 'Pool connect failed '+r.error, r.ok?'info':'error');
        } catch {}
      });
    }
  },

  disconnect(tabId) {
    const b = this._bridge();
    if (!b?.disconnect_page_pool) return;
    b.disconnect_page_pool(tabId, (res)=>{
      try {
        const r = JSON.parse(res);
        LogConsole.log(r.ok ? `Pool page ${window.TabLabel.of(tabId)} disconnected` : 'Disconnect failed '+r.error, r.ok?'info':'error');
        this.refresh();
      } catch {}
    });
  },

  resetCooldown(tabId) {
    const b = this._bridge();
    if (!b?.reset_page_cooldown) return;
    b.reset_page_cooldown(tabId, (res)=>{
      try {
        const r = JSON.parse(res);
        // D-5: the reply now says what was removed — and a live job keeps its page.
        LogConsole.log(r.ok ? this._clearMsg(tabId, r) : 'Reset failed: '+r.error, r.ok?(r.busy?'warn':'success'):'error');
        this.refresh();
      } catch {}
    });
  },

  _clearMsg(tabId, r) {
    const label = window.TabLabel.of(tabId);
    const was = (window.PagePoolPanel ? window.PagePoolPanel.fmt(r.was || 0) : `${r.was || 0}s`);
    if (r.busy) return `⏳ Clear time: ${label} still busy — ${was} removed, the job keeps its page`;
    return `♻️ Clear time: ${label} ready now — ${was} removed`;
  },

  _parseMinutes(val) {
    const mins = parseFloat(String(val).replace(',', '.'));
    if (isNaN(mins) || mins < 0 || mins > 1440) return null;
    return mins;
  },

  _onEditInput(tabId, val) {
    const mins = this._parseMinutes(val);
    if (mins === null) { LogConsole.log('⚠ Enter 0-1440 minutes', 'warn'); return; }
    const secs = Math.round(mins * 60);
    const b = this._bridge();
    if (!b?.set_page_cooldown) return;
    b.set_page_cooldown(tabId, secs, (res)=>{
      try {
        const r = JSON.parse(res);
        LogConsole.log(r.ok ? `⏳ Cooldown for ${window.TabLabel.of(tabId)} set to ${this._store().fmt(secs)}` : 'Edit failed: '+r.error, r.ok?'info':'error');
        this.refresh();
      } catch {}
    });
  },

  editCooldown(tabId) {
    const ask = (onOk) => {
      if (window.Dialog?.promptName) {
        Dialog.promptName('Edit cooldown', 'Minutes remaining (0 = ready now)', 'Set', onOk);
      } else if (typeof prompt === 'function') {
        const v = prompt('Minutes remaining (0 = ready now):', '5');
        if (v !== null) onOk(v);
      }
    };
    ask((val) => this._onEditInput(tabId, val));
  },

  onUpdate(payload) {
    try {
      const snap = typeof payload === 'string' ? JSON.parse(payload) : payload;
      this._store().setSnapshot(snap);
      this._render().render(snap, this);
    } catch(e){ console.warn('pool onUpdate failed', e); }
  },

  tickCountdowns() { return window.PagePoolTicker.tick(); },
};
