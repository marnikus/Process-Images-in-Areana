/* browser-preview.js */
'use strict';

const BrowserPreview = {
  init() {
    const clearBtn = document.getElementById('browserClearBtn');
    if (clearBtn) clearBtn.addEventListener('click', ()=>this.clear());
  },

  showImage(img) {
    const frame = document.getElementById('browserFrame');
    if (!frame) return;
    frame.innerHTML = '';
    const showImg = (src) => {
      const i = document.createElement('img');
      i.src = src;
      i.alt = img.relative_path;
      i.onerror = () => { frame.textContent = 'Preview not available: ' + img.relative_path; };
      frame.appendChild(i);
    };
    if (App.bridge && App.bridge.get_image_thumbnail) {
      // Backend data URL — file:// mangles Windows paths in WebEngine.
      frame.textContent = 'Loading preview…';
      App.bridge.get_image_thumbnail(img.id, 'preview', (res) => {
        let url = '';
        try { const r = JSON.parse(res); if (r.ok) url = r.data_url || ''; } catch (e) {}
        frame.innerHTML = '';
        if (url) showImg(url);
        else frame.textContent = 'Preview not available: ' + img.relative_path;
      });
    } else if (img.absolute_path) {
      showImg('file://' + img.absolute_path);  // standalone fallback (no bridge)
    } else {
      frame.textContent = img.relative_path;
    }
    // highlight rect if needed
    if (App.bridge && App.bridge.highlight_image) {
      App.bridge.highlight_image(img.id, ()=>{});
    }
  },

  clear() {
    const frame = document.getElementById('browserFrame');
    if (frame) frame.innerHTML = '<span>No preview</span>';
  }
};
