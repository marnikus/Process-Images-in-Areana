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

const PANELS = path.resolve(ROOT, '../../../ui/web/js/panels');

function loadPanelScripts(dom) {
  for (const name of ['captcha-recordings.js', 'captcha-recording-comparison.js']) {
    let source = fs.readFileSync(path.join(PANELS, name), 'utf8');
    source = source.replace('const CaptchaRecordingsPanel =', 'globalThis.CaptchaRecordingsPanel =')
      .replace('const CaptchaRecordingComparison =', 'globalThis.CaptchaRecordingComparison =');
    dom.window.eval(source);
  }
}

// Fixture shaped like the PERSISTED schema (recorder.py::_event / _checkpoint):
// flat event fields with offset_ms, snapshot with ISO at. If the viewer contract
// drifts from this schema, the assertions below fail (RULE 8).
const persistedDetails = {manifest: {session_id: 's1', actor_label: 'manual', method: 'manual',
  outcome: 'manual', url: 'https://arena.ai/c/1', started_at: '2026-09-18T10:00:00Z'},
events: [{seq: 0, at: '2026-09-18T10:00:00.012Z', offset_ms: 12, kind: 'network_response',
          request_id: 'r1', status: 200, url: 'https://www.google.com/recaptcha/api2/anchor'}],
latest_snapshot: {at: '2026-09-18T10:00:05Z', html: '<main>safe</main>', truncated_for_view: false}};

test('records UI renders the persisted event and snapshot schema', () => {
  const dom = new JSDOM('<section id="captchaCompareA"></section><section id="captchaCompareB"></section>',
    {url: 'https://app.local', runScripts: 'outside-only'});
  dom.window.LogConsole = {log() {}};
  let opened = '';
  dom.window.CaptchaRecordingsBridge = {
    get_session(_id, callback) { callback(JSON.stringify({ok: true, details: persistedDetails})); },
    open_folder(id, callback) { opened = id; callback(JSON.stringify({ok: true})); },
  };
  loadPanelScripts(dom);
  dom.window.CaptchaRecordingComparison.load('s1', 0);
  const text = dom.window.document.getElementById('captchaCompareA').textContent;
  assert.match(text, /manual/);
  assert.match(text, /12ms/);            // offset_ms rendered (was 0ms with the old contract)
  assert.match(text, /network_response/);
  assert.match(text, /recaptcha\/api2\/anchor/);  // event detail fields rendered (was empty)
  assert.match(text, /<main>safe<\/main>/);
  assert.match(text, /checkpoint/i);      // snapshot timestamp from persisted at
  dom.window.CaptchaRecordingsPanel.openButton({session_id: 's1'}).click();
  assert.equal(opened, 's1');
});

test('records UI lists all retained sessions and deletes with confirmation', () => {
  const dom = new JSDOM(
    '<div id="captchaRecordsSummary"></div><div id="captchaRecordsEmpty" style="display:none"></div>' +
    '<table><tbody id="captchaRecordsBody"></tbody></table>',
    {url: 'https://app.local', runScripts: 'outside-only'});
  dom.window.LogConsole = {log() {}};
  dom.window.confirm = () => true;
  const rows = [{session_id: 's1', actor_label: 'bot', method: 'auto', outcome: 'solved',
    url: 'https://arena.ai/c/1', started_at: '2026-09-18T10:00:00Z', elapsed_ms: 5000,
    mutation_count: 1, network_count: 2, snapshot_count: 1}];
  let listed = 0;
  let deleted = '';
  dom.window.CaptchaRecordingsBridge = {
    list_sessions(limit, callback) { listed += 1;
      callback(JSON.stringify({ok: true, sessions: rows, total: 2, limit})); },
    set_label(id, label, callback) { callback(JSON.stringify({ok: true, session: {session_id: id}})); },
    delete_session(id, callback) { deleted = id;
      callback(JSON.stringify({ok: true, session: {session_id: id, deleted: true}})); },
  };
  loadPanelScripts(dom);
  dom.window.CaptchaRecordingsPanel.load();
  assert.equal(listed, 1);
  assert.match(dom.window.document.getElementById('captchaRecordsSummary').textContent,
    /showing last 1 of 2 local sessions/);
  const deleteButton = dom.window.document.querySelector('#captchaRecordsBody button[title*="Delete"]');
  assert.ok(deleteButton, 'row carries a delete button');
  deleteButton.click();
  assert.equal(deleted, 's1');
  assert.equal(listed, 2, 'list refreshes after delete');
});
