/* Dialog — the shared in-app modals (Qt WebEngine has no usable
  prompt()/confirm(), so the app ships its own #nameModal / #confirmModal
  markup).

  Before: the implementation lived inside PresetsUI and three other
  panels reached into another panel's guts (`PresetsUI.confirm(...)`).
  After: Dialog owns the modals; PresetsUI keeps thin delegates for
  compatibility, new code calls Dialog directly.
*/
'use strict';

window.Dialog = {
  /** Ask for a name (empty input is refused). onOk(name). */
  promptName(title, placeholder, okLabel, onOk) {
    this._openName({ title, placeholder, okLabel, initial: '' }, onOk);
  },

  /** Edit an existing value (prefilled + selected). onOk(value). */
  promptEdit(title, initial, okLabel, onOk) {
    this._openName({ title, placeholder: initial, okLabel, initial }, onOk);
  },

  _openName(opts, onOk) {
    const modal = document.getElementById('nameModal');
    const input = document.getElementById('nameModalInput');
    const ok = document.getElementById('nameModalOk');
    document.getElementById('nameModalTitle').textContent = opts.title || 'Preset name';
    input.placeholder = opts.placeholder || 'Enter a name…';
    input.value = opts.initial ? String(opts.initial) : '';
    ok.textContent = opts.okLabel || 'Save';
    modal.classList.remove('hidden');
    input.focus();
    if (opts.initial) input.select();
    this._wireName(modal, input, ok, onOk);
  },

  _wireName(modal, input, ok, onOk) {
    const cancel = document.getElementById('nameModalCancel');
    const cleanup = () => {
      modal.classList.add('hidden');
      ok.onclick = null;
      cancel.onclick = null;
      input.onkeydown = null;
    };
    ok.onclick = () => {
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      cleanup();
      onOk(name);
    };
    cancel.onclick = cleanup;
    input.onkeydown = (e) => {
      if (e.key === 'Enter') ok.click();
      else if (e.key === 'Escape') cleanup();
    };
  },

  /** Generic confirmation. onYes() runs on OK or Enter. */
  confirm(title, text, okLabel, onYes) {
    const modal = document.getElementById('confirmModal');
    const yes = document.getElementById('confirmModalYes');
    const no = document.getElementById('confirmModalNo');
    document.getElementById('confirmModalTitle').textContent = title || 'Confirm';
    document.getElementById('confirmModalText').textContent = text || '';
    yes.textContent = okLabel || 'Delete';
    modal.classList.remove('hidden');

    const cleanup = () => {
      modal.classList.add('hidden');
      yes.onclick = null;
      no.onclick = null;
      document.removeEventListener('keydown', onKey, true);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); cleanup(); }
      else if (e.key === 'Enter') { e.preventDefault(); cleanup(); onYes(); }
    };
    yes.onclick = () => { cleanup(); onYes(); };
    no.onclick = cleanup;
    document.addEventListener('keydown', onKey, true);
    yes.focus();
  },
};
