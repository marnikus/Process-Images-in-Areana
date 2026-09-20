// Boundary harness: actual index markup and actual UI modules, no copied panel logic.
import fs from 'node:fs';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';

export async function controls(t) {
  const dom = new JSDOM(fs.readFileSync('app/ui/web/index.html', 'utf8'), {
    url: 'https://arena-ui.test/', runScripts: 'outside-only'
  });
  t.after(() => dom.window.close());
  const w = dom.window, calls = [], listeners = [];
  w.App = { state: {}, bridge: {
    save_settings: (raw, cb) => { calls.push(JSON.parse(raw)); cb('{"ok":true}'); },
    progress_updated: { connect: fn => listeners.push(fn) }
  } };
  for (const file of ['core/boot.js', 'core/ui-helpers.js', 'panels/url-list/store.js',
    'panels/url-list/render.js', 'panels/url-list/interval.js']) {
    vm.runInContext(fs.readFileSync('app/ui/web/js/' + file, 'utf8'), dom.getInternalVMContext(), { filename: file });
  }
  if (w.document.readyState === 'loading') {
    await new Promise(resolve => w.document.addEventListener('DOMContentLoaded', resolve, {once:true}));
  }
  w.Boot.bootPanels(['UrlInterval']);
  return {w, calls, listeners, emit: data => listeners.forEach(fn => fn(JSON.stringify(data)))};
}
