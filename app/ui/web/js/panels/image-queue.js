/* image-queue.js — thumbs + explorer reveal + copy path — fixed clipboard */
'use strict';

const ImageQueue = {
  _filter: 'all',
  _images: [],
  _thumbCache: {},

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
        const act = btn.dataset.action;
        if (!act) return;
        const id = btn.dataset.imgId;
        const p = btn.dataset.path; // fallback direct path
        const pathType = btn.dataset.pathType; // input / output — preferred to avoid embedding full path with backslashes
        if (act === 'retry' && id) this.retryOne(id);
        else if (act === 'reset' && id) this.resetOne(id);
        else if (act === 'exclude' && id) this.excludeOne(id);
        else if (act === 'preview' && id) this.previewOne(id);
        else if (act === 'reveal') {
          if (id && pathType) {
            const img = this._images.find(i => i.id === id);
            if (img) {
              const path = pathType === 'output' ? (img.output_path || '') : (img.absolute_path || '');
              if (path) this.revealPath(path);
              else LogConsole.log('No path to reveal for ' + id, 'warn');
            }
          } else if (p) {
            this.revealPath(p);
          }
        }
        else if (act === 'copy') {
          if (id && pathType) {
            const img = this._images.find(i => i.id === id);
            if (img) {
              const path = pathType === 'output' ? (img.output_path || '') : (img.absolute_path || '');
              if (path) this.copyPath(path);
              else LogConsole.log('No path to copy for ' + id, 'warn');
            }
          } else if (p) {
            this.copyPath(p);
          }
        }
      });
    }
  },

  restore(state) {
    if (!state || !state.images) return;
    this._images = state.images;
    this.render(state.images);
  },

  _fileUrl(pathOrUrl) {
    const raw = String(pathOrUrl == null ? '' : pathOrUrl);
    if (!raw) return '';
    if (/^(file|https?|data|blob|qrc):/i.test(raw)) return raw;
    let p = raw.replace(/\\/g, '/');
    if (/^[A-Za-z]:\//.test(p)) p = '/' + p;
    if (p.charAt(0) !== '/') p = '/' + p;
    return 'file://' + encodeURI(p).replace(/#/g, '%23').replace(/\?/g, '%3F');
  },

  _basename(p) {
    if (!p) return '';
    const s = String(p);
    const parts = s.split(/[\/\\]/);
    return parts[parts.length - 1] || s;
  },

  revealPath(path) {
    if (!path) {
      LogConsole.log('Reveal: empty path', 'warn');
      return;
    }
    if (App.bridge && App.bridge.reveal_in_explorer) {
      App.bridge.reveal_in_explorer(path, (res) => {
        try {
          const r = typeof res === 'string' ? JSON.parse(res) : res;
          if (!r.ok) {
            LogConsole.log('Reveal failed: ' + (r.error || res) + ' — ' + path, 'error');
          } else {
            LogConsole.log('📁 Opened in Explorer: ' + path, 'info');
          }
        } catch (e) {
          LogConsole.log('📁 Reveal result: ' + res, 'info');
        }
      });
    } else {
      LogConsole.log('Reveal not available (bridge missing)', 'warn');
    }
  },

  copyPath(path) {
    if (!path) {
      LogConsole.log('Copy: empty path', 'warn');
      return;
    }
    const txt = String(path);
    const fallbackTextarea = (t) => {
      try {
        const ta = document.createElement('textarea');
        ta.value = t;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, 99999);
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (ok) {
          LogConsole.log('📋 Copied (textarea): ' + t, 'success');
          return true;
        } else {
          LogConsole.log('Copy failed (textarea execCommand returned false)', 'error');
          return false;
        }
      } catch (e) {
        LogConsole.log('Copy textarea exception: ' + e + ' path: ' + t, 'error');
        return false;
      }
    };

    const tryNavigator = (t) => {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(t).then(() => {
          LogConsole.log('📋 Copied: ' + t, 'success');
        }).catch((e) => {
          LogConsole.log('Clipboard API failed: ' + e + ', trying textarea', 'warn');
          if (!fallbackTextarea(t)) {
            LogConsole.log('All copy methods failed for: ' + t, 'error');
          }
        });
      } else {
        fallbackTextarea(t);
      }
    };

    // Preferred: Qt clipboard via bridge — most reliable in QWebEngine file:// context
    if (App.bridge && App.bridge.copy_path_to_clipboard) {
      try {
        App.bridge.copy_path_to_clipboard(txt, (res) => {
          try {
            const r = typeof res === 'string' ? JSON.parse(res) : res;
            if (r.ok) {
              LogConsole.log('📋 Copied: ' + txt, 'success');
            } else {
              LogConsole.log('Bridge copy failed: ' + (r.error || res) + ', trying navigator', 'warn');
              tryNavigator(txt);
            }
          } catch (e) {
            // If bridge returns non-JSON or throws, still try to consider it success and log
            LogConsole.log('📋 Copied (bridge): ' + txt, 'success');
          }
        });
      } catch (e) {
        LogConsole.log('Bridge copy exception: ' + e + ', trying navigator', 'warn');
        tryNavigator(txt);
      }
    } else {
      LogConsole.log('Bridge copy not available, trying navigator clipboard', 'warn');
      tryNavigator(txt);
    }
  },

  _requestThumb(imgId, imgEl) {
    if (!imgId) return;
    if (this._thumbCache[imgId]) {
      const cached = this._thumbCache[imgId];
      const el = imgEl || document.querySelector(`img.queue-thumb[data-img-id="${imgId}"]`);
      if (el) {
        el.src = cached;
        el.style.display = 'block';
        if (el.nextElementSibling) el.nextElementSibling.style.display = 'none';
      }
      return;
    }
    if (App.bridge && App.bridge.get_image_thumbnail) {
      try {
        App.bridge.get_image_thumbnail(imgId, (res) => {
          try {
            const r = typeof res === 'string' ? JSON.parse(res) : res;
            if (r.ok && r.data_url) {
              this._thumbCache[imgId] = r.data_url;
              const el = imgEl || document.querySelector(`img.queue-thumb[data-img-id="${imgId}"]`);
              if (el) {
                el.src = r.data_url;
                el.style.display = 'block';
                if (el.nextElementSibling) el.nextElementSibling.style.display = 'none';
              }
            }
          } catch (e) {}
        });
      } catch (e) {}
    }
  },

  _fetchAllThumbs(images) {
    if (!App.bridge || !App.bridge.get_image_thumbnail) return;
    const list = (images || []).slice(0, 80);
    list.forEach((img, idx) => {
      if (this._thumbCache[img.id]) {
        const el = document.querySelector(`img.queue-thumb[data-img-id="${img.id}"]`);
        if (el) {
          el.src = this._thumbCache[img.id];
          el.style.display = 'block';
          if (el.nextElementSibling) el.nextElementSibling.style.display = 'none';
        }
        return;
      }
      setTimeout(() => this._requestThumb(img.id, null), idx * 60);
    });
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
      const thumbSrc = img.absolute_path ? this._fileUrl(img.absolute_path) : '';
      const thumbHtml = thumbSrc
        ? `<img class="queue-thumb" data-img-id="${img.id}" src="${thumbSrc}" alt="${this.esc(img.filename||'')}" loading="lazy" onerror="this.onerror=null; this.dataset.fileFailed='1'; if(this.nextElementSibling) this.nextElementSibling.style.display='flex'; if(typeof ImageQueue!=='undefined') ImageQueue._requestThumb(this.dataset.imgId, this);"><div class="queue-thumb queue-thumb-fallback" style="display:none; align-items:center; justify-content:center; font-size:10px;">${this.esc((img.extension||'').replace('.','').toUpperCase() || 'IMG')}</div>`
        : `<div class="queue-thumb queue-thumb-fallback" style="display:flex; align-items:center; justify-content:center; font-size:10px;">${this.esc((img.extension||'').replace('.','').toUpperCase() || 'IMG')}</div>`;

      const absPath = img.absolute_path || '';
      const relPath = img.relative_path || img.filename || '';
      const outPath = img.output_path || '';

      // Use data-img-id + data-path-type to avoid embedding full Windows path with backslashes/spaces in attribute (was causing copy failure)
      const pathCell = `
        <div style="display:flex; align-items:center; gap:4px; max-width:180px;">
          <span title="${this.esc(absPath)}" style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${this.esc(relPath)}</span>
          ${absPath ? `<button class="btn-small" title="Open in Explorer" data-action="reveal" data-img-id="${img.id}" data-path-type="input">📁</button><button class="btn-small" title="Copy path" data-action="copy" data-img-id="${img.id}" data-path-type="input">📋</button>` : ''}
        </div>`;

      let outCell = '';
      if (outPath) {
        const outBase = this._basename(outPath);
        outCell = `
          <div style="display:flex; align-items:center; gap:4px; max-width:180px;">
            <span title="${this.esc(outPath)}" style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px;">${this.esc(outBase)}</span>
            <button class="btn-small" title="Open in Explorer" data-action="reveal" data-img-id="${img.id}" data-path-type="output">📁</button>
            <button class="btn-small" title="Copy path" data-action="copy" data-img-id="${img.id}" data-path-type="output">📋</button>
          </div>`;
      } else {
        outCell = `<span style="color:var(--text-muted); font-size:11px;">—</span>`;
      }

      tr.innerHTML = `
        <td><input type="checkbox" ${img.selected ? 'checked' : ''} data-img-id="${img.id}"></td>
        <td>${thumbHtml}</td>
        <td>${pathCell}</td>
        <td><span class="status-badge s-${img.status}">${this.esc(img.status)}</span></td>
        <td style="font-size:10px;">${this.esc(img.assigned_url || '')}</td>
        <td style="font-size:10px;">${img.attempts || 0}</td>
        <td>${outCell}</td>
        <td style="font-size:10px; color:var(--red); max-width:120px; overflow:hidden; text-overflow:ellipsis;" title="${this.esc(img.error || '')}">${this.esc((img.error||'').slice(0,60))}</td>
        <td>
          <button class="btn-small" title="Preview" data-action="preview" data-img-id="${img.id}">👁</button>
          <button class="btn-small" title="Retry" data-action="retry" data-img-id="${img.id}">↻</button>
          <button class="btn-small" title="Reset" data-action="reset" data-img-id="${img.id}">Reset</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    const countEl = document.getElementById('queueCount');
    if (countEl) countEl.textContent = `${filtered.length}/${this._images.length} images`;
    this._fetchAllThumbs(filtered);
  },

  esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;'); },

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
  }
};
