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
    const actor = this.actorSelect(item);
    const result = this.resultSelect(item);
    const save = () => this.setLabels(item.session_id, actor, result);
    actor.addEventListener('change', save); result.addEventListener('change', save);
    labelCell.append(actor, result, CaptchaRecordingComparison.button(item, 0),
      CaptchaRecordingComparison.button(item, 1), this.openButton(item));
    tr.appendChild(labelCell);
    tr.title = item.reason || item.session_id || '';
    return tr;
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

  actorSelect(item) {
    return this.select([['unknown', 'Actor?'], ['bot', 'Bot'], ['manual', 'Manual'],
      ['mixed', 'Bot→Manual']], item.actor_label);
  },

  resultSelect(item) {
    return this.select([['unknown', 'Result?'], ['passed', 'Passed'], ['failed', 'Failed']],
      item.result_label);
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
