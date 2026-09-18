/* Recaptcha render hook — captures the dialog widget's sitecallback closure.
   Installed once per document (idempotent) at CDP attach AND on every reload
   (Page.addScriptToEvaluateOnNewDocument). Arena's escalation code
   (bundle module 980034 — see
   docs/archive/2026-09-18-captcha-escalation-path/design.md §2.2) renders
   the visible v2 enterprise widget via grecaptcha.enterprise.render and the
   render options `callback: token => …` is the ONLY thing that closes the
   dialog and makes arena retry the request with the token. Wrapping render
   BEFORE the first escalation captures that closure into
   window.__arenaV2Challenge = {sitekey, ts, solve(token)} so the solver can
   complete the canonical path with a 2Captcha token. */
(() => {
  const FLAG = "__arenaRecaptchaHook";
  const CH = "__arenaV2Challenge";
  if (window[FLAG]) return {installed: true, fresh: false, ready: _ready()};
  window[FLAG] = true;
  function _ready() {
    const ch = window[CH];
    return !!(ch && ch.sitekey) || !!(window.grecaptcha &&
      window.grecaptcha.enterprise && window.grecaptcha.enterprise.__hooked);
  }
  const install = () => {
    const ent = window.grecaptcha && window.grecaptcha.enterprise;
    if (!ent || typeof ent.render !== "function" || ent.__hooked) {
      return !!(ent && typeof ent.render === "function");
    }
    const orig = ent.render;
    ent.render = (container, opts) => {
      try {
        window[CH] = {
          sitekey: (opts && opts.sitekey) || "",
          ts: Date.now(),
          solve: (tok) => {
            try { opts.callback && opts.callback(tok); return true; }
            catch (e) { return false; }
          }
        };
      } catch (e) { /* capture never breaks the real render */ }
      return orig.call(ent, container, opts);
    };
    ent.__hooked = true;
    return true;
  };
  if (install()) return {installed: true, fresh: true, ready: true};
  /* the gstatic library may still be loading — poll briefly for render() */
  const t = setInterval(() => { if (install()) clearInterval(t); }, 200);
  setTimeout(() => clearInterval(t), 30000);
  return {installed: true, fresh: true, ready: false};
})()
