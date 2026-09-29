import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { JSDOM } from 'jsdom';

const ROOT = new URL('../..', import.meta.url).pathname;
const PY = String.raw`
import json
from app.browser.dom_highlight import WatcherOverlaySpec, build_watcher_overlay_js_from_spec, build_watcher_clear_js
print(json.dumps({
  "watcher": build_watcher_overlay_js_from_spec(WatcherOverlaySpec("watcher warning", "generation", 600, "", "watcher:A")),
  "job": build_watcher_overlay_js_from_spec(WatcherOverlaySpec("job warning", "captcha", 300, "", "job:A:1")), 
  "hide_watcher": build_watcher_clear_js("watcher:A"),
  "hide_job": build_watcher_clear_js("job:A:1"),
  "hide_all": build_watcher_clear_js(),
}))
`;
const payloads = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', PY], {
  cwd: ROOT, encoding: 'utf8',
}));

function execute(dom, js) {
  return JSON.parse(dom.window.eval(js));
}

test('owner-specific hide preserves another overlay and reveals its content', () => {
  const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>', {
    runScripts: 'outside-only',
  });
  const { window } = dom;
  const showWatcher = execute(dom, payloads.watcher);
  assert.equal(showWatcher.shown, true);
  const showJob = execute(dom, payloads.job);
  assert.equal(showJob.shown, true);
  assert.equal(window.document.querySelector('[data-arena-watcher-overlay]')?.textContent.includes('JOB WARNING'), true);

  execute(dom, payloads.watcher); // duplicate show replaces that owner's lease, not another owner
  assert.equal(Object.keys(window.__arenaWatcherOverlayState.leases).length, 2);
  assert.equal(window.document.querySelectorAll('[data-arena-watcher-overlay]').length, 1);

  const hiddenJob = execute(dom, payloads.hide_job);
  assert.equal(hiddenJob.cleared, 1);
  let visible = window.document.querySelector('[data-arena-watcher-overlay]');
  assert.ok(visible);
  assert.equal(visible.textContent.includes('WATCHER WARNING'), true);

  execute(dom, payloads.job);
  assert.equal(execute(dom, payloads.hide_watcher).cleared, 1);
  visible = window.document.querySelector('[data-arena-watcher-overlay]');
  assert.ok(visible);
  assert.equal(visible.textContent.includes('JOB WARNING'), true);

  execute(dom, payloads.hide_all);
  assert.equal(Object.keys(window.__arenaWatcherOverlayState.leases).length, 0);
  assert.equal(window.document.querySelector('[data-arena-watcher-overlay]'), null);
  dom.window.close();
});
