((filename, mimeType, encoded) => {
  try {
    const visible = (el) => {
      if (!el || el.disabled || el.closest('[aria-hidden="true"]')) return false;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        rect.width > 0 && rect.height > 0;
    };
    const prompts = document.querySelectorAll(
      'textarea[name="message"],textarea[placeholder*="Describe" i],textarea[rows],[contenteditable="true"][role="textbox"]');
    const prompt = Array.from(prompts).find(visible);
    const form = prompt?.closest('form');
    if (!form) return {ok: false, error: 'active prompt form not found'};
    const previews = Array.from(form.querySelectorAll('img')).map(
      (image) => `${image.currentSrc || image.src || ''}|${image.alt || ''}`);
    const binary = atob(encoded);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], filename, {type: mimeType}));
    const event = new Event('paste', {bubbles: true, cancelable: true});
    Object.defineProperty(event, 'clipboardData', {value: transfer});
    prompt.focus();
    prompt.dispatchEvent(event);
    return {ok: true, previews, dispatched: true};
  } catch (error) {
    return {ok: false, error: String(error)};
  }
})
