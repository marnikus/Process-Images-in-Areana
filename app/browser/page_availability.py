"""Read-only admission probe for workers; no UI imports or browser mutations.

Hidden file inputs are normal. Missing/broken observations never mean steady.
"""

# ideal-size: leaf module keeps the single admission DOM contract together.
PAGE_AVAILABILITY_JS = """
;(() => {
  const visible = el => !!el && el.offsetParent !== null;
  const anyVisible = selector => Array.from(document.querySelectorAll(selector)).some(visible);
  const dialogs = Array.from(document.querySelectorAll('div[role="dialog"][data-state="open"]'));
  if (anyVisible('iframe[title="reCAPTCHA"]') || dialogs.some(d =>
      visible(d) && /Security Verification/i.test(d.innerText || '')))
    return {status: 'waiting_captcha'};
  if (anyVisible('div.animate-spin, [role="progressbar"], [aria-busy="true"], button[aria-label*="Stop"], button[aria-label*="stop"]'))
    return {status: 'busy'};
  const outputs = Array.from(document.querySelectorAll('div.no-scrollbar img'));
  if (outputs.some(img => visible(img) && !img.complete)) return {status: 'busy'};
  const prompt = document.querySelector('textarea[name="message"]');
  const send = document.querySelector('button[aria-label="Send message"]');
  const file = document.querySelector('input[type="file"]');
  if (!visible(prompt) || prompt.disabled || !visible(send) || !file)
    return {status: 'not_ready'};
  // Send is often disabled until a prompt is entered; that alone is not busy.
  return {status: 'steady'};
})()
"""


async def observe_availability(controller):
    """Validate the CDP result instead of treating falsy/error as idle."""
    result = await controller.cdp.evaluate(PAGE_AVAILABILITY_JS)
    if not isinstance(result, dict):
        raise RuntimeError('Page availability probe returned no valid result')
    status = result.get('status')
    if status not in {'steady', 'busy', 'waiting_captcha', 'not_ready'}:
        raise RuntimeError(f'Invalid page availability result: {result!r}')
    return status
