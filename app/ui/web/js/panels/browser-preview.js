/* browser-preview.js — fixed thumb file:// handling for Windows + base64 fallback */
'use strict';

const BrowserPreview = {
  init() {
    const clearBtn = document.getElementById('browserClearBtn');
    if (clearBtn) clearBtn.addEventListener('click', ()=>this.clear());
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

  showImage(img) {
    const frame = document.getElementById('browserFrame');
    if (!frame) return;
    frame.innerHTML = '';
    if (img.absolute_path) {
      const i = document.createElement('img');
      i.src = this._fileUrl(img.absolute_path);
      i.alt = img.relative_path;
      i.style.maxWidth = '100%';
      i.style.maxHeight = '100%';
      i.style.objectFit = 'contain';
      i.onerror = () => {
        // Try base64 thumbnail via bridge
        if (App.bridge && App.bridge.get_image_thumbnail) {
          App.bridge.get_image_thumbnail(img.id, (res)=>{
            try {
              const r = typeof res === 'string' ? JSON.parse(res) : res;
              if (r.ok && r.data_url) {
                i.src = r.data_url;
                i.onerror = null;
                return;
              }
            } catch(e){}
            frame.textContent = 'Preview not available: ' + img.relative_path;
          });
        } else {
          frame.textContent = 'Preview not available: ' + img.relative_path;
        }
      };
      frame.appendChild(i);
    } else {
      frame.textContent = img.relative_path;
    }
    if (App.bridge && App.bridge.highlight_image) {
      App.bridge.highlight_image(img.id, ()=>{});
    }
  },

  clear() {
    const frame = document.getElementById('browserFrame');
    if (frame) frame.innerHTML = '<span>No preview</span>';
  }
};
