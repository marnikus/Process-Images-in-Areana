/* Captcha recording summaries + user-owned ground-truth labels. */
'use strict';

const ACTOR_OPTIONS = [['unknown', 'Actor?'], ['bot', 'Bot'], ['manual', 'Manual'], ['mixed', 'Bot→Manual']];
const RESULT_OPTIONS = [['unknown', 'Result?'], ['passed', 'Passed'], ['failed', 'Failed']];

const CaptchaRecordingsPanel = {
  init() {
    document.getElementById('captchaRecordsRefreshBtn')?.addEventListener('click', () => this.load());
    this.initToggle();
    setTimeout(() => this.load(), 1600);
  },

  initToggle() {
    const box = document.getElementById('captchaRecordToggle');
    const bridge = window.CaptchaRecordingsBridge;
    if (!box || !bridge?.recording_enabled) return;
    bridge.recording_enabled((raw) => {
      try { box.checked = JSON.parse(raw).enabled === true; }
      catch (error) { LogConsole.log('Captcha record toggle state failed: ' + error, 'warn'); }
    });
    box.addEventListener('change', () => {
      if (!bridge.set_recording_enabled) return;
      bridge.set_recording_enabled(box.checked, (reply) => {
        try {
          const result = JSON.parse(reply);
          if (result.ok) LogConsole.log(`🎞 Session recording ${result.enabled ? 'enabled' : 'disabled'}`, 'info');
          else LogConsole.log('Captcha record toggle failed: ' + result.error, 'error');
        } catch (error) { LogConsole.log('Captcha record toggle reply failed: ' + error, 'error'); }
      });
    });
  },

  load() {
    const bridge = window.CaptchaRecordingsBridge;
    if (!bridge?.list_sessions) return;
    bridge.list_sessions(1000, (raw) => {
      try {
        const result = JSON.parse(raw);
        if (result.ok) this.render(result.sessions || [], result.total);
      } catch (error) { LogConsole.log('Captcha records parse failed: ' + error, 'warn'); }
    });
  },

  render(rows, total) {
    const body = document.getElementById('captchaRecordsBody');
    if (!body) return;
    body.replaceChildren(...rows.map((row) => this.row(row)));
    const summary = document.getElementById('captchaRecordsSummary');
    if (summary) {
      summary.textContent = (total > rows.length)
        ? `showing last ${rows.length} of ${total} local sessions`
        : `${rows.length} local session${rows.length === 1 ? '' : 's'}`;
    }
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
    // D3: actor (who solved) and result (what happened) are independent columns
    this.labelCells(tr, item);
    const labelCell = document.createElement('td');
    labelCell.append(CaptchaRecordingComparison.button(item, 0),
      CaptchaRecordingComparison.button(item, 1), this.openButton(item), this.deleteButton(item));
    tr.appendChild(labelCell);
    tr.title = item.reason || item.session_id || '';
    return tr;
  },

  deleteButton(item) {
    const button = document.createElement('button');
    button.className = 'captcha-compare-btn';
    button.textContent = '🗑';
    button.title = 'Delete this recording — cannot be undone';
    button.addEventListener('click', () => {
      if (!confirm(`Delete recording ${item.session_id}? This cannot be undone.`)) return;
      const bridge = window.CaptchaRecordingsBridge;
      if (!bridge?.delete_session) return;
      bridge.delete_session(item.session_id, (raw) => {
        try {
          const result = JSON.parse(raw);
          if (result.ok) { LogConsole.log(`🗑 Recording ${item.session_id} deleted`, 'warn'); this.load(); }
          else LogConsole.log('Delete recording failed: ' + result.error, 'error');
        } catch (error) { LogConsole.log('Delete recording reply failed: ' + error, 'error'); }
      });
    });
    return button;
  },

  openButton(item) {
    const button = document.createElement('button');
    button.className = 'captcha-compare-btn';
    button.textContent = 'Open';
    button.title = 'Open this recording folder';
    button.addEventListener('click', () => {
      const bridge = window.CaptchaRecordingsBridge;
      if (!bridge?.open_folder) return;
      bridge.open_folder(item.session_id, (raw) => {
        try {
          const result = JSON.parse(raw);
          if (!result.ok) LogConsole.log('Open recording folder failed: ' + result.error, 'error');
        } catch (error) { LogConsole.log('Open recording folder reply failed: ' + error, 'error'); }
      });
    });
    return button;
  },

  // Both axes are edited together: changing either select persists actor+result
  // as one pair (the bridge slot takes them as a pair), so a half-written
  // manifest is impossible.
  labelCells(tr, item) {
    const actor = this.select(ACTOR_OPTIONS, item.actor_label);
    const result = this.select(RESULT_OPTIONS, item.result_label);
    const changed = () => this.setLabels(item.session_id, actor, result);
    actor.addEventListener('change', changed);
    result.addEventListener('change', changed);
    this.selectCell(tr, actor);
    this.selectCell(tr, result);
  },

  select(options, selected) {
    const select = document.createElement('select');
    select.className = 'captcha-record-label';
    options.forEach(([value, text]) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = text; select.appendChild(option);
    });
    select.value = selected || 'unknown';
    return select;
  },

  setLabels(sessionId, actor, result) {
    const bridge = window.CaptchaRecordingsBridge;
    if (!bridge?.set_labels) return;
    actor.disabled = true; result.disabled = true;
    bridge.set_labels(sessionId, actor.value, result.value, (raw) => {
      actor.disabled = false; result.disabled = false;
      try {
        const reply = JSON.parse(raw);
        if (!reply.ok) LogConsole.log('Captcha labels failed: ' + reply.error, 'error');
      } catch (error) { LogConsole.log('Captcha label reply failed: ' + error, 'error'); }
    });
  },

  cell(row, text) {
    const td = document.createElement('td');
    td.textContent = String(text == null ? '' : text); row.appendChild(td);
  },
  selectCell(row, select) {
    const td = document.createElement('td');
    td.appendChild(select); row.appendChild(td);
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
