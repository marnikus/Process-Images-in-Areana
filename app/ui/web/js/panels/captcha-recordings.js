/* Captcha recording summaries + user-owned ground-truth labels. */
'use strict';

const CaptchaRecordingsPanel = {
  init() {
    document.getElementById('captchaRecordsRefreshBtn')?.addEventListener('click', () => this.load());
    document.getElementById('captchaRecordsDeleteAllBtn')?.addEventListener('click', () => this.removeAll());
    document.getElementById('captchaRecordsUndoBtn')?.addEventListener('click', () => this.undoDelete());
    setTimeout(() => this.load(), 1600);
  },

  load() {
    const bridge = window.CaptchaRecordingsBridge;
    if (bridge?.list_all_sessions) bridge.list_all_sessions((raw) => this.receive(raw));
    else if (bridge?.list_sessions) bridge.list_sessions(1000, (raw) => this.receive(raw));
  },

  receive(raw) {
    try {
      const result = JSON.parse(raw);
      if (result.ok) this.render(result.sessions || []);
      else LogConsole.log('Captcha records failed: ' + result.error, 'error');
    } catch (error) { LogConsole.log('Captcha records parse failed: ' + error, 'warn'); }
  },

  render(rows) {
    const body = document.getElementById('captchaRecordsBody');
    if (!body) return;
    body.replaceChildren(...rows.map((row) => this.row(row)));
    const summary = document.getElementById('captchaRecordsSummary');
    if (summary) summary.textContent = `All ${rows.length} retained session${rows.length === 1 ? '' : 's'}`;
    const empty = document.getElementById('captchaRecordsEmpty');
    if (empty) empty.style.display = rows.length ? 'none' : 'block';
  },

  row(item) {
    const tr = document.createElement('tr');
    this.cell(tr, this.when(item.started_at));
    this.cell(tr, this.route(item.url));
    this.cell(tr, item.method || '—');
    this.cell(tr, item.outcome || item.status || '—');
    this.cell(tr, this.verdict(item));
    this.cell(tr, this.duration(item.elapsed_ms));
    this.cell(tr, `${item.mutation_count || 0}/${item.network_count || 0}/${item.snapshot_count || 0}`);
    this.cell(tr, String(item.milestone_count || 0));
    const labelCell = document.createElement('td');
    const actor = this.actorSelect(item);
    const result = this.resultSelect(item);
    const save = () => this.setLabels(item.session_id, actor, result);
    actor.addEventListener('change', save); result.addEventListener('change', save);
    labelCell.append(actor, result, CaptchaRecordingComparison.button(item, 0),
      CaptchaRecordingComparison.button(item, 1), this.openButton(item), this.deleteButton(item));
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

  deleteButton(item) {
    const button = document.createElement('button');
    button.className = 'captcha-delete-btn';
    button.textContent = 'Delete';
    button.title = 'Remove this recording (Undo delete restores it)';
    button.addEventListener('click', () => this.remove(item));
    return button;
  },

  remove(item) {
    this.deleteRequest('delete_session', item.session_id);
  },

  removeAll() {
    Dialog.confirm('Delete all recordings?',
      'Remove every retained recording? Active recordings are kept. Undo delete restores this group.',
      'Delete all', () => this.deleteRequest('delete_all_sessions'));
  },

  undoDelete() {
    const bridge = window.CaptchaRecordingsBridge;
    if (!bridge?.undo_delete) return;
    bridge.undo_delete((raw) => {
      try {
        const reply = JSON.parse(raw);
        if (!reply.ok) throw new Error(reply.error);
        CaptchaRecordingComparison.reset();
        this.load();
      } catch (error) { LogConsole.log('Undo recording delete failed: ' + error, 'error'); }
    });
  },

  deleteRequest(slot, sessionId) {
    const bridge = window.CaptchaRecordingsBridge;
    const done = (raw) => {
      try {
        const reply = JSON.parse(raw);
        if (!reply.ok) throw new Error(reply.error);
        CaptchaRecordingComparison.reset();
        this.load();
      } catch (error) { LogConsole.log('Delete recording failed: ' + error, 'error'); }
    };
    if (sessionId) bridge?.[slot]?.(sessionId, done);
    else bridge?.[slot]?.(done);
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

  verdict(item) {
    const acceptance = item.acceptance || 'none';
    if (item.verified === true) return 'verified ✓';
    if (item.verified === false) return 'refuted ✗';
    return acceptance === 'accepted_candidate' ? 'candidate …' : acceptance;
  },
  verdictText(manifest) {
    const acceptance = manifest.acceptance || 'none';
    if (manifest.verified === true) return `Acceptance: ${acceptance} → job completed (verified)`;
    if (manifest.verified === false) return `Acceptance: ${acceptance} → job ${manifest.job || 'failed'} (candidate refuted)`;
    return `Acceptance: ${acceptance} — image job has not confirmed this session yet`;
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
