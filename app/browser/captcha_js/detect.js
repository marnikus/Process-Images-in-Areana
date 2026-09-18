/* Captcha detect probe — self-contained, evaluated via CDP Runtime.evaluate.
   Verified against real arena.ai states (2026-09-18 research, see
   docs/archive/2026-09-18-captcha-detection-verification/design.md and
   docs/archive/2026-09-18-captcha-pass-path/design.md):
   * challenge dialog: role=dialog[data-state=open] + "Security Verification",
     enterprise anchor iframe (size=normal) inside div.recaptcha-v2-container,
     footer "Protected by reCAPTCHA", textarea[name=g-recaptcha-response]
   * badge (normal) state: .grecaptcha-badge with a size=invisible anchor
     iframe carrying a DIFFERENT sitekey — never a challenge, never a trigger.
   * sitekey preference (pass-path round): the dialog widget's own key wins
     (dialog_iframe_k → dialog_data_sitekey → page chain); the badge key is
     excluded from fallbacks when its iframe exposes it, so a paid task is
     never created for the wrong widget.
   * identity correlation (token-vs-page round): the challenge frame identity
     + the page's own timeOrigin travel with the signal so a token is only
     injected into the page state that asked for it
     (docs/archive/2026-09-18-recaptcha-verification-architecture/).
   Output: {visible, kind, sitekey, invisible, url, dom} — exact data the
   solver needs for its 2Captcha payload, plus the semantic DOM anchor
   for captcha reports. RULE 21: semantic before structural. */
