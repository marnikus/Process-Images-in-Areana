/* new-tab-setting.js — Settings → Job Cycle: "Start new chat as new tab" (I-79).
   The option rides the cooldown slots (no new slot): `load()` shows the `new_tab`
   part of get_cooldown_config, and settings.js's saveCooldown sends `read()` with
   the cooldown payload. Own module because settings.js is size-frozen (JS ratchet). */
'use strict';
const NewTabSetting = {
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

  read() {
    const box = document.getElementById('newTabEnabled');
    const url = document.getElementById('newTabUrl');
    return { new_tab: !!box?.checked, new_tab_url: (url?.value || '').trim() };
  },
};
if (typeof window !== 'undefined') window.NewTabSetting = NewTabSetting;
