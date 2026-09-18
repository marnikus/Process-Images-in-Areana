/* Captcha detect probe — self-contained, evaluated via CDP Runtime.evaluate.
   Verified against real arena.ai states (2026-09-18 research, see
   docs/archive/2026-09-18-captcha-detection-verification/design.md):
   * challenge dialog: role=dialog[data-state=open] + "Security Verification",
     enterprise anchor iframe (size=normal) inside div.recaptcha-v2-container,
     footer "Protected by reCAPTCHA", textarea[name=g-recaptcha-response]
   * badge (normal) state: .grecaptcha-badge with a size=invisible anchor
     iframe carrying a DIFFERENT sitekey — never a challenge, never a trigger.
   Output: {visible, kind, sitekey, invisible, url, dom} — exact data the
   solver needs for its 2Captcha payload, plus the semantic DOM anchor
   for captcha reports. RULE 21: semantic before structural. */
(() => {
  const out = {visible: false, kind: "none", sitekey: "", invisible: false,
    url: location.href, integration: "unknown", anchorPresent: false,
    anchorVisible: false, challengePresent: false, challengeVisible: false,
    challengeTitle: "", challengeSrc: "", responseFields: 0,
    responseScope: "none", sitekeySource: "none",
    pageIdentity: location.href};
  const IFRAME = 'iframe[title="reCAPTCHA"], iframe[src*="recaptcha"]';
  const WIDGET = IFRAME + ', div.recaptcha-v2-container, #recaptcha-v2-container';
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
    (f.src || "").includes("/bframe"));
  out.anchorPresent = anchors.length > 0;
  out.anchorVisible = anchors.some(visible);
  out.challengePresent = challenges.length > 0;
  out.challengeVisible = challenges.some(visible);
  if (challenges[0]) {
    out.challengeTitle = (challenges[0].title || "").slice(0, 120);
    out.challengeSrc = (() => { try { const u = new URL(challenges[0].src); return u.host + u.pathname; } catch (_) { return "challenge"; } })();
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
  const m = src.match(/[?&]k=([A-Za-z0-9_-]{20,})/);
  if (m) { out.sitekey = m[1]; out.sitekeySource = "iframe_k"; }
  if (!out.sitekey) {
    const scope = dialog || document;
    const dk = scope.querySelector('[data-sitekey]');
    if (dk && dk.getAttribute("data-sitekey")) { out.sitekey = dk.getAttribute("data-sitekey"); out.sitekeySource = "data-sitekey"; }
  }
  if (!out.sitekey && !dialog) {
    const dk = document.querySelector('[data-sitekey]');
    if (dk && dk.getAttribute("data-sitekey")) { out.sitekey = dk.getAttribute("data-sitekey"); out.sitekeySource = "data-sitekey"; }
  }
  if (!out.sitekey) {
    try {
      for (const s of document.querySelectorAll("script")) {
        const m2 = (s.textContent || "").match(/6L[A-Za-z0-9_-]{29,}/);
        if (m2) { out.sitekey = m2[0]; out.sitekeySource = "script"; break; }
      }
    } catch (e) { /* no inline scripts readable — stay without sitekey */ }
  }
  return out;
})()
