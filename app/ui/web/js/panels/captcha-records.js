/* Redacted CAPTCHA session review; labels are operator annotations only. */
'use strict';
(() => {
  const state = {rows: [], selected: ''};
  const bridge = () => (typeof App !== 'undefined' ? App.bridge : null);
  const parse = (raw) => { try { return typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (_) { return {ok:false}; } };
  const el = (id) => document.getElementById(id);
  const render = () => {
    const list = el('captchaRecordsList');
    if (!list) return;
    list.innerHTML = state.rows.map((r) => `<button class="btn-small ${r.rid === state.selected ? 'btn-primary' : ''}" data-rid="${r.rid}">${r.label || 'unknown'} · ${r.terminal_outcome || 'active'} · ${r.rid}</button>`).join('<br>') || 'No recordings';
    list.querySelectorAll('[data-rid]').forEach((b) => b.onclick = () => select(b.dataset.rid));
  };
  const select = (rid) => {
    state.selected = rid;
    const b = bridge();
    if (!b || !b.get_captcha_recording) return;
    b.get_captcha_recording(rid, (raw) => {
      const data = parse(raw);
      const m = data.manifest || {};
      el('captchaRecordLabel').value = m.label || 'unknown';
      el('captchaRecordNote').value = m.label_note || '';
      el('captchaRecordDetail').textContent = JSON.stringify({manifest:m, events:data.events || []}, null, 2);
      render();
    });
  };
  const refresh = () => {
    const b = bridge();
    if (!b || !b.list_captcha_recordings) return;
    b.list_captcha_recordings((raw) => { const data = parse(raw); state.rows = data.records || []; render(); });
  };
  const save = () => {
    const b = bridge(); if (!b || !state.selected) return;
    b.label_captcha_recording(state.selected, el('captchaRecordLabel').value, el('captchaRecordNote').value, (ok) => {
      el('captchaRecordsStatus').textContent = ok ? 'Label saved.' : 'Label was not saved.'; refresh();
    });
  };
  document.addEventListener('DOMContentLoaded', () => {
    el('captchaRecordsRefreshBtn')?.addEventListener('click', refresh);
    el('captchaRecordsSaveBtn')?.addEventListener('click', save);
    el('captchaRecordsClearBtn')?.addEventListener('click', () => { const b=bridge(); if (b?.clear_captcha_recordings) b.clear_captcha_recordings(() => refresh()); });
    refresh();
  });
})();
