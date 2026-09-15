/* image-queue.js */
'use strict';

const ImageQueue = {
  _filter: 'all',
  _images: [],
  _thumbCache: {},
  _thumbLoading: {},

  init() {
    const filterSel = document.getElementById('queueFilter');
    if (filterSel) filterSel.addEventListener('change', (e) => {
      this._filter = e.target.value;
      this.render(this._images);
    });

    document.getElementById('queueSelectAllBtn')?.addEventListener('click', () => this.bulkSelect(true));
    document.getElementById('queueDeselectAllBtn')?.addEventListener('click', () => this.bulkSelect(false));
    document.getElementById('queueRetryFailedBtn')?.addEventListener('click', () => this.retryFailed());
    document.getElementById('queueResetBtn')?.addEventListener('click', () => this.resetAll());
    document.getElementById('queueClearListBtn')?.addEventListener('click', () => this.clearList());

    const tbody = document.getElementById('queueTableBody');
    if (tbody) {
      tbody.addEventListener('click', (e) => {
        const cb = e.target.closest('input[type=checkbox]');
        if (cb && cb.dataset.imgId) {
          this.toggleSelect(cb.dataset.imgId, cb.checked);
          return;
        }
        const btn = e.target.closest('button');
        if (!btn) return;
        const id = btn.dataset.imgId;
        const act = btn.dataset.action;
        if (!id || !act) return;
        if (act === 'retry') this.retryOne(id);
        if (act === 'reset') this.resetOne(id);
        if (act === 'exclude') this.excludeOne(id);
        if (act === 'preview') this.previewOne(id);
        if (act === 'reveal') this.revealOne(id);
      });
    }
  },

  restore(state) {
    if (!state || !state.images) return;
    this._images = state.images;
    this.render(state.images);
  },

  render(images) {
    this._images = images || this._images;
    const tbody = document.getElementById('queueTableBody');
    if (!tbody) return;
    const filter = this._filter;
    let filtered = this._images;
    if (filter !== 'all') filtered = this._images.filter(i => i.status === filter);

    tbody.innerHTML = '';
    filtered.forEach(img => {
      const tr = document.createElement('tr');
      const cached = this._thumbCache[img.id];
      const thumbCell = cached
        ? `<img class="queue-thumb" src="${cached}" alt="">`
        : `<img class="queue-thumb" data-thumb-for="${this.esc(img.id)}" alt="">`;
      tr.innerHTML = `
        <td><input type="checkbox" ${img.selected ? 'checked' : ''} data-img-id="${img.id}"></td>
        <td>${thumbCell}</td>
        <td title="${this.esc(img.relative_path)}" style="max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${this.esc(img.relative_path)}</td>
        <td><span class="status-badge s-${img.status}">${this.esc(img.status)}</span></td>
        <td style="font-size:10px;">${this.esc(img.assigned_url || '')}</td>
        <td style="font-size:10px;">${img.attempts || 0}</td>
        <td style="font-size:10px; max-width:120px; overflow:hidden; text-overflow:ellipsis;">${this.esc(img.output_path || '')}</td>
        <td style="font-size:10px; color:var(--red); max-width:120px; overflow:hidden; text-overflow:ellipsis;" title="${this.esc(img.error || '')}">${this.esc((img.error||'').slice(0,60))}</td>
        <td>
          <button class="btn-small" data-action="preview" data-img-id="${img.id}" title="Preview">👁</button>
          <button class="btn-small" data-action="reveal" data-img-id="${img.id}" title="Open in Explorer">📁</button>
          <button class="btn-small" data-action="retry" data-img-id="${img.id}">↻</button>
          <button class="btn-small" data-action="reset" data-img-id="${img.id}">Reset</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    const countEl = document.getElementById('queueCount');
    if (countEl) countEl.textContent = `${filtered.length}/${this._images.length} images`;
    this._loadThumbs();
  },

  _loadThumbs() {
    // Lazy-load each visible thumb once via backend data URLs (file:// is
    // unusable in WebEngine, esp. with Windows paths). Failures keep the
    // CSS placeholder square.
    if (!App.bridge || !App.bridge.get_image_thumbnail) return;
    const tbody = document.getElementById('queueTableBody');
    if (!tbody) return;
    tbody.querySelectorAll('img[data-thumb-for]').forEach(el => {
      const id = el.getAttribute('data-thumb-for');
      if (!id || this._thumbCache[id] || this._thumbLoading[id]) return;
      this._thumbLoading[id] = true;
      try {
        App.bridge.get_image_thumbnail(id, 'thumb', (res) => {
          delete this._thumbLoading[id];
          let url = '';
          try { const r = JSON.parse(res); if (r.ok) url = r.data_url || ''; } catch (e) {}
          // Row may have re-rendered while loading — look the cell up fresh.
          const fresh = tbody.querySelector(`img[data-thumb-for="${id}"]`);
          if (!fresh) return;
          if (url) {
            this._thumbCache[id] = url;
            fresh.src = url;
            fresh.removeAttribute('data-thumb-for');
          } else {
            const ph = document.createElement('div');
            ph.className = 'queue-thumb';
            fresh.replaceWith(ph);
          }
        });
      } catch (e) {
        delete this._thumbLoading[id];
      }
    });
  },

  esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); },

  toggleSelect(id, selected) {
    if (App.bridge && App.bridge.set_image_selected) {
      App.bridge.set_image_selected(id, selected, ()=>{});
    }
  },

  bulkSelect(sel) {
    if (App.bridge && App.bridge.bulk_select) {
      App.bridge.bulk_select(sel, this._filter, (res)=>{
        try { const r=JSON.parse(res); if(r.ok) LogConsole.log((sel?'Selected ':'Deselected ')+r.count+' images','info'); } catch(e){}
      });
    }
  },

  retryFailed() {
    if (App.bridge && App.bridge.retry_failed) {
      App.bridge.retry_failed((res)=>{
        try{ const r=JSON.parse(res); LogConsole.log('Retry failed: '+r.count+' queued','info'); }catch(e){}
      });
    }
  },

  resetAll() {
    if (!confirm('Reset all progress?')) return;
    if (App.bridge && App.bridge.reset_all) App.bridge.reset_all(()=>LogConsole.log('All reset','warn'));
  },

  clearList() {
    if (!confirm('Clear entire list? This will remove ALL images from queue (start new batch). This cannot be undone except via Undo button.')) return;
    if (App.bridge && App.bridge.clear_queue) {
      App.bridge.clear_queue((res)=>{
        try {
          const r = JSON.parse(res);
          if (r.ok) LogConsole.log(`🗑 Cleared list: ${r.count} images removed — ready for new batch`, 'warn');
          else LogConsole.log('Clear list failed: '+(r.error||res),'error');
        } catch(e){
          LogConsole.log('Clear list done','warn');
        }
      });
    } else if (App.bridge && App.bridge.clear_images) {
      App.bridge.clear_images((res)=>{
        try {
          const r = JSON.parse(res);
          if (r.ok) LogConsole.log(`🗑 Cleared list: ${r.count} images removed — ready for new batch`, 'warn');
        } catch(e){}
      });
    }
  },

  retryOne(id){ if (App.bridge && App.bridge.retry_image) App.bridge.retry_image(id, ()=>{}); },
  resetOne(id){ if (App.bridge && App.bridge.reset_image) App.bridge.reset_image(id, ()=>{}); },
  excludeOne(id){ if (App.bridge && App.bridge.set_image_selected) App.bridge.set_image_selected(id,false,()=>{}); },
  previewOne(id){
    const img = this._images.find(i=>i.id===id);
    if (!img) return;
    if (typeof BrowserPreview !== 'undefined' && BrowserPreview.showImage) BrowserPreview.showImage(img);
  },

  revealOne(id){
    if (App.bridge && App.bridge.open_in_explorer) {
      App.bridge.open_in_explorer(id, (res)=>{
        try {
          const r = JSON.parse(res);
          if (!r.ok) LogConsole.log('Open in Explorer failed: '+(r.error||res),'error');
        } catch(e){
          LogConsole.log('Open in Explorer failed: '+res,'error');
        }
      });
    } else {
      LogConsole.log('Open in Explorer unavailable (no bridge)','warn');
    }
  },
};
