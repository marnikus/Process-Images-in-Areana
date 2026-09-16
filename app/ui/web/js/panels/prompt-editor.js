/* prompt-editor.js */
'use strict';

const PromptEditor = {
  init() {
    const ta = document.getElementById('promptTextarea');
    const saveBtn = document.getElementById('promptSaveBtn');
    if (!ta) return;
    ta.addEventListener('input', () => this.updatePreview());
    if (saveBtn) saveBtn.addEventListener('click', () => this.save());
    this.updatePreview();
  },

  restore(state) {
    if (!state || !state.prompt) return;
    const ta = document.getElementById('promptTextarea');
    if (ta && state.prompt.template) ta.value = state.prompt.template;
    this.updatePreview();
  },

  updatePreview() {
    const ta = document.getElementById('promptTextarea');
    const preview = document.getElementById('promptPreview');
    if (!ta || !preview) return;
    const template = ta.value;
    const jobId = 'JOB-' + Math.random().toString(36).slice(2,8).toUpperCase() + '-' + Date.now().toString(36);
    const withToken = template + '\n\n[JOB-ID: ' + jobId + ']';
    preview.innerHTML = this.esc(withToken).replace(/\[JOB-ID: [^\]]+\]/g, (m) => `<span class="token-highlight">${this.esc(m)}</span>`);
  },

  esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/\n/g,'<br>'); },

  save() {
    const ta = document.getElementById('promptTextarea');
    if (!ta) return;
    const val = ta.value;
    // record undo before save (local mirror)
    if (typeof ArenaHistory !== 'undefined') ArenaHistory.recordGlobal('prompt', val);
    if (App.bridge && App.bridge.set_prompt) {
      App.bridge.set_prompt(val, (res)=>{
        try{ const r=JSON.parse(res); if(r.ok) LogConsole.log('Prompt saved','success'); else LogConsole.log('Save failed: '+r.error,'error'); }catch(e){}
      });
    }
  }
};
