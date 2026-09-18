/* Captcha dialog continue-click probe — clicks the semantic action button
   of the visible security dialog (submit type, verify/continue/confirm
   aria-label or exact button text). Best effort: the site may auto-submit
   on token receipt, in which case no button exists and that is fine. */
(() => {
  try {
    const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
    for (const d of dialogs) {
      const cands = d.querySelectorAll('button, [role="button"]');
      for (const b of cands) {
        if (b.offsetParent === null || b.disabled) continue;
        const label = (b.getAttribute("aria-label") || "").toLowerCase();
        const text = (b.innerText || b.textContent || "").trim().toLowerCase();
        const byType = b.tagName === "BUTTON" && b.type === "submit";
        const byLabel = /verify|continue|confirm|check|proceed/.test(label);
        const byText = /^(verify|continue|confirm|check|proceed|ok|submit|done)$/.test(text);
        if (byType || byLabel || byText) {
          b.click();
          return {ok: true, used: (label || text || "submit").slice(0, 40)};
        }
      }
    }
    return {ok: false, reason: "no action button found"};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
})()
