/* Captcha token injection probe — a function receiving (token, sitekey).
   A real user solve does TWO things in the parent page: (1) the widget
   fills the hidden g-recaptcha-response field(s), (2) the page's registered
   solve callback runs with the token. Per 2captcha docs that callback lives
   in the widget's data-callback attribute, the grecaptcha.render() options,
   or ___grecaptcha_cfg.clients[N]…callback — NOT in the anchor iframe's
   &cb= URL param (that is recaptcha's internal loader arg; round-4 premise
   disproved by live logs: window[cb] never exists). So: set EVERY response
   field (the badge's always-present field must not shadow the dialog's),
   then invoke the first callable in the data-callback → grecaptcha-cfg →
   anchor-cb chain. Result: {ok, scope, fields, len, cb, cbCalled, cbError,
   cbSource, clientsSeen}. */
// ideal-size: 122 lines reason=single self-contained page probe (fields + 3-step callback chain + bounded cfg search); splitting the payload would break the CDP-evaluated agent contract
(token, sitekey) => {
  try {
    const SEL = 'textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"], #g-recaptcha-response';
    const setField = (field) => {
      const proto = field.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) desc.set.call(field, token);
      else field.value = token;
      field.dispatchEvent(new Event("input", {bubbles: true}));
      field.dispatchEvent(new Event("change", {bubbles: true}));
    };
    const inOpenDialog = (el) => {
      const d = el.closest ? el.closest('div[role="dialog"]') : null;
      return !!d && d.getAttribute("data-state") === "open";
    };
    let fields = 0;
    let scope = "";
    let len = 0;
    const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
    for (const d of dialogs) {
      const found = d.querySelectorAll(SEL);
      for (const f of found) { setField(f); fields++; len = (f.value || "").length; }
      if (found.length) scope = "dialog";
    }
    const rest = document.querySelectorAll(SEL);
    for (const f of rest) {
      if (inOpenDialog(f)) continue;  // already set above — never double-fire events
      setField(f); fields++;
      if (!len) len = (f.value || "").length;
    }
    if (!fields) return {ok: false, error: "response field not found", cbSource: "none", clientsSeen: 0};
    if (!scope) scope = "document";
    let cb = null, cbCalled = false, cbError = null, cbSource = "none", clientsSeen = 0;
    const tryCall = (name, source) => {
      if (!name || typeof window[name] !== "function") return false;
      cb = name; cbSource = source;
      try { window[name](token); cbCalled = true; } catch (e) { cbError = String(e); }
      return true;
    };
    for (const d of dialogs) {  // (a) data-callback, dialog scope first
      const w = d.querySelector("[data-callback]");
      const name = w ? w.getAttribute("data-callback") : "";
      if (name && tryCall(name, "data-callback:" + name)) break;
    }
    if (!cb) {  // (a) data-callback, page scope
      const w = document.querySelector("[data-callback]");
      const name = w ? w.getAttribute("data-callback") : "";
      if (name) tryCall(name, "data-callback:" + name);
    }
    if (!cb) {  // (b) ___grecaptcha_cfg.clients deep search, sitekey-preferred
      const hit = findCfgCallback(window.___grecaptcha_cfg, sitekey || "");
      clientsSeen = hit.seen;
      if (hit.fn) {
        cb = hit.label; cbSource = "grecaptcha-cfg";
        try { hit.fn(token); cbCalled = true; } catch (e) { cbError = String(e); }
      }
    }
    if (!cb) {  // (c) legacy anchor &cb= last resort (kept: harmless, observable)
      let iframe = null;
      for (const d of dialogs) { iframe = d.querySelector('iframe[src*="recaptcha"]'); if (iframe) break; }
      if (!iframe) iframe = document.querySelector('iframe[src*="recaptcha"]');
      const src = iframe ? (iframe.getAttribute("src") || "") : "";
      const m = src.match(/[?&]cb=([A-Za-z0-9_$][\w$]*)/);
      if (m) tryCall(m[1], "anchor-cb:" + m[1]);
    }
    return {ok: true, scope, fields, len, cb, cbCalled, cbError, cbSource, clientsSeen};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
  function findCfgCallback(cfg, want) {
    const out = {fn: null, label: "", seen: 0};
    const clients = cfg && cfg.clients;
    if (!clients || typeof clients !== "object") return out;
    const ids = Object.keys(clients).slice(0, 10);
    out.seen = ids.length;
    const budget = {n: 0};
    const findCb = (node, depth) => {
      if (budget.n > 2000 || !node || depth > 6 || typeof node !== "object") return null;
      for (const k in node) {
        if (++budget.n > 2000) return null;
        let v = null;
        try { v = node[k]; } catch (e) { continue; }
        if (k === "callback" && typeof v === "function") return v;
        const sub = findCb(v, depth + 1);
        if (sub) return sub;
      }
      return null;
    };
    const hasKey = (node, depth) => {
      if (budget.n > 2000 || !node || depth > 6) return false;
      if (typeof node === "string") return !!want && node.indexOf(want) !== -1;
      if (typeof node !== "object") return false;
      for (const k in node) {
        if (++budget.n > 2000) return false;
        try { if (hasKey(node[k], depth + 1)) return true; } catch (e) { /* skip unreadable */ }
      }
      return false;
    };
    for (const id of ids) {
      let cli = null;
      try { cli = clients[id]; } catch (e) { continue; }
      const fn = findCb(cli, 0);
      if (typeof fn !== "function") continue;
      if (!out.fn) { out.fn = fn; out.label = "client:" + id; }
      if (want && hasKey(cli, 0)) { out.fn = fn; out.label = "client:" + id; break; }
    }
    return out;
  }
}
