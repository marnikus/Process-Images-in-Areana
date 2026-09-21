/* job-history.js — the Job History window (17th window).
   Pure observability: renders job_history_updated + the get_job_history reply,
   self-connects to both history signals (listeners.js stays frozen), own
   history-thumb flow on thumbnail_ready (the queue thumbs keep their own). */
'use strict';
const JobHistoryPanel = {
  _connected: false,

  init() {
    Boot.bindOnceById('historyRefreshBtn', 'click', () => this.refresh(), 'historyRefresh');
    Boot.bindOnceById('historyClearBtn', 'click', () => this.clear(), 'historyClear');
    Boot.bindOnceById('historyTableBody', 'click', (e) => window.JobHistoryActions.onTableClick(e), 'historyTableClick');
    Boot.onBridgeReady(() => this._connect());
  },

  _connect() {
    const b = Boot._bridge();
    if (!b || this._connected) return;
    this._connected = true;
    if (b.job_history_updated) b.job_history_updated.connect((json) => this.onHistory(json));
    if (b.thumbnail_ready) b.thumbnail_ready.connect((id, p) => this.onThumb(id, p));
    this.refresh();
  },

  _parse(json) {
    try { return typeof json === 'string' ? JSON.parse(json) : json; } catch { return null; }
  },

  onHistory(json) {
    const p = this._parse(json);
    if (!p) return;
    window.JobHistoryStore.setPayload(p);
    if (window.JobHistoryLimit) window.JobHistoryLimit.load(p);
    this.render();
  },

  onThumb(imgId, payloadJson) {
    window.JobHistoryActions.onThumbReady(imgId, payloadJson);
  },

  _set(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  },

  render() {
    const r = window.JobHistoryRender;
    this._set('historyTableBody', r.rows());
    this._set('historyCount', r.countText());
    window.JobHistoryActions.fetchThumbs();
  },

  refresh() { return window.JobHistoryActions.refresh(); },
  clear() { return window.JobHistoryActions.clear(); },
};
window.JobHistoryPanel = JobHistoryPanel;
