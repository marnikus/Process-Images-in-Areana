/* Captcha diagnose probe — the gate verdict PLUS the evidence behind it.
   One CDP eval gives the wait gate (cdp_arena._security_gate) and the
   on-demand "Scan now" (bridge.diagnose_captcha) everything they need to
   say WHY they saw what they saw (2026-09-18: "detection is not clear —
   show the steps; give steps to debug it now").

   Verdict logic is IDENTICAL to visible.js (the canonical gate predicate —
   keep them in sync): open role=dialog with "Security Verification" /
   "Protected by reCAPTCHA" / a reCAPTCHA iframe, OR a non-badge reCAPTCHA
   iframe actually on screen (geometry + visibility walk). The badge is
   never a challenge. Superset of detect.js: kind/sitekey/invisible/anchor
   are extracted the same way, only when a challenge exists.

   Self-contained IIFE, returns a JSON-able dict:
   {visible, kind, sitekey, invisible, url, anchor{cb,size,ams,ems},
    evidence{dialogs_open, dialog_hits[], iframes[], reason}}
   RULE 21: semantic before structural; RULE 8: node tests execute this. */
(() => {
  const out = {visible: false, kind: "none", sitekey: "", invisible: false, url: location.href,
               anchor: {cb: false, size: "", ams: "", ems: ""},
               evidence: {dialogs_open: 0, dialog_hits: [], iframes: [], reason: ""}};
  const IFRAME = 'iframe[title="reCAPTCHA"], iframe[src*="recaptcha"]';
  const WIDGET = IFRAME + ', div.recaptcha-v2-container, #recaptcha-v2-container';
  const inBadge = (el) => !!(el.closest && el.closest(".grecaptcha-badge"));
  const onScreen = (el) => {
    if (el.offsetParent === null) return false;
    let n = el;
    while (n && n.nodeType === 1) {
      const s = window.getComputedStyle(n);
      if (s.display === "none" || s.visibility === "hidden" || s.visibility === "collapse") return false;
      n = n.parentElement;
    }
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 &&
           r.left < window.innerWidth && r.top < window.innerHeight;
  };
  const dialogs = Array.from(document.querySelectorAll('div[role="dialog"][data-state="open"]'));
  out.evidence.dialogs_open = dialogs.length;
  let dialog = null, dialogHits = [];
  for (const d of dialogs) {
    const text = (d.innerText || d.textContent || "");
    const hits = [];
    if (text.includes("Security Verification")) hits.push("Security Verification");
    if (text.includes("Protected by reCAPTCHA")) hits.push("Protected by reCAPTCHA");
    if (d.querySelector(WIDGET)) hits.push("widget");
    out.evidence.dialog_hits.push({text: text.replace(/\s+/g, " ").trim().slice(0, 80), hits});
    if (!dialog && (hits.length || d.querySelector(IFRAME))) { dialog = d; dialogHits = hits.length ? hits : ["iframe"]; }
  }
  const frames = Array.from(document.querySelectorAll(IFRAME));
  out.evidence.iframes = frames.slice(0, 6).map((f) => {
    const r = f.getBoundingClientRect();
    return {in_badge: inBadge(f), in_dialog: !!(f.closest && f.closest('div[role="dialog"]')),
            on_screen: onScreen(f), w: Math.round(r.width), h: Math.round(r.height),
            x: Math.round(r.left), y: Math.round(r.top),
            title: (f.getAttribute("title") || "").slice(0, 40),
            src: (f.getAttribute("src") || "").slice(0, 90)};
  });
  let iframe = dialog ? dialog.querySelector(IFRAME) : null;
  if (dialog) {
    out.visible = true;  // verdict parity with visible.js: open dialog is a challenge
    out.evidence.reason = "open dialog: " + (dialogHits.join(", ") || "iframe");
  } else {
    for (const f of frames) {
      if (!inBadge(f) && onScreen(f)) { iframe = f; break; }
    }
    if (iframe) {
      out.visible = true;
      out.evidence.reason = "reCAPTCHA iframe on screen (not badge)";
    }
  }
  if (!out.visible) {
    const badge = frames.filter((f) => inBadge(f)).length;
    out.evidence.reason = "no open dialog; " + frames.length +
      " recaptcha iframe(s) — " + badge + " in badge, " + (frames.length - badge) + " hidden/off-screen";
  }
  const src = iframe ? (iframe.getAttribute("src") || "") : "";
  const imageCaptcha = !!(dialog && dialog.querySelector('img[src*="captcha"], img[alt*="captcha" i]'));
  if (out.visible) {
    out.kind = imageCaptcha && !iframe ? "image"
               : src.includes("/recaptcha/api2/") ? "recaptcha_v2"
               : "recaptcha_enterprise";
    out.invisible = /[?&]size=invisible/.test(src);
    const m = src.match(/[?&]k=([A-Za-z0-9_-]{20,})/);
    if (m) out.sitekey = m[1];
    if (!out.sitekey) {
      const dk = (dialog || document).querySelector('[data-sitekey]');
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
    out.anchor = {
      cb: !!/[?&]cb=[A-Za-z0-9_$]/.test(src),
      size: (src.match(/[?&]size=([a-z]+)/i) || [])[1] || "",
      ams: (src.match(/[?&]anchor-ms=(\d+)/) || [])[1] || "",
      ems: (src.match(/[?&]execute-ms=(\d+)/) || [])[1] || "",
    };
  }
  return out;
})()
