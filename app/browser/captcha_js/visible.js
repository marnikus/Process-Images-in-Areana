/* Security dialog visibility predicate — the ONE gate every captcha call
   site checks before entering the captcha flow (CDPArenaController.
   is_security_dialog_visible).
   A real challenge = an open role=dialog containing "Security
   Verification" (or a reCAPTCHA widget inside it), or a VISIBLE reCAPTCHA
   iframe OUTSIDE the always-present .grecaptcha-badge. The page's badge
   widget carries its own size=invisible anchor iframe (a DIFFERENT
   sitekey than the challenge dialog) and is on screen in the normal
   state — it is NOT a challenge and must never start the captcha flow
   (2026-09-18 research: two coexisting sitekeys). */
(() => {
  const inBadge = (el) => !!(el.closest && el.closest(".grecaptcha-badge"));
  const IFRAME = 'iframe[title="reCAPTCHA"], iframe[src*="recaptcha"]';
  const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
  for (const d of dialogs) {
    if (d.innerText && d.innerText.includes('Security Verification')) return true;
    if (d.querySelector(IFRAME)) return true;
  }
  const iframes = document.querySelectorAll(IFRAME);
  for (const f of iframes) {
    if (f.offsetParent !== null && !inBadge(f)) return true;
  }
  return false;
})()
