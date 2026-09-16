/* url-list.js — URL List panel with Job Cycle & Cooldown Logic */
'use strict';

const UrlList = {
  _lastConnectUrl: '',
  _lastConnectTs: 0,
  _countdownInterval: null,
  _cooldownCache: {},

  init() {
    const addBtn = document.getElementById('urlAddBtn');
    const input = document.getElementById('urlInput');
    const tableBody = document.getElementById('urlTableBody');
    if (!addBtn || !input || !tableBody) return;

    addBtn.addEventListener('click', () => this.addUrl());
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.addUrl(); });

    tableBody.addEventListener('click', (e) => {
      const chk = e.target.closest('input[type=checkbox]');
      if (chk) {
        const urlId = chk.dataset.urlId;
        const action = chk.dataset.action;
        if (action === 'toggle' && urlId) this.toggleUrl(urlId);
        return;
      }
      const btn = e.target.closest('button');
      if (!btn) return;
      const urlId = btn.dataset.urlId;
      const action = btn.dataset.action;
      if (!urlId || !action) return;
      if (action === 'test') this.testUrl(urlId);
      if (action === 'toggle') this.toggleUrl(urlId);
      if (action === 'remove') this.removeUrl(urlId);
      if (action === 'edit') this.editUrl(urlId);
      if (action === 'connect') this.connectUrl(urlId);
      if (action === 'reset_cooldown') this.resetCooldown(urlId);
      if (action === 'edit_cooldown') this.editCooldown(urlId);
      if (action === 'edit_penalty') this.editPenalty(urlId);
    });

    // global cooldown controls
    this.initGlobalControls();
    this.startCountdownTicker();
  },

  initGlobalControls() {
    const minCdInput = document.getElementById('globalMinCooldown');
    const penInput = document.getElementById('globalCaptchaPenalty');
    const resetCheck = document.getElementById('postGenResetCheck');
    const applyBtn = document.getElementById('globalCooldownApplyBtn');
    const resetAllBtn = document.getElementById('resetAllCooldownsBtn');

    if (applyBtn) {
      applyBtn.addEventListener('click', () => {
        const minCd = minCdInput ? parseInt(minCdInput.value, 10) : 300;
        const pen = penInput ? parseInt(penInput.value, 10) : 900;
        const reset = resetCheck ? resetCheck.checked : true;
        const applyAll = document.getElementById('applyToAllCheck')?.checked || false;
        this.setGlobalCooldown(minCd, pen, reset, applyAll);
      });
    }
    if (resetAllBtn) {
      resetAllBtn.addEventListener('click', () => this.resetAllCooldowns());
    }

    // load current global config
    if (typeof App !== 'undefined' && App.bridge && App.bridge.get_global_cooldown) {
      try {
        App.bridge.get_global_cooldown((res) => {
          try {
            const r = JSON.parse(res);
            if (r.ok && r.cooldown) {
              if (minCdInput) minCdInput.value = r.cooldown.min_cooldown_seconds || 300;
              if (penInput) penInput.value = r.cooldown.captcha_penalty_seconds || 900;
              if (resetCheck) resetCheck.checked = r.cooldown.post_generation_reset !== false;
            }
          } catch {}
        });
      } catch {}
    }
  },

  startCountdownTicker() {
    if (this._countdownInterval) clearInterval(this._countdownInterval);
    this._countdownInterval = setInterval(() => this.updateCountdowns(), 1000);
  },

  updateCountdowns() {
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    const now = Date.now();
    const rows = tbody.querySelectorAll('tr[data-url-id]');
    rows.forEach(tr => {
      const urlId = tr.dataset.urlId;
      const u = (App.state && App.state.urls) ? App.state.urls.find(x => x.id === urlId) : null;
      if (!u) return;
      const cdEl = tr.querySelector('.url-cooldown-timer');
      if (!cdEl) return;
      let remaining = 0;
      let until = u.cooldown_until || null;
      if (until) {
        try {
          const untilEpoch = new Date(until).getTime();
          remaining = Math.max(0, Math.floor((untilEpoch - now) / 1000));
        } catch {}
      }
      if (u.in_cooldown || remaining > 0) {
        cdEl.textContent = this.formatRemaining(remaining);
        cdEl.style.color = remaining > 0 ? '#ff9500' : 'var(--text-muted)';
        cdEl.title = `Cooldown until ${until || ''} — ${remaining}s remaining, captcha x${u.captcha_count || 0}`;
        tr.classList.add('in-cooldown');
      } else {
        cdEl.textContent = 'ready';
        cdEl.style.color = '#4ade80';
        cdEl.title = 'Ready to receive new job';
        tr.classList.remove('in-cooldown');
      }
    });
  },

  formatRemaining(sec) {
    sec = Math.max(0, parseInt(sec, 10) || 0);
    if (sec <= 0) return 'ready';
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m < 60) {
      return s === 0 ? `${m}m` : `${m}m ${s}s`;
    }
    const h = Math.floor(m / 60);
    const mm = m % 60;
    return mm === 0 ? `${h}h` : `${h}h ${mm}m`;
  },

  restore(state) {
    if (!state || !state.urls) return;
    this.render(state.urls);
  },

  render(urls) {
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    urls.forEach(u => {
      const tr = document.createElement('tr');
      tr.dataset.urlId = u.id;
      tr.dataset.url = u.url;
      const cooldownSec = u.cooldown_seconds || 300;
      const penaltySec = u.captcha_penalty_seconds || 900;
      const capCount = u.captcha_count || 0;
      const remainingStr = u.cooldown_remaining_str || (u.in_cooldown ? `${u.cooldown_remaining || 0}s` : 'ready');
      const inCd = u.in_cooldown ? true : false;
      tr.innerHTML = `
        <td><input type="checkbox" ${u.enabled !== false ? 'checked' : ''} data-action="toggle" data-url-id="${u.id}"></td>
        <td style="max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${this.esc(u.url)}">${this.esc(u.url)}</td>
        <td><span class="url-status url-status-${u.status || 'pending'}">${this.esc(u.status || 'pending')}</span></td>
        <td class="url-conn-status" style="font-size:11px;"><span style="color:var(--text-muted);">○ checking…</span></td>
        <td style="font-size:10px;">
          <span class="url-cooldown-timer" style="font-weight:600; color:${inCd ? '#ff9500' : '#4ade80'};" title="Cooldown until ${this.esc(u.cooldown_until || '')}">${this.esc(remainingStr)}</span>
          <div style="font-size:9px; color:var(--text-muted);">CD:${cooldownSec}s Pen:${penaltySec}s ${capCount ? `⚠x${capCount}` : ''}</div>
        </td>
        <td style="font-size:10px; color:var(--text-muted)">${this.esc(u.last_error || '')}</td>
        <td style="display:flex; flex-wrap:wrap; gap:2px;">
          <button class="btn-small" data-action="connect" data-url-id="${u.id}" title="Find Chrome tab matching this URL and connect">Connect</button>
          <button class="btn-small" data-action="test" data-url-id="${u.id}">Test</button>
          <button class="btn-small" data-action="edit_cooldown" data-url-id="${u.id}" title="Edit minimum cooldown between jobs (e.g. 5 min)">CD:${cooldownSec}s</button>
          <button class="btn-small" data-action="edit_penalty" data-url-id="${u.id}" title="Edit captcha penalty duration (e.g. +15 min per captcha)">Pen:${penaltySec}s</button>
          <button class="btn-small" data-action="reset_cooldown" data-url-id="${u.id}" title="Reset cooldown timer now">Reset CD</button>
          <button class="btn-small" data-action="edit" data-url-id="${u.id}">Edit</button>
          <button class="btn-small" data-action="remove" data-url-id="${u.id}">✕</button>
        </td>
      `;
      if (inCd) tr.classList.add('in-cooldown');
      tbody.appendChild(tr);
    });
    const countEl = document.getElementById('urlCount');
    if (countEl) countEl.textContent = `${urls.length} URLs`;
    if (typeof CDPPanel !== 'undefined' && CDPPanel.updateUrlRowsConnection) {
      setTimeout(()=>CDPPanel.updateUrlRowsConnection(), 50);
    }
    // cache
    this._cooldownCache = {};
    urls.forEach(u => { this._cooldownCache[u.id] = u.cooldown_until; });
  },

  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');
  },

  _snapshotUrls() {
    return (App.state && App.state.urls) ? App.state.urls : [];
  },

  addUrl() {
    const input = document.getElementById('urlInput');
    const val = input.value.trim();
    if (!val) return;
    if (App.bridge && App.bridge.add_url) {
      App.bridge.add_url(val, (res) => {
        try {
          const r = JSON.parse(res);
          if (!r.ok) LogConsole.log('Add URL failed: ' + r.error, 'error');
          else {
            input.value = '';
            LogConsole.log('URL added: ' + val, 'success');
            if (typeof ArenaHistory !== 'undefined') {
              setTimeout(()=>ArenaHistory.recordGlobal('urls', App.state.urls), 100);
            }
          }
        } catch (e) { console.error(e); }
      });
    }
  },

  removeUrl(id) {
    if (App.bridge && App.bridge.remove_url) {
      App.bridge.remove_url(id, () => LogConsole.log('URL removed', 'info'));
    }
  },

  toggleUrl(id) {
    if (App.bridge && App.bridge.toggle_url) {
      App.bridge.toggle_url(id, () => {});
    }
  },

  testUrl(id) {
    if (App.bridge && App.bridge.test_url) {
      LogConsole.log('Testing URL ' + id + '...', 'info');
      App.bridge.test_url(id, (res) => {
        try {
          const r = JSON.parse(res);
          LogConsole.log('Test result: ' + (r.ok ? 'OK' : r.error), r.ok ? 'success' : 'error');
        } catch (e) {}
      });
    }
  },

  editUrl(id) {
    const newUrl = prompt('Edit URL:');
    if (!newUrl) return;
    if (App.bridge && App.bridge.edit_url) {
      App.bridge.edit_url(id, newUrl, (res) => {
        try {
          const r = JSON.parse(res);
          if (!r.ok) LogConsole.log('Edit failed: ' + r.error, 'error');
        } catch (e) {}
      });
    }
  },

  editCooldown(id) {
    const urlObj = (App.state && App.state.urls) ? App.state.urls.find(u => u.id === id) : null;
    const cur = urlObj ? (urlObj.cooldown_seconds || 300) : 300;
    const input = prompt(`Set minimum cooldown between jobs for this URL (seconds). Current ${cur}s, e.g. 300 = 5 min:`, String(cur));
    if (!input) return;
    const sec = parseInt(input, 10);
    if (isNaN(sec) || sec < 0) { LogConsole.log('Invalid cooldown seconds', 'error'); return; }
    if (App.bridge && App.bridge.set_url_cooldown) {
      App.bridge.set_url_cooldown(id, sec, (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) LogConsole.log(`Cooldown set to ${sec}s for ${id}`, 'success');
          else LogConsole.log('Set cooldown failed: ' + r.error, 'error');
        } catch {}
      });
    }
  },

  editPenalty(id) {
    const urlObj = (App.state && App.state.urls) ? App.state.urls.find(u => u.id === id) : null;
    const cur = urlObj ? (urlObj.captcha_penalty_seconds || 900) : 900;
    const input = prompt(`Set extra penalty duration per captcha event for this URL (seconds). Current ${cur}s, e.g. 900 = 15 min. Repeated captchas stack:`, String(cur));
    if (!input) return;
    const sec = parseInt(input, 10);
    if (isNaN(sec) || sec < 0) { LogConsole.log('Invalid penalty seconds', 'error'); return; }
    if (App.bridge && App.bridge.set_url_captcha_penalty) {
      App.bridge.set_url_captcha_penalty(id, sec, (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) LogConsole.log(`Captcha penalty set to ${sec}s for ${id}`, 'success');
          else LogConsole.log('Set penalty failed: ' + r.error, 'error');
        } catch {}
      });
    }
  },

  resetCooldown(id) {
    if (App.bridge && App.bridge.reset_url_cooldown) {
      App.bridge.reset_url_cooldown(id, (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) LogConsole.log(`Cooldown reset for ${id}`, 'success');
          else LogConsole.log('Reset failed: ' + r.error, 'error');
        } catch {}
      });
    }
  },

  setGlobalCooldown(minCd, pen, postReset, applyAll) {
    if (App.bridge && App.bridge.set_global_cooldown) {
      const payload = JSON.stringify({
        min_cooldown_seconds: minCd,
        captcha_penalty_seconds: pen,
        post_generation_reset: postReset,
        apply_to_all: !!applyAll
      });
      App.bridge.set_global_cooldown(payload, (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) LogConsole.log(`Global cooldown set: min ${minCd}s, penalty ${pen}s, reset ${postReset}, applyAll ${applyAll}`, 'success');
          else LogConsole.log('Global cooldown failed: ' + r.error, 'error');
        } catch {}
      });
    }
  },

  resetAllCooldowns() {
    if (App.bridge && App.bridge.reset_all_cooldowns) {
      if (!confirm('Reset all cooldown timers now?')) return;
      App.bridge.reset_all_cooldowns('', (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) LogConsole.log('All cooldowns reset', 'success');
          else LogConsole.log('Reset all failed: ' + r.error, 'error');
        } catch {}
      });
    }
  },

  _extractUrl(q) {
    if (!q) return '';
    q = q.trim();
    let m = q.match(/\(https?:\/\/[^\s\)]+\)/);
    if (m) {
      let inside = m[0].slice(1,-1).trim();
      if (inside.startsWith('http')) return inside;
    }
    q = q.replace(/^\+/, '').replace(/\]+$/, '').replace(/^\(+/, '').replace(/\)+$/, '').trim();
    let http = q.match(/(https?:\/\/[^\s\]\)]+)/);
    if (http) return http[1].trim();
    return q;
  },

  connectUrl(id) {
    const urlObj = (App.state && App.state.urls) ? App.state.urls.find(u => u.id === id) : null;
    let url = urlObj ? urlObj.url : '';
    if (!url) { LogConsole.log('⚠ URL not found', 'warn'); return; }
    url = this._extractUrl(url);
    const now = Date.now();
    if (url === this._lastConnectUrl && (now - this._lastConnectTs) < 1500) {
      console.debug('UrlList.connectUrl debounced duplicate', url.slice(0,60));
      return;
    }
    this._lastConnectUrl = url;
    this._lastConnectTs = now;
    LogConsole.log(`🔍 Connect: finding tab for ${url}`, 'info');
    if (App.bridge && App.bridge.find_tab_by_url) {
      App.bridge.find_tab_by_url(url);
    }
    const inp = document.getElementById('urlBookmarkInput');
    if (inp) inp.value = url;
  }
};
