/* image-queue/actions.js — bulk + single actions + clipboard, ≤200 LOC, CC≤10 */
'use strict';
window.ImageQueueActions = {
  _store() { return window.ImageQueueStore; },
  _bridge() { return window.App && window.App.bridge; },

  toggleSelect(id, selected) {
    const b = this._bridge();
    if (b && b.set_image_selected) b.set_image_selected(id, selected, ()=>{});
  },

  bulkSelect(sel) {
    const b = this._bridge();
    if (!b || !b.bulk_select) return;
    const filter = this._store().filter;
    b.bulk_select(sel, filter, (res)=>{
      try { const r=JSON.parse(res); if(r.ok) LogConsole.log((sel?'Selected ':'Deselected ')+r.count+' images','info'); } catch{}
    });
  },

  retryFailed() {
    const b = this._bridge();
    if (b && b.retry_failed) b.retry_failed((res)=>{ try{ const r=JSON.parse(res); LogConsole.log('Retry failed: '+r.count+' queued','info'); }catch{}});
  },

  _confirmKeep(keepAi) {
    if (!keepAi) return true;
    return confirm('Delete ALL non-_AI images in the picker folder (recursive)? Files are removed from disk and cannot be undone.');
  },

  _onAiResponse(res) {
    try {
      const r = JSON.parse(res);
      if (!r.ok && !r.pending) LogConsole.log('Folder _AI op: '+(r.error||'failed'),'error');
      else if (r.pending) LogConsole.log('Folder _AI op running','info');
    } catch {}
  },

  filterAi(keepAi) {
    if (!this._confirmKeep(keepAi)) return;
    const slot = keepAi ? 'keep_only_ai_files' : 'drop_ai_suffix';
    const b = this._bridge();
    if (b && b[slot]) b[slot]((res)=> this._onAiResponse(res));
  },

  resetAll() {
    if (!confirm('Reset all progress?')) return;
    const b = this._bridge();
    if (b && b.reset_all) b.reset_all(()=>LogConsole.log('All reset','warn'));
  },

  clearList() {
    if (!confirm('Clear entire list? This will remove ALL images from queue (start new batch). This cannot be undone except via Undo button.')) return;
    const b = this._bridge();
    const handle = (res)=>{ try { const r=JSON.parse(res); if (r.ok) LogConsole.log(`🗑 Cleared list: ${r.count} images removed`, 'warn'); else LogConsole.log('Clear list failed: '+(r.error||res),'error'); } catch{ LogConsole.log('Clear list done','warn'); } };
    if (b && b.clear_queue) b.clear_queue(handle);
    else if (b && b.clear_images) b.clear_images(handle);
  },

  retryOne(id){ const b=this._bridge(); if (b&&b.retry_image) b.retry_image(id, ()=>{}); },
  resetOne(id){ const b=this._bridge(); if (b&&b.reset_image) b.reset_image(id, ()=>{}); },
  excludeOne(id){ const b=this._bridge(); if (b&&b.set_image_selected) b.set_image_selected(id,false,()=>{}); },

  previewOne(id){
    const img = this._store().findById(id);
    if (!img) return;
    if (typeof BrowserPreview !== 'undefined' && BrowserPreview.showImage) BrowserPreview.showImage(img);
  },

  revealPath(path) {
    if (!path) { LogConsole.log('Reveal: empty path', 'warn'); return; }
    const b = this._bridge();
    if (!b || !b.reveal_in_explorer) { LogConsole.log('Reveal not available','warn'); return; }
    b.reveal_in_explorer(path, (res)=> this._onReveal(path, res));
  },

  _onReveal(path, res) {
    try {
      const r = typeof res === 'string' ? JSON.parse(res) : res;
      if (!r.ok) LogConsole.log('Reveal failed: '+(r.error||res)+' — '+path,'error');
      else LogConsole.log('📁 Opened in Explorer: '+path,'info');
    } catch { LogConsole.log('📁 Reveal result: '+res,'info'); }
  },

  _fallbackTextarea(t) {
    try {
      const ta=document.createElement('textarea'); ta.value=t; ta.style.position='fixed'; ta.style.left='-9999px'; document.body.appendChild(ta); ta.focus(); ta.select(); const ok=document.execCommand('copy'); document.body.removeChild(ta);
      if (ok) LogConsole.log('📋 Copied (textarea): '+t,'success');
      return ok;
    } catch(e){ LogConsole.log('Copy textarea exception: '+e,'error'); return false; }
  },

  _tryNavigator(t) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(()=>LogConsole.log('📋 Copied: '+t,'success')).catch(()=>{ LogConsole.log('Clipboard API failed, trying textarea','warn'); this._fallbackTextarea(t); });
    } else this._fallbackTextarea(t);
  },

  _onBridgeCopy(txt, res) {
    try {
      const r = typeof res === 'string' ? JSON.parse(res) : res;
      if (r.ok) LogConsole.log('📋 Copied: '+txt,'success');
      else { LogConsole.log('Bridge copy failed, trying navigator','warn'); this._tryNavigator(txt); }
    } catch { LogConsole.log('📋 Copied (bridge): '+txt,'success'); }
  },

  copyPath(path) {
    if (!path) { LogConsole.log('Copy: empty path','warn'); return; }
    const txt = String(path);
    const b = this._bridge();
    if (!b || !b.copy_path_to_clipboard) { LogConsole.log('Bridge copy not available, trying navigator','warn'); this._tryNavigator(txt); return; }
    try {
      b.copy_path_to_clipboard(txt, (res)=> this._onBridgeCopy(txt, res));
    } catch { LogConsole.log('Bridge copy exception, trying navigator','warn'); this._tryNavigator(txt); }
  },
};
