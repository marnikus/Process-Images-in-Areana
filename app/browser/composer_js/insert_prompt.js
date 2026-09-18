((promptText) => {
  try {
    const visible = (el) => {
      if (!el || el.disabled || el.closest('[aria-hidden="true"]')) return false;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        rect.width > 0 && rect.height > 0;
    };
    const selectors = [
      'textarea[name="message"]', 'textarea[placeholder*="Describe" i]',
      'textarea[rows]', '[contenteditable="true"][role="textbox"]',
    ];
    let prompt = null;
    for (const selector of selectors) {
      prompt = Array.from(document.querySelectorAll(selector)).find(visible);
      if (prompt) break;
    }
    if (!prompt) return {ok: false, error: 'visible prompt composer not found'};
    prompt.focus();
    if (prompt instanceof HTMLTextAreaElement || prompt instanceof HTMLInputElement) {
      const prototype = prompt instanceof HTMLTextAreaElement ?
        HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const previous = prompt.value;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(prompt, promptText);
      if (prompt._valueTracker) prompt._valueTracker.setValue(previous);
    } else {
      prompt.textContent = promptText;
    }
    const input = typeof InputEvent === 'function' ?
      new InputEvent('input', {bubbles: true, inputType: 'insertText', data: promptText}) :
      new Event('input', {bubbles: true});
    prompt.dispatchEvent(input);
    prompt.dispatchEvent(new Event('change', {bubbles: true}));
    const actual = 'value' in prompt ? prompt.value : prompt.textContent;
    return {ok: actual === promptText, len: actual.length, actual};
  } catch (error) {
    return {ok: false, error: String(error)};
  }
})
