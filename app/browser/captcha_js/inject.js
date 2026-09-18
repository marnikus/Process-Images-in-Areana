/* Captcha token injection probe — a function receiving the solved token.
   Sets the reCAPTCHA hidden response field (dialog-scoped first, then
   document) with a React-safe setter + input/change events. The token is
   then submitted by the site's own dialog action (continue_click.js). */
(token) => {
  try {
    const SEL = 'textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"], #g-recaptcha-response';
    let field = null;
    let scope = "";
    const dialogs = document.querySelectorAll('div[role="dialog"][data-state="open"]');
    for (const d of dialogs) {
      field = d.querySelector(SEL);
      if (field) { scope = "dialog"; break; }
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
    return {ok: true, scope, tag: field.tagName, len: (field.value || "").length};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
}
