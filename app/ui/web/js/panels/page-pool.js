/* page-pool.js — Multi-page parallel dispatch panel
   Shows steady/busy/cooling pages, per-tab cooldown countdowns with
   reset/edit, allows connect additional pages, clear pool.
   Requirement: when 2+ webpages connected and 2+ images pending, dispatch
   to different pages selecting steady. After each job the tab auto-clicks
   New Chat, waits for full load, then cools down (spec 01-04).
*/
'use strict';

const PagePoolPanel = {
  snapshot: {total:0, steady:0, busy:0, cooling:0, free:0, pages:[]},
  snapAt: 0,

  init() {
    document.getElementById('poolRefreshBtn')?.addEventListener('click', ()=>this.refresh());
    document.getElementById('poolClearBtn')?.addEventListener('click', ()=>this.clear());
    document.getElementById('poolConnectBtn')?.addEventListener('click', ()=>this.connectFromSelect());
    setTimeout(()=>this.refresh(), 1200);
    setInterval(()=>this.refresh(), 5000);
    setInterval(()=>this.tickCountdowns(), 1000);
  },

  refresh() {
    if (App.bridge && App.bridge.get_page_pool_status) {
      try {
        App.bridge.get_page_pool_status((res)=>{
          try {
            const snap = JSON.parse(res);
            if (snap.error) { LogConsole.log('Pool status error: '+snap.error, 'warn'); return; }
            this.onUpdate(JSON.stringify(snap));
          } catch(e){ LogConsole.log('Pool parse failed '+e, 'warn'); }
        });
      } catch(e) {
        try {
          const res = App.bridge.get_page_pool_status();
          if (res) this.onUpdate(res);
        } catch {}
      }
    }
  },

  clear() {
    if (App.bridge && App.bridge.clear_page_pool) {
      App.bridge.clear_page_pool((res)=>{
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? `Pool cleared ${r.cleared} pages` : 'Pool clear failed '+r.error, r.ok?'warn':'error');
          this.refresh();
        } catch {}
      });
    }
  },

  connectFromSelect() {
    const sel = document.getElementById('tabSelect');
    const ws = sel ? sel.value : '';
    if (!ws) { LogConsole.log('⚠ Select a Chrome tab first to add to pool', 'warn'); return; }
    LogConsole.log(`🔗 Adding tab to pool ${ws.slice(0,60)}… steady mode`, 'info');
    if (App.bridge && App.bridge.connect_page_pool) {
      App.bridge.connect_page_pool(ws, (res)=>{
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? 'Pool connect queued' : 'Pool connect failed '+r.error, r.ok?'info':'error');
        } catch {}
      });
    }
  },

  disconnect(tabId) {
    if (App.bridge && App.bridge.disconnect_page_pool) {
      App.bridge.disconnect_page_pool(tabId, (res)=>{
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? `Pool page ${tabId.slice(0,8)} disconnected` : 'Disconnect failed '+r.error, r.ok?'info':'error');
          this.refresh();
        } catch {}
      });
    }
  },

  resetCooldown(tabId) {
    if (App.bridge && App.bridge.reset_page_cooldown) {
      App.bridge.reset_page_cooldown(tabId, (res)=>{
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? `♻️ Cooldown reset for ${tabId.slice(0,8)} — tab ready` : 'Reset failed: '+r.error, r.ok?'success':'error');
          this.refresh();
        } catch {}
      });
    }
  },

  editCooldown(tabId) {
    const ask = (onOk) => {
      if (window.Dialog && Dialog.promptName) {
        Dialog.promptName('Edit cooldown', 'Minutes remaining (0 = ready now)', 'Set', onOk);
      } else if (typeof prompt === 'function') {
        const v = prompt('Minutes remaining (0 = ready now):', '5');
        if (v !== null) onOk(v);
      }
    };
    ask((val) => {
      const mins = parseFloat(String(val).replace(',', '.'));
      if (isNaN(mins) || mins < 0 || mins > 1440) { LogConsole.log('⚠ Enter 0-1440 minutes', 'warn'); return; }
      const secs = Math.round(mins * 60);
      if (App.bridge && App.bridge.set_page_cooldown) {
        App.bridge.set_page_cooldown(tabId, secs, (res)=>{
          try {
            const r = JSON.parse(res);
            LogConsole.log(r.ok ? `⏳ Cooldown for ${tabId.slice(0,8)} set to ${this.fmt(secs)}` : 'Edit failed: '+r.error, r.ok?'info':'error');
            this.refresh();
          } catch {}
        });
      }
    });
  },

  onUpdate(payload) {
    try {
      const snap = typeof payload === 'string' ? JSON.parse(payload) : payload;
      this.snapshot = snap;
      this.snapAt = Date.now();
      this.render(snap);
    } catch(e){ console.warn('pool onUpdate failed', e); }
  },

  fmt(totalSecs) {
    const s = Math.max(0, Math.round(totalSecs || 0));
    const m = Math.floor(s / 60), sec = s % 60;
    if (m < 60) return String(m).padStart(2,'0')+':'+String(sec).padStart(2,'0');
    return Math.floor(m/60)+':'+String(m%60).padStart(2,'0')+':'+String(sec).padStart(2,'0');
  },

  cooldownCell(p) {
    const remaining = p.cooldown_remaining || 0;
    const total = p.cooldown_total || 0;
    const captcha = p.captcha_count || 0;
    const pending = p.pending_penalty || 0;
    const badge = captcha > 0 ? ` <span title="Captcha detections on this tab">🛡x${captcha}</span>` : '';
    if ((p.status || '') === 'cooldown' && remaining > 0) {
      const of = total > 0 ? ` / ${this.fmt(total)}` : '';
      const title = this.esc(p.cooldown_reason || 'cooling');
      return `<span data-cool-tab="${this.esc(p.tab_id)}" data-cool-left="${remaining}" title="${title}">${this.fmt(remaining)}${of}</span>${badge}`;
    }
    if (pending > 0) {
      return `<span title="Captcha penalty waiting for next cooldown">+${this.fmt(pending)} pending</span>${badge}`;
    }
    if (captcha > 0) return `<span title="No active timer">—</span>${badge}`;
    return '—';
  },

  tickCountdowns() {
    if (!this.snapAt) return;
    const elapsed = Math.floor((Date.now() - this.snapAt) / 1000);
    let expired = false;
    document.querySelectorAll('[data-cool-tab]').forEach(el => {
      const left = Math.max(0, parseInt(el.getAttribute('data-cool-left') || '0', 10) - elapsed);
      const txt = el.textContent;
      const suffix = txt.includes('/') ? txt.slice(txt.indexOf('/')) : '';
      el.textContent = this.fmt(left) + (suffix ? ' ' + suffix : '');
      if (left <= 0) expired = true;
    });
    if (expired) { this.snapAt = 0; this.refresh(); }
  },

  statusColor(status) {
    if (status === 'cooldown') return '#ff9500';
    if (status === 'busy' || status === 'waiting_generation') return '#4dabf7';
    if (status === 'waiting_captcha' || status === 'error') return '#ff6b6b';
    if (status === 'disconnected') return '#888';
    return '#4ade80';
  },

  render(snap) {
    if (!snap) return;
    const setText = (id, txt) => { const el=document.getElementById(id); if(el) el.textContent=txt; };
    setText('poolTotal', snap.total||0);
    setText('poolSteady', snap.steady||0);
    setText('poolBusy', snap.busy||0);
    setText('poolCooling', snap.cooling||0);
    setText('poolFree', snap.free||snap.steady||0);
    const badge = document.getElementById('poolStatusBadge');
    if (badge) {
      const coolTxt = snap.cooling>0 ? ` ${snap.cooling} cooling` : '';
      if (snap.total>=2) {
        badge.textContent = `✅ ${snap.total} pages ${snap.steady} steady ${snap.busy} busy${coolTxt} — parallel ready`;
        badge.style.background='var(--bg-success,#1a3a1a)'; badge.style.color='#4ade80';
      } else if (snap.total===1) {
        badge.textContent = `⚠ ${snap.total} page only — connect 2nd tab for parallel`;
        badge.style.background='rgba(180,120,20,0.3)'; badge.style.color='#ffcc00';
      } else {
        badge.textContent = `${snap.total} pages ${snap.steady} steady ${snap.busy} busy${coolTxt}`;
        badge.style.background='var(--bg-input)'; badge.style.color='var(--text-muted)';
      }
      if (snap.busy>0) {
        badge.textContent = `${snap.total} pages ${snap.steady} steady ${snap.busy} busy${coolTxt}`;
        badge.style.background='rgba(20,80,180,0.9)'; badge.style.color='#fff';
        if (snap.total>=2) badge.textContent = `⏳ ${snap.total} pages ${snap.steady} steady ${snap.busy} busy${coolTxt} — parallel running`;
      } else if (snap.cooling>0 && snap.total>=1) {
        badge.textContent = `⏳ ${snap.total} pages ${snap.steady} steady${coolTxt} — waiting for cooldown`;
        badge.style.background='rgba(180,120,20,0.9)'; badge.style.color='#fff';
      }
    }
    const tbody = document.getElementById('poolTableBody');
    if (!tbody) return;
    tbody.innerHTML='';
    (snap.pages||[]).forEach(p=>{
      const tr = document.createElement('tr');
      const status = p.status||'steady';
      const color = this.statusColor(status);
      const statusLabel = status==='steady' ? 'steady (ready)' : status;
      tr.innerHTML = `
        <td title="${this.esc(p.tab_id)}">${this.esc((p.tab_id||'').slice(0,12))}</td>
        <td title="${this.esc(p.title)}">${this.esc((p.title||'').slice(0,30))}</td>
        <td title="${this.esc(p.url)}" style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${this.esc((p.url||'').slice(0,50))}</td>
        <td><span style="color:${color}; font-weight:600;">● ${this.esc(statusLabel)}</span></td>
        <td title="Jobs completed — next job goes to the free tab with the lowest count">${p.jobs_completed||0}</td>
        <td>${this.esc(p.current_job_id||'—')}</td>
        <td style="white-space:nowrap;">${this.cooldownCell(p)}</td>
        <td style="white-space:nowrap;">
          <button class="btn-small" data-cool-reset="${this.esc(p.tab_id)}" title="Reset cooldown — tab ready now">♻️</button>
          <button class="btn-small" data-cool-edit="${this.esc(p.tab_id)}" title="Edit cooldown timer">✎</button>
          <button class="btn-small" data-disconnect="${this.esc(p.tab_id)}" title="Remove from pool">✕</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button[data-disconnect]').forEach(btn=>{
      btn.addEventListener('click', ()=>this.disconnect(btn.getAttribute('data-disconnect')));
    });
    tbody.querySelectorAll('button[data-cool-reset]').forEach(btn=>{
      btn.addEventListener('click', ()=>this.resetCooldown(btn.getAttribute('data-cool-reset')));
    });
    tbody.querySelectorAll('button[data-cool-edit]').forEach(btn=>{
      btn.addEventListener('click', ()=>this.editCooldown(btn.getAttribute('data-cool-edit')));
    });
  },

  esc(s){ if(!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
};
