/* Captcha response-field observation probe — counts and lengths only.

   Used for the HUMAN path (the automatic path learns the same facts from
   inject.js). A person solves the widget inside the cross-origin frame, so the
   only comparable, privacy-safe evidence in the parent page is how many
   response fields exist, how many carry a value, how long that value is, and
   whether those fields live inside the open dialog. Field CONTENT never leaves
   the page (RULE 20). Output: {ok, fields, filled, max_len, in_dialog, dialogs} */
(() => {
  try {
    const SEL = 'textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"], #g-recaptcha-response';
    const fields = Array.from(document.querySelectorAll(SEL));
    let filled = 0, maxLen = 0, inDialog = 0;
    for (const f of fields) {
      const value = f.value || f.textContent || "";
      if (value) { filled++; maxLen = Math.max(maxLen, String(value).length); }
      try { if (f.closest && f.closest('div[role="dialog"]')) inDialog++; } catch (e) { /* detached */ }
    }
    return {ok: true, fields: fields.length, filled, max_len: maxLen, in_dialog: inDialog,
            dialogs: document.querySelectorAll('div[role="dialog"][data-state="open"]').length};
  } catch (e) { return {ok: false, error: String(e)}; }
})()
