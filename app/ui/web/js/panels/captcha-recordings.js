/* Captcha recording summaries + user-owned ground-truth labels. */
'use strict';

const CaptchaRecordingsPanel = {
  init() {
    document.getElementById('captchaRecordsRefreshBtn')?.addEventListener('click', () => this.load());
    setTimeout(() => this.load(), 1600);
  },

  load() {
    const bridge = window.CaptchaRecordingsBridge;
    if (!bridge?.list_sessions) return;
    bridge.list_sessions(200, (raw) => {
      try {
        const result = JSON.parse(raw);
        if (result.ok) this.render(result.sessions || []);
      } catch (error) { LogConsole.log('Captcha records parse failed: ' + error, 'warn'); }
    });
  },

  render(rows) {
    const body = document.getElementById('captchaRecordsBody');
    if (!body) return;
    body.replaceChildren(...rows.map((row) => this.row(row)));
    const summary = document.getElementById('captchaRecordsSummary');
    if (summary) summary.textContent = `${rows.length} local session${rows.length === 1 ? '' : 's'}`;
    const empty = document.getElementById('captchaRecordsEmpty');
    if (empty) empty.style.display = rows.length ? 'none' : 'block';
  },

  row(item) {
    const tr = document.createElement('tr');
    this.cell(tr, this.when(item.started_at));
    this.cell(tr, this.route(item.url));
    this.cell(tr, item.method || '—');
    this.cell(tr, item.outcome || item.status || '—');
    this.cell(tr, this.duration(item.elapsed_ms));
    this.cell(tr, `${item.mutation_count || 0}/${item.network_count || 0}/${item.snapshot_count || 0}`);
    const labelCell = document.createElement('td');
    labelCell.append(this.labelSelect(item), CaptchaRecordingComparison.button(item, 0),
      CaptchaRecordingComparison.button(item, 1));
    tr.appendChild(labelCell);
    tr.title = item.reason || item.session_id || '';
    return tr;
  },

  labelSelect(item) {
    const select = document.createElement('select');
    select.className = 'captcha-record-label';
    [['unknown', 'Unknown'], ['bot', 'Bot passed'], ['manual', 'User passed']].forEach(([value, text]) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = text; select.appendChild(option);
    });
    select.value = item.actor_label || 'unknown';
    select.addEventListener('change', () => this.setLabel(item.session_id, select));
    return select;
  },

  setLabel(sessionId, select) {
    const bridge = window.CaptchaRecordingsBridge;
    if (!bridge?.set_label) return;
    select.disabled = true;
    bridge.set_label(sessionId, select.value, (raw) => {
      select.disabled = false;
      try {
        const result = JSON.parse(raw);
        if (!result.ok) LogConsole.log('Captcha label failed: ' + result.error, 'error');
      } catch (error) { LogConsole.log('Captcha label reply failed: ' + error, 'error'); }
    });
  },

  cell(row, text) {
    const td = document.createElement('td');
    td.textContent = String(text == null ? '' : text); row.appendChild(td);
  },
  when(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  },
  route(value) {
    try { const url = new URL(value); return url.host + url.pathname; }
    catch (_) { return value || '—'; }
  },
  duration(value) {
    const seconds = Number(value || 0) / 1000;
    return seconds < 60 ? `${seconds.toFixed(1)}s` : `${(seconds / 60).toFixed(1)}m`;
  },
};
