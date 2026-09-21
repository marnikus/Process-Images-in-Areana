/* page-pool/render.js — rendering, ≤200 LOC, CC≤10 via helpers */
'use strict';
window.PagePoolRender = {
  _store() { return window.PagePoolStore; },

  _setText(id, txt) {
    const el=document.getElementById(id);
    if (el) el.textContent=txt;
  },

  _badgeText(snap) {
    const coolTxt = snap.cooling>0 ? ` ${snap.cooling} cooling` : '';
    if (snap.total>=2) return `✅ ${snap.total} pages ${snap.steady} steady ${snap.busy} busy${coolTxt} — parallel ready`;
    if (snap.total===1) return `⚠ ${snap.total} page only — connect 2nd tab for parallel`;
    return `${snap.total} pages ${snap.steady} steady ${snap.busy} busy${coolTxt}`;
  },

  _badgeStyle(snap) {
    if (snap.busy>0) return { bg: 'rgba(20,80,180,0.9)', color: '#fff', text: `${snap.total} pages ${snap.steady} steady ${snap.busy} busy${snap.cooling>0?` ${snap.cooling} cooling`:''}` };
    if (snap.cooling>0 && snap.total>=1) return { bg: 'rgba(180,120,20,0.9)', color: '#fff', text: `⏳ ${snap.total} pages ${snap.steady} steady${snap.cooling>0?` ${snap.cooling} cooling`:''} — waiting for cooldown` };
    if (snap.total>=2) return { bg: 'var(--bg-success,#1a3a1a)', color: '#4ade80', text: this._badgeText(snap) };
    if (snap.total===1) return { bg: 'rgba(180,120,20,0.3)', color: '#ffcc00', text: this._badgeText(snap) };
    return { bg: 'var(--bg-input)', color: 'var(--text-muted)', text: this._badgeText(snap) };
  },

  _updateBadge(snap) {
    const badge = document.getElementById('poolStatusBadge');
    if (!badge) return;
    const st = this._badgeStyle(snap);
    badge.textContent = st.text;
    if (snap.busy>0 && snap.total>=2) badge.textContent = `⏳ ${snap.total} pages ${snap.steady} steady ${snap.busy} busy${snap.cooling>0?` ${snap.cooling} cooling`:''} — parallel running`;
    badge.style.background = st.bg;
    badge.style.color = st.color;
  },

  _updateCounts(snap) {
    this._setText('poolTotal', snap.total||0);
    this._setText('poolSteady', snap.steady||0);
    this._setText('poolBusy', snap.busy||0);
    this._setText('poolCooling', snap.cooling||0);
    this._setText('poolFree', snap.free||snap.steady||0);
  },

  _cooldownBadge(p) {
    const captcha = p.captcha_count || 0;
    return captcha > 0 ? ` <span title="Captcha detections on this tab">🛡x${captcha}</span>` : '';
  },

  _cooldownActiveHtml(p, badge) {
    const remaining = p.cooldown_remaining || 0;
    const total = p.cooldown_total || 0;
    const of = total > 0 ? ` / ${this._store().fmt(total)}` : '';
    const title = this._store().esc(p.cooldown_reason || 'cooling');
    return `<span data-cool-tab="${this._store().esc(p.tab_id)}" data-cool-left="${remaining}" title="${title}">${this._store().fmt(remaining)}${of}</span>${badge}`;
  },

  _cooldownPendingHtml(pending, badge) {
    return `<span title="Captcha penalty waiting for next cooldown">+${this._store().fmt(pending)} pending</span>${badge}`;
  },

  cooldownCell(p) {
    const remaining = p.cooldown_remaining || 0;
    const pending = p.pending_penalty || 0;
    const badge = this._cooldownBadge(p);
    if ((p.status || '') === 'cooldown' && remaining > 0) return this._cooldownActiveHtml(p, badge);
    if (pending > 0) return this._cooldownPendingHtml(pending, badge);
    if ((p.captcha_count||0) > 0) return `<span title="No active timer">—</span>${badge}`;
    return '—';
  },

  _rowHtml(p) {
    const s = this._store();
    const status = p.status||'steady';
    const color = s.statusColor(status);
    const statusLabel = status==='steady' ? 'steady (ready)' : status;
    return `
        <td title="${s.esc(p.tab_id)}" style="white-space:nowrap;"><b class="worker-no">#${Number(p.worker_no)||0}</b> ${s.esc(p.tab_id)}</td>
        <td title="${s.esc(p.title)}">${s.esc((p.title||'').slice(0,30))}</td>
        <td title="${s.esc(p.url)}" style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${s.esc((p.url||'').slice(0,50))}</td>
        <td><span style="color:${color}; font-weight:600;">● ${s.esc(statusLabel)}</span></td>
        <td title="Jobs completed — next job goes to the free tab with the lowest count">${p.jobs_completed||0}</td>
        <td>${s.esc(p.current_job_id||'—')}</td>
        <td style="white-space:nowrap;">${this.cooldownCell(p)}</td>
        <td style="white-space:nowrap;">
          <button class="btn-small" data-cool-reset="${s.esc(p.tab_id)}" title="Reset cooldown — tab ready now">♻️</button>
          <button class="btn-small" data-cool-edit="${s.esc(p.tab_id)}" title="Edit cooldown timer">✎</button>
          <button class="btn-small" data-disconnect="${s.esc(p.tab_id)}" title="Remove from pool">✕</button>
        </td>
      `;
  },

  _bindRowActions(tbody, actions) {
    tbody.querySelectorAll('button[data-disconnect]').forEach(btn=>{
      btn.addEventListener('click', ()=>actions.disconnect(btn.getAttribute('data-disconnect')));
    });
    tbody.querySelectorAll('button[data-cool-reset]').forEach(btn=>{
      btn.addEventListener('click', ()=>actions.resetCooldown(btn.getAttribute('data-cool-reset')));
    });
    tbody.querySelectorAll('button[data-cool-edit]').forEach(btn=>{
      btn.addEventListener('click', ()=>actions.editCooldown(btn.getAttribute('data-cool-edit')));
    });
  },

  render(snap, actions) {
    if (!snap) return;
    this._updateCounts(snap);
    this._updateBadge(snap);
    const tbody = document.getElementById('poolTableBody');
    if (!tbody) return;
    tbody.innerHTML='';
    (snap.pages||[]).forEach(p=>{
      const tr = document.createElement('tr');
      tr.innerHTML = this._rowHtml(p);
      tbody.appendChild(tr);
    });
    this._bindRowActions(tbody, actions);
  },
};
