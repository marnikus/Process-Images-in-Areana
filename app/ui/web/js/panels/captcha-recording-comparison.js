/* Two-session evidence viewer plus deterministic first-divergence report. */
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
    if (report) report.textContent = 'Select both A and B to calculate common evidence and the first divergence.';
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

  timeline(events) {
    const node = document.createElement('pre');
    node.className = 'captcha-event-timeline';
    node.textContent = events.map((event) =>
      `${event.offset_ms || 0}ms  ${event.kind || '?'}  ${this.eventText(event.payload)}`).join('\n') || 'No events';
    return node;
  },

  checkpoints(snapshots) {
    const wrap = document.createElement('div');
    const select = document.createElement('select');
    const body = document.createElement('pre');
    snapshots.forEach((snapshot, index) => {
      const option = document.createElement('option');
      option.value = index; option.textContent = `${snapshot.offset_ms || 0}ms · ${snapshot.reason || snapshot.name}`;
      select.appendChild(option);
    });
    const show = () => { body.textContent = snapshots[Number(select.value)]?.html || 'No DOM checkpoint'; };
    select.addEventListener('change', show); select.value = Math.max(0, snapshots.length - 1); show();
    wrap.append(select, body); return wrap;
  },

  compare() {
    if (!this.ids[0] || !this.ids[1]) return;
    const bridge = window.CaptchaRecordingsBridge;
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
    const first = report.first_divergence || {};
    const lines = [
      `Evidence complete: ${report.evidence_complete ? 'YES' : 'NO'}`,
      ...((report.warnings || []).map((value) => `WARNING: ${value}`)),
      `First divergence: ${first.operation || 'none'}`,
      `A: ${(first.left || []).join(' ; ') || '—'}`,
      `B: ${(first.right || []).join(' ; ') || '—'}`,
      `Common (${(report.common || []).length}): ${(report.common || []).join(' ; ') || '—'}`,
      `A only: ${(report.left_only || []).join(' ; ') || '—'}`,
      `B only: ${(report.right_only || []).join(' ; ') || '—'}`,
      'DOM diff:', ...((report.dom_diff || []).slice(0, 200)),
    ];
    pane.textContent = lines.join('\n');
    pane.classList.toggle('evidence-incomplete', !report.evidence_complete);
  },

  eventText(payload) {
    const text = JSON.stringify(payload || {});
    return text.length > 500 ? text.slice(0, 500) + '…' : text;
  },
};
