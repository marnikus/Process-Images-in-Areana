/* image-queue/render.js — row render, ≤200 LOC CC≤10 */
'use strict';
window.ImageQueueRender = {
  _store() { return window.ImageQueueStore; },
  _thumbs() { return window.ImageQueueThumbs; },

  thumbHtml(img) {
    const s = this._store();
    const src = img.absolute_path ? s.fileUrl(img.absolute_path) : '';
    if (!src) {
      return `<div class="queue-thumb queue-thumb-fallback" style="display:flex; align-items:center; justify-content:center; font-size:10px;">${s.esc((img.extension||'').replace('.','').toUpperCase() || 'IMG')}</div>`;
    }
    return `<img class="queue-thumb" data-img-id="${img.id}" src="${src}" alt="${s.esc(img.filename||'')}" loading="lazy" onerror="this.onerror=null; this.dataset.fileFailed='1'; if(this.nextElementSibling) this.nextElementSibling.style.display='flex'; if(typeof ImageQueue!=='undefined') ImageQueue._requestThumb(this.dataset.imgId, this);"><div class="queue-thumb queue-thumb-fallback" style="display:none; align-items:center; justify-content:center; font-size:10px;">${s.esc((img.extension||'').replace('.','').toUpperCase() || 'IMG')}</div>`;
  },

  pathCell(img) {
    const s = this._store();
    const absPath = img.absolute_path || '';
    const relPath = img.relative_path || img.filename || '';
    if (!absPath) return `<span>${s.esc(relPath)}</span>`;
    return `<div style="display:flex; align-items:center; gap:4px; max-width:180px;"><span title="${s.esc(absPath)}" style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${s.esc(relPath)}</span><button class="btn-small" title="Open in Explorer" data-action="reveal" data-img-id="${img.id}" data-path-type="input">📁</button><button class="btn-small" title="Copy path" data-action="copy" data-img-id="${img.id}" data-path-type="input">📋</button></div>`;
  },

  outCell(img) {
    const s = this._store();
    const outPath = img.output_path || '';
    if (!outPath) return `<span style="color:var(--text-muted); font-size:11px;">—</span>`;
    const outBase = s.basename(outPath);
    return `<div style="display:flex; align-items:center; gap:4px; max-width:180px;"><span title="${s.esc(outPath)}" style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px;">${s.esc(outBase)}</span><button class="btn-small" title="Open in Explorer" data-action="reveal" data-img-id="${img.id}" data-path-type="output">📁</button><button class="btn-small" title="Copy path" data-action="copy" data-img-id="${img.id}" data-path-type="output">📋</button></div>`;
  },

  rowHtml(img) {
    const s = this._store();
    return `<td><input type="checkbox" ${img.selected ? 'checked' : ''} data-img-id="${img.id}"></td><td>${this.thumbHtml(img)}</td><td>${this.pathCell(img)}</td><td><span class="status-badge s-${img.status}">${s.esc(img.status)}</span></td><td style="font-size:10px;">${s.esc(img.assigned_url || '')}</td><td style="font-size:10px;">${img.attempts || 0}</td><td>${this.outCell(img)}</td><td style="font-size:10px; color:var(--red); max-width:120px; overflow:hidden; text-overflow:ellipsis;" title="${s.esc(img.error || '')}">${s.esc((img.error||'').slice(0,60))}</td><td><button class="btn-small" title="Preview" data-action="preview" data-img-id="${img.id}">👁</button><button class="btn-small" title="Retry" data-action="retry" data-img-id="${img.id}">↻</button><button class="btn-small" title="Reset" data-action="reset" data-img-id="${img.id}">Reset</button></td>`;
  },

  render(images) {
    const s = this._store();
    if (images) s.images = images;
    const tbody = document.getElementById('queueTableBody');
    if (!tbody) return;
    const filtered = s.filtered();
    tbody.innerHTML = '';
    filtered.forEach(img => {
      const tr = document.createElement('tr');
      tr.dataset.imgId = img.id;
      tr.innerHTML = this.rowHtml(img);
      tbody.appendChild(tr);
    });
    const countEl = document.getElementById('queueCount');
    if (countEl) countEl.textContent = `${filtered.length}/${s.images.length} images`;
    this._thumbs().fetchAll(filtered);
  },

  _rowFor(imgId) {
    const tbody = document.getElementById('queueTableBody');
    if (!tbody) return null;
    const rows = tbody.children || [];
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].dataset && rows[i].dataset.imgId === imgId) return rows[i];
    }
    return null;
  },

  /* B10: re-render ONE row in place (job_started / job_finished). Falls back to
     a full render when the row is not on screen or a status filter is active
     (the row may need to enter/leave the filtered view). */
  updateRow(img) {
    if (!img) return false;
    const s = this._store();
    const tr = s.filter === 'all' ? this._rowFor(img.id) : null;
    if (!tr) { this.render(); return true; }
    tr.innerHTML = this.rowHtml(img);
    this._thumbs().fetchAll([img]);
    return true;
  },
};
