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
    const events = (details.events || []).map((event) =>
      `${event.at_ms || 0}ms  ${event.kind || '?'}  ${this.eventText(event.payload)}`).join('\n');
    const snapshot = details.latest_snapshot || {};
    pane.replaceChildren();
    const heading = document.createElement('b');
    heading.textContent = `${manifest.actor_label || 'unknown'} · ${manifest.method || '—'} · ${manifest.outcome || manifest.status || '—'}`;
    const meta = document.createElement('div');
    meta.textContent = `${CaptchaRecordingsPanel.when(manifest.started_at)} · ${CaptchaRecordingsPanel.route(manifest.url)} · ${manifest.session_id || ''}`;
    const timeline = document.createElement('pre');
    timeline.textContent = events || 'No events';
    const dom = document.createElement('pre');
    dom.textContent = snapshot.html || 'No DOM checkpoint';
    pane.append(heading, meta, timeline, dom);
  },

  eventText(payload) {
    if (payload == null) return '';
    const text = JSON.stringify(payload);
    return text.length > 500 ? text.slice(0, 500) + '…' : text;
  },
};