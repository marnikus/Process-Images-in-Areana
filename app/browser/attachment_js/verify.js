((expectedFilename, baseline) => {
  try {
    const visible = (el) => {
      if (!el || el.closest('[aria-hidden="true"]')) return false;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        rect.width > 0 && rect.height > 0;
    };
    const prompts = document.querySelectorAll(
      'textarea[name="message"],textarea[placeholder*="Describe" i],textarea[rows],[contenteditable="true"][role="textbox"]');
    const prompt = Array.from(prompts).find(visible);
    const form = prompt?.closest('form');
    if (!form) return {found: false, error: 'active prompt form not found'};
    const input = form.querySelector('input[type="file"]');
    const names = input ? Array.from(input.files || []).map((file) => file.name) : [];
    if (names.includes(expectedFilename)) {
      return {found: true, matched: 'active-input-file', filename: expectedFilename};
    }
    const before = new Set(Array.isArray(baseline) ? baseline : []);
    const images = Array.from(form.querySelectorAll('img')).filter(visible);
    const fresh = images.find((image) => {
      const key = `${image.currentSrc || image.src || ''}|${image.alt || ''}`;
      return !before.has(key);
    });
    if (!fresh) return {found: false, inputNames: names, previewCount: images.length};
    return {found: true, matched: 'new-active-preview', alt: fresh.alt || ''};
  } catch (error) {
    return {found: false, error: String(error)};
  }
})
