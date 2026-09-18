((expected) => {
  try {
    const visible = (el) => {
      if (!el || el.disabled || el.closest('[aria-hidden="true"]')) return false;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        rect.width > 0 && rect.height > 0;
    };
    const selector = 'textarea[name="message"],textarea[placeholder*="Describe" i],textarea[rows],[contenteditable="true"][role="textbox"]';
    const prompt = Array.from(document.querySelectorAll(selector)).find(visible);
    if (!prompt) return {ok: false, error: 'visible prompt composer not found'};
    const actual = 'value' in prompt ? prompt.value : prompt.textContent;
    return {ok: actual === expected, actual, len: actual.length};
  } catch (error) {
    return {ok: false, error: String(error)};
  }
})
