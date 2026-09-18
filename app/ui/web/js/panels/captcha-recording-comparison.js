/* Two-session evidence viewer: milestone alignment first, then divergence. */
'use strict';

const CaptchaRecordingComparison = {
  ids: [null, null],
  reset() {
    this.ids = [null, null];
    const a = document.getElementById('captchaCompareA');
    const b = document.getElementById('captchaCompareB');
    const report = document.getElementById('captchaComparisonReport');
    if (a) a.textContent = 'Select comparison A';
    if (b) b.textContent = 'Select comparison B';
    if (report) report.textContent = 'Select both A and B to align milestones and find the first divergence.';
  },
  button(item, slot) {
    const button = document.createElement('button');
    button.className = 'captcha-compare-btn';
    button.textContent = slot ? 'B' : 'A';
    button.title = `Load this session into comparison ${button.textContent}`;
    button.addEventListener('click', () => this.load(item.session_id, slot));
    return button;
  },

  load(sessionId, slot) {
    const bridge = window.CaptchaRecordingsBridge;
    if (!bridge?.get_session) return;
    bridge.get_session(sessionId, (raw) => {
      try {
        const result = JSON.parse(raw);
        if (!result.ok) throw new Error(result.error);
        this.ids[slot] = sessionId;
        this.render(slot, result.details);
        this.compare();
      } catch (error) { LogConsole.log('Captcha recording detail failed: ' + error, 'error'); }
    });
  },

  render(slot, details) {
    const pane = document.getElementById(`captchaCompare${slot ? 'B' : 'A'}`);
    if (!pane) return;
    const manifest = details.manifest || {};
    pane.replaceChildren(this.heading(manifest), this.meta(manifest),
      this.verdictLine(details), this.milestones(details.milestones || []),
      this.timeline(details.events || []),
      this.checkpoints(details.snapshots || [details.latest_snapshot].filter(Boolean)));
    pane.classList.toggle('evidence-incomplete', !details.evidence_complete);
  },

  heading(manifest) {
    const node = document.createElement('b');
    node.textContent = `${manifest.actor_label || 'unknown'} / ${manifest.result_label || 'unknown'} · ${manifest.method || '—'} / ${manifest.outcome || '—'}`;
    return node;
  },

  meta(manifest) {
    const node = document.createElement('div');
    node.textContent = `${CaptchaRecordingsPanel.when(manifest.started_at)} · ${CaptchaRecordingsPanel.route(manifest.url)} · ${manifest.session_id || ''}`;
    return node;
  },

  verdictLine(details) {
    const node = document.createElement('div');
    node.className = 'captcha-record-verdict';
    node.textContent = CaptchaRecordingsPanel.verdictText(details.manifest || {});
    (details.warnings || []).forEach((warning) => node.append(Object.assign(
      document.createElement('div'), {className: 'captcha-record-warning', textContent: '⚠ ' + warning})));
    return node;
  },

  milestones(rows) {
    const node = document.createElement('pre');
    node.className = 'captcha-milestone-timeline';
    node.textContent = rows.map((row) =>
      `${String(row.offset_ms || 0).padStart(7)}ms  ${row.phase}  ${this.bounded(row.data)}`).join('\n') || 'No named edges';
    return node;
  },

  timeline(events) {
    const node = document.createElement('pre');
    node.className = 'captcha-event-timeline';
    node.textContent = events.map((event) =>
      `${event.offset_ms || 0}ms  ${event.kind || '?'}  ${this.bounded(event.payload)}`).join('\n') || 'No events';
    return node;
  },

  checkpoints(snapshots) {
    const wrap = document.createElement('div');
    const select = document.createElement('select');
    const body = document.createElement('pre');
    snapshots.forEach((snapshot, index) => {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = `${snapshot.offset_ms || 0}ms · ${snapshot.reason || snapshot.name}`;
      select.appendChild(option);
    });
    const show = () => { body.textContent = snapshots[Number(select.value)]?.html || 'No DOM checkpoint'; };
    select.addEventListener('change', show);
    select.value = Math.max(0, snapshots.length - 1);
    show();
    wrap.append(select, body);
    return wrap;
  },

  compare() {
    if (!this.ids[0] || !this.ids[1]) return;
    const bridge = window.CaptchaRecordingsBridge;
    if (!bridge?.compare_sessions) return;
    bridge.compare_sessions(this.ids[0], this.ids[1], (raw) => {
      try {
        const result = JSON.parse(raw);
        if (!result.ok) throw new Error(result.error);
        this.renderReport(result.comparison);
      } catch (error) { LogConsole.log('Captcha comparison failed: ' + error, 'error'); }
    });
  },

  renderReport(report) {
    const pane = document.getElementById('captchaComparisonReport');
    if (!pane) return;
    pane.textContent = this.reportLines(report).join('\n');
    pane.classList.toggle('evidence-incomplete', !report.evidence_complete);
  },

  reportLines(report) {
    const verdict = report.verdict || {};
    const first = report.first_divergence || {};
    return [
      `Comparable: ${verdict.comparable ? 'YES' : 'NO'} — ${verdict.reason || ''}`,
      `Evidence complete: ${report.evidence_complete ? 'YES' : 'NO'}`,
      ...((report.warnings || []).map((value) => `WARNING: ${value}`)),
      '',
      'Milestone alignment (A=B means both sides reached the same named edge):',
      ...((report.alignment || []).map((row) => this.alignmentLine(row))),
      '',
      `First divergence: ${first.phase ? `${first.phase} (${first.status}) — ${first.why}` : 'none'}`,
      ...((report.timing_gaps || []).map((row) => `Timing gap: ${row.phase} ${row.delta_ms}ms`)),
      `Sequence divergence: ${(report.sequence_divergence || {}).operation || 'none'}`,
      '',
      `Network A: ${this.classes((report.network || {}).left)}`,
      `Network B: ${this.classes((report.network || {}).right)}`,
      `A-only classes: ${((report.network || {}).a_only || []).join(' ; ') || '—'}`,
      `B-only classes: ${((report.network || {}).b_only || []).join(' ; ') || '—'}`,
      '',
      'DOM diff (resolved checkpoints):',
      ...((report.dom_diff || []).slice(0, 200)),
    ];
  },

  alignmentLine(row) {
    const a = row.a_ms === null || row.a_ms === undefined ? '—' : `${row.a_ms}ms`;
    const b = row.b_ms === null || row.b_ms === undefined ? '—' : `${row.b_ms}ms`;
    const flag = row.status === 'both' ? '' : `  <${row.structural ? 'expected' : 'DIVERGENCE'}>`;
    return `${row.phase.padEnd(22)} A ${a.padStart(9)}  B ${b.padStart(9)}${flag}`;
  },

  classes(rows) {
    return (rows || []).map((row) => `${row.class}×${row.count}`).join(' ; ') || '—';
  },

  bounded(payload) {
    const text = JSON.stringify(payload || {});
    return text.length > 400 ? text.slice(0, 400) + '…' : text;
  },
};
