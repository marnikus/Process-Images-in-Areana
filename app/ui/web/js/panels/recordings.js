/* Recordings panel — captcha session recordings (window #15).
   Design: docs/archive/2026-09-18-captcha-session-recording/design.md
   List sessions, labels (bot pass vs manual pass), delete, and the
   side-by-side snapshot diff used to compare a human vs bot session. */

const RecordingsPanel = (() => {
  const $ = (id) => document.getElementById(id);
  const sessions = [];       // last fetched list (label selects read from it)
  const selected = { id: null };
  const diffPick = { a: null, b: null };

  function call(slot, arg, cb) {
    if (!(App.bridge && App.bridge[slot])) { $('recDetail').textContent = 'bridge unavailable'; return; }
    try {
      if (arg === undefined) App.bridge[slot]((res) => cb(safeParse(res)));
      else App.bridge[slot](arg, (res) => cb(safeParse(res)));
    } catch (e) { showDetail(`bridge error: ${e.message}`); }
  }

  function safeParse(res) {
    try { return JSON.parse(res); } catch (e) { return { ok: false, error: String(res).slice(0, 200) }; }
  }

  function showDetail(text) { $('recDetail').textContent = text; }

  function fmtTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    return isNaN(d.getTime()) ? String(ts) : d.toLocaleString();
  }

  function labelBadge(label) {
    if (label === 'bot_pass') return ' 🤖bot';
    if (label === 'manual_pass') return ' 👤manual';
    return '';
  }

  function renderList(payload) {
    sessions.length = 0;
    (payload.sessions || []).forEach((s) => sessions.push(s));
    const box = $('recList');
    if (!sessions.length) { box.innerHTML = '<div style="padding:8px;color:var(--text-muted);font-size:11px;">no recordings yet — one starts automatically when a captcha is detected</div>'; fillDiffSelects(); return; }
    box.innerHTML = '';
    sessions.forEach((s) => box.appendChild(rowFor(s)));
    fillDiffSelects();
    $('recEnabled').checked = payload.enabled !== false;
  }

  function rowFor(s) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;align-items:center;padding:3px 4px;border-radius:4px;cursor:pointer;font-size:11px;';
    const c = s.counters || {};
    row.innerHTML = `<span style="color:var(--text-muted)">${fmtTime(s.started_at)}</span>`
      + `<span>${s.outcome || 'active'}</span>`
      + `<span style="color:var(--text-muted)">ev ${c.events || 0} · snap ${c.snapshots || 0}</span>`
      + `<span style="font-weight:600;">${labelBadge(s.label)}</span>`;
    row.title = `${s.id} — ${s.url || ''}`;
    if (selected.id === s.id) row.style.background = 'rgba(96,165,250,0.18)';
    row.onclick = () => { selected.id = s.id; refresh(); };
    return row;
  }

  function fillDiffSelects() {
    const labelFor = (s) => {
      const c = s.counters || {};
      return `${fmtTime(s.started_at)} ${s.outcome}${labelBadge(s.label)} (${c.snapshots || 0} snaps)`;
    };
    [['recDiffA', 'a'], ['recDiffB', 'b']].forEach(([elId, key]) => {
      const sel = $(elId);
      const prev = diffPick[key];
      sel.innerHTML = '<option value="">— pick session —</option>';
      sessions.forEach((s) => {
        const opt = document.createElement('option');
        opt.value = s.id; opt.textContent = labelFor(s);
        if (prev === s.id) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.onchange = () => { diffPick[key] = sel.value || null; };
    });
  }

  function renderDetail(payload) {
    if (!payload.ok) { showDetail(`error: ${payload.error || 'unknown'}`); return; }
    const s = payload.session || {};
    const lines = [`session ${s.id}`, `url: ${s.url}`, `outcome: ${s.outcome} · method: ${s.method || '—'} · label: ${s.label || '—'}`,
                   `started ${fmtTime(s.started_at)} → ended ${fmtTime(s.ended_at)}`, ''];
    const snaps = (payload.session && payload.session.snapshot_names) || [];
    if (snaps.length) lines.push(`snapshots: ${snaps.join(', ')}`, '');
    (payload.events || []).slice(-120).forEach((e) => lines.push(eventLine(e)));
    showDetail(lines.join('\n'));
  }

  function eventLine(e) {
    const t = fmtTime(e.ts);
    if (e.kind === 'state') return `${t} STATE  ${e.note || ''}`;
    if (e.kind === 'mutation') return `${t} MUT    ${e.mut} ${e.sel || e.attr || ''} +${e.added || 0} -${e.removed || 0}`;
    if (e.kind === 'network') return `${t} NET    ${e.method} ${e.status} ${e.url}`;
    if (e.kind === 'snapshot') return `${t} SNAP   ${e.name || ''}`;
    return `${t} ${e.kind}`;
  }

  function renderDiff(payload) {
    if (!payload.ok) { showDetail(`diff error: ${payload.error || 'unknown'}`); return; }
    const lines = payload.lines || [];
    const head = `identical: ${payload.identical} · diff lines: ${payload.total || 0}`
      + (payload.truncated ? ' (truncated)' : '') + '\n\n';
    showDetail(head + (lines.join('\n') || '(no differences)'));
  }

  function refresh() {
    call('get_recordings_list', undefined, (payload) => {
      renderList(payload);
      if (selected.id) call('get_recording_detail', JSON.stringify({ session_id: selected.id }), renderDetail);
    });
  }

  function snapshotNameFor(sessionId, index) {
    const s = sessions.find((x) => x.id === sessionId);
    const names = (s && s.snapshot_names) || [];
    return names[Math.min(index, Math.max(names.length - 1, 0))] || '';
  }

  function runDiff() {
    if (!diffPick.a || !diffPick.b) { showDetail('pick two sessions to compare (latest snapshot of each)'); return; }
    const req = { session_a: diffPick.a, name_a: snapshotNameFor(diffPick.a),
                  session_b: diffPick.b, name_b: snapshotNameFor(diffPick.b) };
    call('get_recording_diff', JSON.stringify(req), renderDiff);
  }

  function setLabel(label) {
    if (!selected.id) { showDetail('select a recording first'); return; }
    call('set_recording_label', JSON.stringify({ session_id: selected.id, label }), refresh);
  }

  function deleteSelected() {
    if (!selected.id) { showDetail('select a recording first'); return; }
    call('delete_recording', JSON.stringify({ session_id: selected.id }), () => { selected.id = null; refresh(); });
  }

  function saveEnabled() {
    call('set_recording_settings', JSON.stringify({ enabled: $('recEnabled').checked }), () => {});
  }

  function init() {
    const bind = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
    bind('recRefreshBtn', refresh);
    bind('recLabelBotBtn', () => setLabel('bot_pass'));
    bind('recLabelManualBtn', () => setLabel('manual_pass'));
    bind('recClearLabelBtn', () => setLabel(''));
    bind('recDeleteBtn', deleteSelected);
    bind('recDiffBtn', runDiff);
    const en = $('recEnabled'); if (en) en.onchange = saveEnabled;
    refresh();
  }

  return { init, refresh };
})();
