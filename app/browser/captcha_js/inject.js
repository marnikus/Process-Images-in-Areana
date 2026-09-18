/* Captcha token injection probe — a function receiving the solved token.
   A real user solve does TWO things in the parent page: (1) the widget
   fills the hidden g-recaptcha-response field, (2) the anchor iframe calls
   the random-named global callback registered in its src (&cb=<name>).
   arena.ai closes the dialog and resumes the request from (2) — so we do
   both: set the field (dialog-scoped first, then document) with a
   React-safe setter + input/change events, then invoke window[cb](token). */
(token) => {
  try {
    const SEL = 'textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"], #g-recaptcha-response';
    let field = null;
    let scope = "";
    let dialog = null;
    const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
    for (const d of dialogs) {
      field = d.querySelector(SEL);
      if (field) { scope = "dialog"; dialog = d; break; }
    }
    if (!field) {
      field = document.querySelector(SEL);
      if (field) scope = "document";
    }
    if (!field) return {ok: false, error: "response field not found"};
    const proto = field.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(field, token);
    else field.value = token;
    field.dispatchEvent(new Event("input", {bubbles: true}));
    field.dispatchEvent(new Event("change", {bubbles: true}));
    let cb = null, cbCalled = false, cbError = null;
    const iframe = (dialog || document).querySelector('iframe[src*="recaptcha"]');
    const src = iframe ? (iframe.getAttribute("src") || "") : "";
    const m = src.match(/[?&]cb=([A-Za-z0-9_$][\w$]*)/);
    if (m && typeof window[m[1]] === "function") {
      cb = m[1];
      try { window[cb](field.value); cbCalled = true; } catch (e) { cbError = String(e); }
    }
    return {ok: true, scope, tag: field.tagName, len: (field.value || "").length, cb, cbCalled, cbError};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
}