(() => {
  const out = {visible: false, kind: "none", sitekey: "", invisible: false,
    url: location.href, integration: "unknown", anchorPresent: false,
    anchorVisible: false, challengePresent: false, challengeVisible: false,
    challengeActive: false, challengeTitle: "", challengeSrc: "",
    challengeIdentity: "", responseFields: 0, responseScope: "none",
    sitekeySource: "none",
    pageIdentity: location.href + "|" + (typeof performance !== "undefined" ? String(performance.timeOrigin || "") : "")};
  const IFRAME = 'iframe[title="reCAPTCHA"], iframe[src*="recaptcha"], iframe[src*="bframe"]';
  const WIDGET = IFRAME + ', div.recaptcha-v2-container, #recaptcha-v2-container';
  const KEY = /[?&]k=([A-Za-z0-9_-]{20,})/;
  const isBadge = (el) => !!(el.closest && el.closest(".grecaptcha-badge"));
  const visible = (el) => {
    if (!el) return false;
    if (el.offsetParent !== null) return true;
    try { return getComputedStyle(el).visibility !== "hidden"; }
    catch (_) { return false; }
  };
  const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
  let dialog = null;
  for (const d of dialogs) {
    const text = (d.innerText || d.textContent || "");
    const hasWidget = d.querySelector(WIDGET);
    if (text.includes("Security Verification") || text.includes("Protected by reCAPTCHA") || hasWidget) { dialog = d; break; }
  }
  const allFrames = Array.from(document.querySelectorAll(IFRAME));
  const anchors = allFrames.filter((f) => isBadge(f) || f.title === "reCAPTCHA");
  const challenges = allFrames.filter((f) => (f.title || "").toLowerCase().includes("challenge") ||
    (f.src || "").includes("/bframe") || (f.getAttribute("src") || "").includes("bframe"));
  const shown = (el) => {  // ancestor visibility walk (jsdom+harness safe)
    try {
      let n = el;
      while (n && n.nodeType === 1) {
        const st = window.getComputedStyle ? window.getComputedStyle(n) : null;
        if (st && (st.visibility === "hidden" || st.display === "none")) return false;
        const ist = n.getAttribute ? (n.getAttribute("style") || "") : "";
        if (/visibility:\s*hidden/.test(ist) || /top:\s*-\d{4,}px/.test(ist)) return false;
        n = n.parentElement;
      }
      return true;
    } catch (_) { return true; }  // unprovable → report as candidate, never hide
  };
  out.anchorPresent = anchors.length > 0;
  out.anchorVisible = anchors.some(visible);
  out.challengePresent = challenges.length > 0;
  out.challengeVisible = challenges.some(visible);
  out.challengeActive = challenges.some((f) => visible(f) && shown(f));
  if (challenges[0]) {
    out.challengeTitle = (challenges[0].title || "").slice(0, 120);
    out.challengeSrc = (() => { try { const u = new URL(challenges[0].src); return u.host + u.pathname; } catch (_) { return "challenge"; } })();
    out.challengeIdentity = ((challenges[0].name || challenges[0].title || "challenge") + "|" + out.challengeSrc).slice(0, 120);
  }
  let iframe = dialog ? dialog.querySelector(IFRAME) : null;
  if (!iframe) {
    for (const f of allFrames) { if (visible(f) && !isBadge(f) && !challenges.includes(f)) { iframe = f; break; } }
  }
  const fields = Array.from(document.querySelectorAll('textarea[name="g-recaptcha-response"], textarea[id*="g-recaptcha-response"]'));
  out.responseFields = fields.length;
  const dialogFields = dialog ? fields.filter((f) => dialog.contains(f)).length : 0;
  out.responseScope = dialogFields ? "dialog" : fields.length ? "document" : "none";
  out.integration = document.querySelector('script[src*="enterprise"], script[id*="recaptcha-enterprise"]') ? "enterprise" : "unknown";
  if (!dialog && !iframe && !out.challengeVisible) return out;
  out.visible = true;
  const src = iframe ? (iframe.getAttribute("src") || "") : "";
  const imageCaptcha = !!(dialog && dialog.querySelector('img[src*="captcha"], img[alt*="captcha" i]'));
  out.dom = (dialog ? "dialog" : "page") + ":"
    + (imageCaptcha && !iframe ? "image" : iframe ? "recaptcha-iframe" : "no-widget");
  out.kind = imageCaptcha && !iframe ? "image"
           : src.includes("/recaptcha/api2/") ? "recaptcha_v2"
           : "recaptcha_enterprise";
  out.invisible = /[?&]size=invisible/.test(src);
  /* Sitekey preference (pass-path round): the dialog widget's own key first;
     the badge's key (different widget, different paid task) is excluded from
     every fallback once its iframe exposes it. */
  const badgeKeys = new Set();
  const badgeEl = document.querySelector(".grecaptcha-badge");
  const badgeFrame = badgeEl && badgeEl.querySelector ? badgeEl.querySelector("iframe") : null;
  if (badgeFrame) {
    const bm = (badgeFrame.getAttribute("src") || "").match(KEY);
    if (bm) badgeKeys.add(bm[1]);
  }
  let m = src.match(KEY);
  if (m) { out.sitekey = m[1]; out.sitekeySource = dialog ? "dialog_iframe_k" : "iframe_k"; }
  if (!out.sitekey && dialog) {
    const dk = dialog.querySelector("[data-sitekey]");
    if (dk && dk.getAttribute("data-sitekey")) { out.sitekey = dk.getAttribute("data-sitekey"); out.sitekeySource = "dialog_data_sitekey"; }
  }
  if (!out.sitekey && !dialog) {
    const dk = document.querySelector('[data-sitekey]');
    if (dk && dk.getAttribute("data-sitekey")) { out.sitekey = dk.getAttribute("data-sitekey"); out.sitekeySource = "data-sitekey"; }
  }
  if (!out.sitekey) {
    try {
      for (const s of document.querySelectorAll("script")) {
        const m2 = (s.textContent || "").match(KEY) || (s.textContent || "").match(/6L[A-Za-z0-9_-]{29,}/);
        const key = m2 ? (m2[1] || m2[0]) : "";
        if (key && !badgeKeys.has(key)) { out.sitekey = key; out.sitekeySource = "script"; break; }
      }
    } catch (e) { /* no inline scripts readable — stay without sitekey */ }
  }
  return out;
})()
