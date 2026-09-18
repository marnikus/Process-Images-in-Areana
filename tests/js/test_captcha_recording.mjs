import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {JSDOM} from 'jsdom';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname),
  '../../app/services/captcha_recording/recording_js');
const probe = (name) => fs.readFileSync(path.join(ROOT, name), 'utf8');

function page() {
  return new JSDOM('<!doctype html><html><body><main></main><input value="secret"></body></html>', {
    url: 'https://arena.ai/c/1?token=secret', runScripts: 'outside-only',
  });
}

test('recording probes capture real mutation diff and stop cleanly', async () => {
  const dom = page();
  assert.equal(dom.window.eval(probe('install.js')).ok, true);
  const node = dom.window.document.createElement('div');
  node.setAttribute('role', 'dialog');
  node.textContent = 'Security Verification';
  dom.window.document.querySelector('main').appendChild(node);
  await new Promise((resolve) => dom.window.setTimeout(resolve, 0));
  const drained = dom.window.eval(probe('drain.js'));
  assert.ok(drained.changes.some((change) => change.op === 'add'));
  assert.equal(dom.window.eval(probe('stop.js')).stopped, true);
});

test('snapshot probe strips values, queries, and opaque tokens', () => {
  const dom = page();
  const token = 'A'.repeat(100);
  dom.window.document.querySelector('main').textContent = token;
  const result = dom.window.eval(probe('snapshot.js'));
  assert.equal(result.ok, true);
  assert.equal(result.url, 'https://arena.ai/c/1');
  assert.ok(!result.html.includes('value="secret"'));
  assert.ok(!result.html.includes(token));
});

test('records UI loads two bounded evidence panes side by side', () => {
  const dom = new JSDOM('<section id="captchaCompareA"></section><section id="captchaCompareB"></section>',
    {url: 'https://app.local', runScripts: 'outside-only'});
  const scripts = path.resolve(ROOT, '../../../ui/web/js/panels');
  dom.window.LogConsole = {log() {}};
  const details = {manifest: {session_id: 's1', actor_label: 'manual', method: 'manual',
    outcome: 'manual', url: 'https://arena.ai/c/1'},
  events: [{at_ms: 3, kind: 'mutation', payload: {path: 'main'}}],
  latest_snapshot: {html: '<main>safe</main>'}};
  let opened = '';
  dom.window.CaptchaRecordingsBridge = {
    get_session(_id, callback) { callback(JSON.stringify({ok: true, details})); },
    open_folder(id, callback) { opened = id; callback(JSON.stringify({ok: true})); },
  };
  for (const name of ['captcha-recordings.js', 'captcha-recording-comparison.js']) {
    let source = fs.readFileSync(path.join(scripts, name), 'utf8');
    source = source.replace('const CaptchaRecordingsPanel =', 'globalThis.CaptchaRecordingsPanel =')
      .replace('const CaptchaRecordingComparison =', 'globalThis.CaptchaRecordingComparison =');
    dom.window.eval(source);
  }
  dom.window.CaptchaRecordingComparison.load('s1', 0);
  assert.match(dom.window.document.getElementById('captchaCompareA').textContent, /manual/);
  assert.match(dom.window.document.getElementById('captchaCompareA').textContent, /mutation/);
  assert.match(dom.window.document.getElementById('captchaCompareA').textContent, /<main>safe<\/main>/);
  dom.window.CaptchaRecordingsPanel.openButton({session_id: 's1'}).click();
  assert.equal(opened, 's1');
});
