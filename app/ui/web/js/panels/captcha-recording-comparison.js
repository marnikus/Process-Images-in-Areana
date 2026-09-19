/* Bounded two-pane reader for already-redacted captcha evidence. */
'use strict';

const CaptchaRecordingComparison = {
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
        this.render(slot, result.details);
      } catch (error) { LogConsole.log('Captcha recording detail failed: ' + error, 'error'); }
    });
  },

  render(slot, details) {
    const pane = document.getElementById(`captchaCompare${slot ? 'B' : 'A'}`);
    if (!pane) return;
    const manifest = details.manifest || {};
    const line = (event) => `${event.offset_ms ?? 0}ms  ${event.kind || '?'}  ${this.eventText(event)}`;
    // D2: milestones always surface, even when the 200-event tail cut them off
    const milestones = (details.milestones || []).map(line).join('\n');
    const events = (details.events || []).filter((e) => e.kind !== 'milestone').map(line).join('\n');
    const timelineText = [milestones, events].filter(Boolean).join('\n');
    const snapshot = details.latest_snapshot || {};
    pane.replaceChildren();
    // D3: actor (who) and result (what) shown side by side, never conflated
    const heading = document.createElement('b');
    heading.textContent = `${manifest.actor_label || 'unknown'} · ${manifest.result_label || 'unknown'} · ${manifest.method || '—'} · ${manifest.outcome || manifest.status || '—'}`;
    const meta = document.createElement('div');
    meta.textContent = `${CaptchaRecordingsPanel.when(manifest.started_at)} · ${CaptchaRecordingsPanel.route(manifest.url)} · ${manifest.session_id || ''}`;
    const timeline = document.createElement('pre');
    timeline.textContent = timelineText || 'No events';
    const dom = document.createElement('pre');
    dom.textContent = snapshot.html || 'No DOM checkpoint';
    const stamp = document.createElement('div');
    stamp.textContent = snapshot.at ? `checkpoint: ${CaptchaRecordingsPanel.when(snapshot.at)}` : '';
    pane.append(heading, meta, timeline, dom, stamp);
  },

  eventText(event) {
    if (event == null) return '';
    const fields = Object.fromEntries(Object.entries(event)
      .filter(([key]) => !['seq', 'at', 'offset_ms', 'kind'].includes(key)));
    const text = JSON.stringify(fields);
    return text.length > 500 ? text.slice(0, 500) + '…' : text;
  },
};
