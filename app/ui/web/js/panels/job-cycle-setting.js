/* job-cycle-setting.js — the Settings → Job Cycle box (I-79 "Start new chat as new tab").
   The option rides the cooldown slots (no new slot): `load()` shows the `new_tab`
   part of get_cooldown_config; `save()` (Settings → Save) sends ONLY its two keys, so
   the URL List bar's pause values are never reset (the server stores what it gets). */
'use strict';
const JobCycleSetting = {
  init() {
    Boot.onBridgeReady(() => this.load());
  },

  load() {
    const call = Boot.needBridge('get_cooldown_config');
    if (call) call((res) => { try { this.show(JSON.parse(res).new_tab); } catch {} });
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
        const text = r.ok ? `New chat as new tab: ${payload.new_tab ? 'on' : 'off'}` : 'New-tab option save failed: ' + r.error;
        if (typeof LogConsole !== 'undefined') LogConsole.log(text, r.ok ? 'success' : 'error');
      } catch {}
    });
  },

  read() {
    const box = document.getElementById('newTabEnabled');
    const url = document.getElementById('newTabUrl');
    return { new_tab: !!box?.checked, new_tab_url: (url?.value || '').trim() };
  },
};
if (typeof window !== 'undefined') window.JobCycleSetting = JobCycleSetting;
