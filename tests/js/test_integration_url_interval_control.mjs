// Integration lane: actual DOM, boot/bridge or cross-file contracts.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { controls } from './live_controls_harness.mjs';

test('save clamps and calls the real save_settings bridge boundary', async t => {
  const h = await controls(t), el = h.w.document.getElementById('urlIntervalMs');
  for (const [raw, expected] of [['1',500], ['70000',60000], ['2500',2500], ['',5000]]) {
    el.value = raw;
    h.w.document.getElementById('urlIntervalSaveBtn').click();
    assert.deepEqual(h.calls.at(-1), {url_reconcile_interval_ms:expected});
    assert.equal(el.value, String(expected));
  }
  assert.equal(h.calls.length, 4);
});

test('pushed cadence populates the real input without saving', async t => {
  const h = await controls(t);
  h.emit({live:{url_interval_ms:9000}});
  assert.equal(h.w.document.getElementById('urlIntervalMs').value, '9000');
  h.emit({live:{url_interval_ms:'garbage'}});
  assert.equal(h.w.document.getElementById('urlIntervalMs').value, '5000');
  h.emit({live:{}});
  assert.equal(h.w.document.getElementById('urlIntervalMs').value, '5000');
  assert.equal(h.calls.length, 0);
});

test('published panel boots and binds one click even if Boot repeats', async t => {
  const h = await controls(t);
  assert.equal(typeof h.w.UrlInterval.init, 'function');
  h.w.Boot.bootPanels(['UrlInterval']);
  h.w.document.getElementById('urlIntervalSaveBtn').click();
  assert.equal(h.calls.length, 1);
  assert.equal(h.listeners.length, 1);
});

test('the frozen url list files did not grow across the entire chain', () => {
  const paths = ['panels/settings.js', 'panels/url-list.js', ...['listeners', 'cooldown', 'actions', 'store', 'matching'].map(n => `panels/url-list/${n}.js`)];
  for (const p of paths) {
    const full = 'app/ui/web/js/' + p;
    const base = execFileSync('git', ['show', `2bbf9ab:${full}`], {encoding:'utf8'});
    assert.equal(fs.readFileSync(full,'utf8'), base, full + ' must remain byte-identical');
  }
  const cdp = fs.readFileSync('app/ui/web/js/panels/cdp.js', 'utf8');
  assert.doesNotMatch(cdp, /setInterval\([^\n]*autoConnectScan/);
});
