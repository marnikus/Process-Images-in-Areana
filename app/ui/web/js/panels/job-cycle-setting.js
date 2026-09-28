/* job-cycle-setting.js — the Settings → Job Cycle box: "Enable minimum pause between jobs"
   and the I-79 "Start new chat as new tab" option. Both ride the cooldown slots (no new
   slot, no second state): the switch is a VIEW of `cooldown_enabled` — the same key as the
   URL List bar's "on" (the bar is the only home of the pause / captcha values). `save()`
   (Settings → Save) sends ONLY {enabled, new_tab, new_tab_url}, so the bar's values are
   never reset. After every save / preset restore the bridge pushes the stored state
   (`cooldown_config_updated`) and `apply()` re-renders BOTH views from it. */
'use strict';
const JobCycleSetting = {
  init() {
    Boot.onBridgeReady(() => this._connect());
  },

  _connect() {
    const b = Boot._bridge();
    if (!b || this._connected) return;
    this._connected = true;
    if (b.cooldown_config_updated) b.cooldown_config_updated.connect((json) => this.apply(json));
    this.load();
  },

  load() {
    const call = Boot.needBridge('get_cooldown_config');
    if (call) call((res) => this.showReply(res));
  },

  /* The push handler: both views of the one stored state re-render — no stale "on" box. */
  apply(json) {
    const r = this.showReply(json);
    if (r?.config) window.UrlListCooldown?.applyConfig(r.config);
  },

  showReply(json) {
    try {
      const r = JSON.parse(json);
      if (!r.ok) return null;
      this.showEnabled(r.config);
      this.show(r.new_tab);
      return r;
    } catch { return null; }
  },

  showEnabled(config) {
    const box = document.getElementById('cooldownEnabled');
    if (box && config) box.checked = config.enabled !== false;   // missing = on, like the bar
  },

  show(setting) {
    if (!setting) return;
    const box = document.getElementById('newTabEnabled');
    const url = document.getElementById('newTabUrl');
    if (box) box.checked = !!setting.enabled;
    if (url) url.value = setting.url || '';
  },

  save() {
    const call = Boot.needBridge('set_cooldown_config');
    if (!call) return;
    const payload = this.read();
    call(JSON.stringify(payload), (res) => {
      try {
        const r = JSON.parse(res);
        const text = r.ok ? this.savedText(payload) : 'Job Cycle save failed: ' + r.error;
        if (typeof LogConsole !== 'undefined') LogConsole.log(text, r.ok ? 'success' : 'error');
      } catch {}
    });
  },

  savedText(payload) {
    const pause = payload.enabled === undefined ? '' : `minimum pause ${payload.enabled ? 'on' : 'off'} · `;
    return `Job Cycle saved: ${pause}new chat as new tab ${payload.new_tab ? 'on' : 'off'}`;
  },

  read() {
    const box = document.getElementById('newTabEnabled');
    const url = document.getElementById('newTabUrl');
    const pause = document.getElementById('cooldownEnabled');
    const payload = { new_tab: !!box?.checked, new_tab_url: (url?.value || '').trim() };
    if (pause) payload.enabled = !!pause.checked;
    return payload;
  },
};
if (typeof window !== 'undefined') window.JobCycleSetting = JobCycleSetting;
