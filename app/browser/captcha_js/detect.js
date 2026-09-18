/* Captcha detect probe — self-contained, evaluated via CDP Runtime.evaluate.
   Verified against real arena.ai states (2026-09-18 research, see
   docs/archive/2026-09-18-captcha-detection-verification/design.md):
   * challenge dialog: role=dialog[data-state=open] + "Security Verification",
     enterprise anchor iframe (size=normal) inside div.recaptcha-v2-container,
     footer "Protected by reCAPTCHA", textarea[name=g-recaptcha-response]
   * badge (normal) state: .grecaptcha-badge with a size=invisible anchor
     iframe carrying a DIFFERENT sitekey — never a challenge, never a trigger.
   Output: {visible, kind, sitekey, invisible, url} — exact data the solver
   needs for its 2Captcha payload. RULE 21: semantic before structural. */
(() => {
  const out = {visible: false, kind: "none", sitekey: "", invisible: false, url: location.href};
  const IFRAME = 'iframe[title="reCAPTCHA"], iframe[src*="recaptcha"]';
  const WIDGET = IFRAME + ', div.recaptcha-v2-container, #recaptcha-v2-container';
  const isBadge = (el) => !!(el.closest && el.closest(".grecaptcha-badge"));
  const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
  let dialog = null;
  for (const d of dialogs) {
    const text = (d.innerText || d.textContent || "");
    const hasWidget = d.querySelector(WIDGET);
    if (text.includes("Security Verification") || text.includes("Protected by reCAPTCHA") || hasWidget) { dialog = d; break; }
  }
  let iframe = dialog ? dialog.querySelector(IFRAME) : null;
  if (!iframe) {
    const all = document.querySelectorAll(IFRAME);
    for (const f of all) { if (f.offsetParent !== null && !isBadge(f)) { iframe = f; break; } }
  }
  if (!dialog && !iframe) return out;
  out.visible = true;
  const src = iframe ? (iframe.getAttribute("src") || "") : "";
  const imageCaptcha = !!(dialog && dialog.querySelector('img[src*="captcha"], img[alt*="captcha" i]'));
  out.kind = imageCaptcha && !iframe ? "image"
           : src.includes("/recaptcha/api2/") ? "recaptcha_v2"
           : "recaptcha_enterprise";
  out.invisible = /[?&]size=invisible/.test(src);
  const m = src.match(/[?&]k=([A-Za-z0-9_-]{20,})/);
  if (m) out.sitekey = m[1];
  if (!out.sitekey) {
    const scope = dialog || document;
    const dk = scope.querySelector('[data-sitekey]');
    if (dk && dk.getAttribute("data-sitekey")) out.sitekey = dk.getAttribute("data-sitekey");
  }
  if (!out.sitekey && !dialog) {
    const dk = document.querySelector('[data-sitekey]');
    if (dk && dk.getAttribute("data-sitekey")) out.sitekey = dk.getAttribute("data-sitekey");
  }
  if (!out.sitekey) {
    try {
      for (const s of document.querySelectorAll("script")) {
        const m2 = (s.textContent || "").match(/6L[A-Za-z0-9_-]{29,}/);
        if (m2) { out.sitekey = m2[0]; break; }
      }
    } catch (e) { /* no inline scripts readable — stay without sitekey */ }
  }
  /* anchor-src diagnostics: does the dialog expose a callable cb=? how long
     does the widget give (anchor-ms/execute-ms)? Feeds the detect log line. */
  out.anchor = {
    cb: !!/[?&]cb=[A-Za-z0-9_$]/.test(src),
    size: (src.match(/[?&]size=([a-z]+)/i) || [])[1] || "",
    ams: (src.match(/[?&]anchor-ms=(\d+)/) || [])[1] || "",
    ems: (src.match(/[?&]execute-ms=(\d+)/) || [])[1] || "",
  };
  return out;
})()
