/* Captcha deep-scan probe (2026-09-18 completion research) — async IIFE,
   evaluated with awaitPromise. Extends "🔍 Scan now" with the evidence that
   answers "what does the dialog's callback actually do with the token":
   1. the open dialog's outerHTML (truncated) — the REAL current markup,
   2. the window.grecaptcha API surface (is getResponse patched? current
      response value?) — the widget-internal consumption path,
   3. same-origin bundle source around 'recaptcha-v2-container' /
      'Security Verification' — the dialog component + its sitecallback
      logic, from the user's own loaded page.
   Self-contained, RULE 8: node-tested. */
(async () => {
  const out = {dialog_html: "", grecaptcha: null, hits: [], errors: []};
  try {
    const d = document.querySelector('div[role="dialog"][data-state="open"]');
    if (d) out.dialog_html = (d.outerHTML || "").replace(/\s+/g, " ").slice(0, 1500);
  } catch (e) { out.errors.push("dialog_html: " + e); }
  try {
    const api = window.grecaptcha;
    if (api) {
      const g = {keys: Object.keys(api).slice(0, 24)};
      if (typeof api.getResponse === "function") {
        g.has_getResponse = true;
        try { g.current_response_len = String(api.getResponse() || "").length; } catch (e) { g.getResponse_error = String(e); }
      }
      out.grecaptcha = g;
    }
  } catch (e) { out.errors.push("grecaptcha: " + e); }
  try {
    const MARKERS = ["recaptcha-v2-container", "Security Verification"];
    const scripts = Array.from(document.querySelectorAll('script[src]'))
      .map((s) => s.src)
      .filter((u) => u.includes(location.host) && u.endsWith(".js"))
      .slice(0, 8);
    for (const url of scripts) {
      let txt = "";
      try { txt = await (await fetch(url, {credentials: "same-origin"})).text(); }
      catch (e) { continue; }
      for (const m of MARKERS) {
        let i = txt.indexOf(m);
        let n = 0;
        while (i !== -1 && n < 2 && out.hits.length < 6) {
          out.hits.push({
            file: url.split("/").pop(),
            marker: m,
            src: txt.slice(Math.max(0, i - 160), i + 420).replace(/\s+/g, " "),
          });
          i = txt.indexOf(m, i + 1);
          n += 1;
        }
      }
    }
  } catch (e) { out.errors.push("bundles: " + e); }
  return out;
})()
