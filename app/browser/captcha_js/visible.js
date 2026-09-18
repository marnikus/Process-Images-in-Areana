/* Security dialog visibility predicate — the ONE gate every captcha call
   site checks before entering the captcha flow (CDPArenaController.
   is_security_dialog_visible).
   A real challenge = an open role=dialog containing "Security
   Verification" / "Protected by reCAPTCHA" (or a reCAPTCHA widget inside
   it), OR a reCAPTCHA iframe that is ACTUALLY VISIBLE ON SCREEN.
   The always-present .grecaptcha-badge is position:fixed + display:block
   in the normal state, so offsetParent alone reads "present" while the
   widget is visibility:hidden and off-screen (right:-186px) — hence the
   identity exclusion (2026-09-18) AND the on-screen geometry/visibility
   walk (2026-09-18b: "detect the moment it is on screen"). */
(() => {
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
    return r.width > 0 && r.height > 0 &&
           r.right > 0 && r.bottom > 0 && r.left < window.innerWidth && r.top < window.innerHeight;
  };
  const IFRAME = 'iframe[title="reCAPTCHA"], iframe[src*="recaptcha"]';
  const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
  for (const d of dialogs) {
    if (d.innerText && d.innerText.includes('Security Verification')) return true;
    if (d.innerText && d.innerText.includes('Protected by reCAPTCHA')) return true;
    if (d.querySelector(IFRAME)) return true;
  }
  const iframes = document.querySelectorAll(IFRAME);
  for (const f of iframes) {
    if (!inBadge(f) && onScreen(f)) return true;
  }
  return false;
})()
