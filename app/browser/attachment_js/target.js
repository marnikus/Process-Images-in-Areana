((marker, customSelectors) => {
  try {
    const visible = (el) => {
      if (!el || el.disabled || el.closest('[aria-hidden="true"]')) return false;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        rect.width > 0 && rect.height > 0;
    };
    const promptSelectors = [
      'textarea[name="message"]',
      'textarea[placeholder*="Describe" i]',
      'textarea[rows]',
      '[contenteditable="true"][role="textbox"]',
    ];
    let prompt = null;
    for (const selector of promptSelectors) {
      prompt = Array.from(document.querySelectorAll(selector)).find(visible);
      if (prompt) break;
    }
    if (!prompt) return {ok: false, error: 'visible prompt composer not found'};
    const form = prompt.closest('form');
    if (!form) return {ok: false, error: 'active prompt form not found'};
    const selectors = customSelectors?.length ? customSelectors : [
      'input[type="file"][accept*="image" i]', 'input[type="file"]',
    ];
    let input = null;
    for (const selector of selectors) {
      input = Array.from(form.querySelectorAll(selector)).find(
        (node) => !node.disabled && node.getAttribute('aria-disabled') !== 'true');
      if (input) break;
    }
    if (!input) return {ok: false, error: 'active composer image input not found'};
    document.querySelectorAll('[data-arena-upload-target]').forEach(
      (node) => node.removeAttribute('data-arena-upload-target'));
    input.setAttribute('data-arena-upload-target', marker);
    const previews = Array.from(form.querySelectorAll('img')).map(
      (image) => `${image.currentSrc || image.src || ''}|${image.alt || ''}`);
    return {ok: true, marker, previews, prompt: prompt.getAttribute('name') ||
      prompt.getAttribute('placeholder') || 'textarea'};
  } catch (error) {
    return {ok: false, error: String(error)};
  }
})
