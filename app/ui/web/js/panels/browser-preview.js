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
    if (img.absolute_path) {
      const i = document.createElement('img');
      i.src = 'file://' + img.absolute_path;
      i.alt = img.relative_path;
      i.onerror = () => { frame.textContent = 'Preview not available: ' + img.relative_path; };
      frame.appendChild(i);
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
