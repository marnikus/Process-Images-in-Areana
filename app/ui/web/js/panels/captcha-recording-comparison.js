/* Two-session evidence viewer plus deterministic first-divergence report. */
'use strict';

const CaptchaRecordingComparison = {
  ids: [null, null],
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

  _formatEvents(details) {
    const evts = details.events || [];
    return evts.map((event) =>
      `${event.offset_ms ?? 0}ms  ${event.kind || '?'}  ${this.eventText(event)}`).join('\n');
  },

  _makeHeading(manifest) {
    const heading = document.createElement('b');
    heading.textContent = `${manifest.actor_label || 'unknown'} · ${manifest.method || '—'} · ${manifest.outcome || manifest.status || '—'}`;
    return heading;
  },

  _makeMeta(manifest) {
    const meta = document.createElement('div');
    meta.textContent = `${CaptchaRecordingsPanel.when(manifest.started_at)} · ${CaptchaRecordingsPanel.route(manifest.url)} · ${manifest.session_id || ''}`;
    return meta;
  },

  _makeTimeline(eventsStr) {
    const timeline = document.createElement('pre');
    timeline.textContent = eventsStr || 'No events';
    return timeline;
  },

  _makeDom(snapshot) {
    const dom = document.createElement('pre');
    dom.textContent = snapshot.html || 'No DOM checkpoint';
    return dom;
  },

  render(slot, details) {
    const pane = document.getElementById(`captchaCompare${slot ? 'B' : 'A'}`);
    if (!pane) return;
    const manifest = details.manifest || {};
    const eventsStr = this._formatEvents(details);
    const snapshot = details.latest_snapshot || {};
    pane.replaceChildren();
    pane.append(
      this._makeHeading(manifest),
      this._makeMeta(manifest),
      this._makeTimeline(eventsStr),
      this._makeDom(snapshot),
      this._makeStamp(snapshot)
    );
  },

  _makeStamp(snapshot) {
    const stamp = document.createElement('div');
    stamp.textContent = snapshot.at ? `checkpoint: ${CaptchaRecordingsPanel.when(snapshot.at)}` : '';
    return stamp;
  },

  eventText(event) {
    if (event == null) return '';
    const fields = Object.fromEntries(Object.entries(event)
      .filter(([key]) => !['seq', 'at', 'offset_ms', 'kind'].includes(key)));
    const text = JSON.stringify(fields);
    return text.length > 500 ? text.slice(0, 500) + '…' : text;
  },
};
