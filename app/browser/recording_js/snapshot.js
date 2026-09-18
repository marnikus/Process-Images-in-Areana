/* Recording snapshot probe — full serialized DOM with recaptcha response
   field contents redacted IN THE PAGE, before the bytes cross CDP. The
   token never reaches the app process (RULE 20 key hygiene, same standard
   as the 2Captcha key). Length-capped so one snapshot cannot explode the
   WebSocket message. */
(() => {
  try {
    const clone = document.documentElement.cloneNode(true);
    const SEL = 'textarea[name="g-recaptcha-response"], input[name="g-recaptcha-response"],'
      + ' textarea[id*="g-recaptcha-response"], input[id*="g-recaptcha-response"]';
    let redacted = 0;
    clone.querySelectorAll(SEL).forEach((el) => {
      const len = String(el.value || el.textContent || "").length;
      if (el.tagName === "TEXTAREA") { el.textContent = "[REDACTED:len=" + len + "]"; }
      else { el.setAttribute("value", "[REDACTED:len=" + len + "]"); }
      redacted++;
    });
    const html = "<!DOCTYPE html>\n" + clone.outerHTML;
    return {ok: true, redacted, length: html.length,
            html: html.slice(0, 2000000)};
  } catch (e) {
    return {ok: false, error: String(e).slice(0, 120)};
  }
})()
