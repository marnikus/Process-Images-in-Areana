/* url-list/cooldown.js — cooldown config read/apply, ≤100 LOC, CC≤10 */
'use strict';
window.UrlListCooldown = {
  _bridge() { return window.App && window.App.bridge; },

  applyConfig(c) {
    const en = document.getElementById('urlCooldownEnabled');
    if (en) en.checked = c.enabled !== false;
    const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    setVal('urlCooldownMin', c.min_minutes ?? Math.round((c.min_seconds||300)/60));
    setVal('urlCooldownPenalty', c.captcha_penalty_minutes ?? Math.round((c.captcha_penalty_seconds||900)/60));
    setVal('urlCooldownRateLimit', c.rate_limit_penalty_minutes ?? Math.round((c.rate_limit_penalty_seconds||1800)/60));
  },

  readInputs() {
    const en = document.getElementById('urlCooldownEnabled');
    const getNum = (id, fb) => { const el = document.getElementById(id); const v = el ? parseFloat(el.value) : NaN; return isNaN(v) ? fb : v; };
    const minM = Math.max(0, Math.min(1440, getNum('urlCooldownMin',5)));
    const penM = Math.max(0, Math.min(1440, getNum('urlCooldownPenalty',15)));
    const rlM = Math.max(0, Math.min(1440, getNum('urlCooldownRateLimit',30)));
    return { en, minM, penM, rlM };
  },

  load() {
    const b = this._bridge();
    if (!b || !b.get_cooldown_config) return;
    b.get_cooldown_config((res)=>{
      try {
        const r=JSON.parse(res);
        if (!r.ok||!r.config) return;
        this.applyConfig(r.config);
      } catch {}
    });
  },

  save() {
    const inputs = this.readInputs();
    const payload = { enabled: inputs.en?inputs.en.checked:true, min_seconds:Math.round(inputs.minM*60), captcha_penalty_seconds:Math.round(inputs.penM*60), rate_limit_penalty_seconds:Math.round(inputs.rlM*60) };
    const b = this._bridge();
    if (b && b.set_cooldown_config) b.set_cooldown_config(JSON.stringify(payload),(res)=>{
      try {
        const r=JSON.parse(res);
        const msg = r.ok ? `Cooldown saved: ${inputs.en&&inputs.en.checked?'on':'off'} pause=${inputs.minM}m captcha=+${inputs.penM}m limit=+${inputs.rlM}m` : 'Cooldown save failed: '+r.error;
        if (typeof LogConsole !== 'undefined') LogConsole.log(msg, r.ok?'success':'error');
      } catch {}
    });
  },
};
