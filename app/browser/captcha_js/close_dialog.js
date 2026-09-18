/* Captcha dialog close probe (2026-09-18 completion fix) — ONE step per call.
   The dialog's widget callback (a JS closure) is the ONLY thing that closes
   it after a real solve — an injected token never fires it, so the dialog
   is stuck by design. Python drives the steps with waits between them
   (React re-renders async, so each step needs its own poll):
     step "esc"     — Escape keydown (Radix Dialog's native close, React-proper),
     step "close"   — click the Radix close control,
     step "nuclear" — remove open dialog node(s) + focus guards + overlay siblings.
   Returns {ok, used}; the caller re-verifies with the visibility predicate
   before the next step. Self-contained, RULE 8: node-tested. */
(step) => {
  try {
    const openDialogs = () => document.querySelectorAll('div[role="dialog"][data-state="open"]');
    if (step === "esc") {
      if (!openDialogs().length) return {ok: true, used: "none"};
      const ev = new KeyboardEvent("keydown", {key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true});
      openDialogs().forEach((d) => d.dispatchEvent(ev));
      document.dispatchEvent(ev);
      return {ok: true, used: "esc"};
    }
    if (step === "close") {
      if (!openDialogs().length) return {ok: true, used: "none"};
      for (const d of openDialogs()) {
        const cands = d.querySelectorAll('[data-radix-dialog-close], button[aria-label="Close"], button[aria-label*="close" i]');
        for (const b of cands) {
          if (b.offsetParent === null) continue;
          b.click();
          return {ok: true, used: "close-btn"};
        }
      }
      return {ok: false, reason: "no close control found"};
    }
    if (step === "nuclear") {
      let removed = 0;
      const kill = (el) => { if (el && el.parentNode) { el.parentNode.removeChild(el); removed += 1; } };
      for (const d of openDialogs()) {
        const portal = d.parentElement;
        if (portal) {
          for (const sib of Array.from(portal.children)) {
            if (sib === d) continue;
            const st = sib.getAttribute ? sib.getAttribute("data-state") : null;
            const cls = String((sib.getAttribute && sib.getAttribute("class")) || "");
            if (sib.getAttribute && sib.getAttribute("data-radix-focus-guard") !== null) kill(sib);
            else if (st === "open" && !sib.getAttribute("role")) kill(sib);  // shadcn overlay sibling
            else if (cls.includes("fixed") && cls.includes("inset-0")) kill(sib);
          }
        }
        kill(d);
      }
      for (const g of document.querySelectorAll('[data-radix-focus-guard]')) kill(g);
      return {ok: true, used: "nuclear", removed};
    }
    return {ok: false, reason: "unknown step: " + step};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
}
