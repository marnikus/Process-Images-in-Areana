/* page-pool.js — Multi-page parallel dispatch panel
   Shows steady/busy pages, allows connect additional pages, clear pool.
   Requirement: when 2+ webpages connected and 2+ images pending, dispatch to different pages selecting steady.
*/
'use strict';

const PagePoolPanel = {
  snapshot: {total:0, steady:0, busy:0, free:0, pages:[]},

  init() {
    document.getElementById('poolRefreshBtn')?.addEventListener('click', ()=>this.refresh());
    document.getElementById('poolClearBtn')?.addEventListener('click', ()=>this.clear());
    document.getElementById('poolConnectBtn')?.addEventListener('click', ()=>this.connectFromSelect());
    setTimeout(()=>this.refresh(), 1200);
    setInterval(()=>this.refresh(), 5000);
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

  onUpdate(payload) {
    try {
      const snap = typeof payload === 'string' ? JSON.parse(payload) : payload;
      this.snapshot = snap;
      this.render(snap);
    } catch(e){ console.warn('pool onUpdate failed', e); }
  },

  render(snap) {
    if (!snap) return;
    const setText = (id, txt) => { const el=document.getElementById(id); if(el) el.textContent=txt; };
    setText('poolTotal', snap.total||0);
    setText('poolSteady', snap.steady||0);
    setText('poolBusy', snap.busy||0);
    setText('poolFree', snap.free||snap.steady||0);
    const badge = document.getElementById('poolStatusBadge');
    if (badge) {
      if (snap.total>=2) {
        badge.textContent = `✅ ${snap.total} pages ${snap.steady} steady ${snap.busy} busy — parallel ready`;
        badge.style.background='var(--bg-success,#1a3a1a)'; badge.style.color='#4ade80';
      } else if (snap.total===1) {
        badge.textContent = `⚠ ${snap.total} page only — connect 2nd tab for parallel`;
        badge.style.background='rgba(180,120,20,0.3)'; badge.style.color='#ffcc00';
      } else {
        badge.textContent = `${snap.total} pages ${snap.steady} steady ${snap.busy} busy`;
        badge.style.background='var(--bg-input)'; badge.style.color='var(--text-muted)';
      }
      if (snap.busy>0) {
        badge.textContent = `${snap.total} pages ${snap.steady} steady ${snap.busy} busy`;
        badge.style.background='rgba(20,80,180,0.9)'; badge.style.color='#fff';
        if (snap.total>=2) badge.textContent = `⏳ ${snap.total} pages ${snap.steady} steady ${snap.busy} busy — parallel running`;
      }
    }
    const tbody = document.getElementById('poolTableBody');
    if (!tbody) return;
    tbody.innerHTML='';
    (snap.pages||[]).forEach(p=>{
      const tr = document.createElement('tr');
      const status = p.status||'steady';
      const isBusy = status==='busy' || status==='waiting_generation' || status==='waiting_captcha';
      const isCooldown = status==='cooldown' || p.in_cooldown;
      let color = '#4ade80';
      if (isBusy) color = status.includes('captcha') ? '#ff6b6b' : '#4dabf7';
      else if (isCooldown) color = '#ff9500';
      const cdRem = p.cooldown_remaining || 0;
      const cdStr = cdRem ? `${cdRem}s` : (isCooldown ? 'cooldown' : '');
      const cap = p.captcha_count ? ` ⚠x${p.captcha_count}` : '';
      tr.innerHTML = `
        <td title="${this.esc(p.tab_id)}">${this.esc((p.tab_id||'').slice(0,12))}</td>
        <td title="${this.esc(p.title)}">${this.esc((p.title||'').slice(0,30))}</td>
        <td title="${this.esc(p.url)}" style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${this.esc((p.url||'').slice(0,50))}</td>
        <td><span style="color:${color}; font-weight:600;">● ${this.esc(status)}${cdStr ? ` ${cdStr}` : ''}${cap}</span></td>
        <td>${this.esc(p.current_job_id||'—')}</td>
        <td><button class="btn-small" data-disconnect="${this.esc(p.tab_id)}" title="Remove from pool">✕</button></td>
      `;
      if (isCooldown) tr.style.background = 'rgba(255,149,0,0.08)';
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('button[data-disconnect]').forEach(btn=>{
      btn.addEventListener('click', ()=>this.disconnect(btn.getAttribute('data-disconnect')));
    });
  },

  esc(s){ if(!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
};
