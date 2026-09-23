/**
 * The Settings browser block after the debugger-approach removal (2026-09-22).
 *
 * Chrome is the one registered browser; Firefox automation moved to its own
 * window ("Firefox auto with Extension", Ui.Vision + native OS input). The
 * block stays data-driven — the browser table lives in Python
 * (`app/browser/browsers.py`) and the panel renders whatever the bridge sends
 * (`browsers` in the `get_cdp_config` payload) — so a future registry row
 * needs no JS change. The removed Firefox vocabulary (prefs, stealth,
 * Prepare Profile) must not survive in the page or the module.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { bootPage } from './page_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf-8');
const moduleSrc = fs.readFileSync(path.join(WEB, 'js/panels/browser-connection.js'), 'utf-8');

const CONFIG = {
  host: '127.0.0.1',
  port: 9223,
  url_pattern: 'arena.ai',
  active_browser: 'chrome',
  scan_line: 'Scanning: chrome 127.0.0.1:9223 (CDP)',
  browsers: [
    { id: 'chrome', label: 'Chrome (Chromium)', protocol: 'cdp', port_offset: 0, resolved_port: 9223,
      user_data_dir: 'C:\\arena-images-chrome', extra_args: '--disable-extensions',
      dir_flag: '--user-data-dir', binary: '"C:\\chrome.exe"', notes: 'Full automation (CDP).',
      capabilities: ['dom', 'evaluate', 'input', 'navigate', 'screenshot', 'set_files', 'tabs'], unavailable: [],
      test_url: 'http://127.0.0.1:9223/json/list',
      commands: { windows: '"C:\\chrome.exe" --remote-debugging-port=9223 --user-data-dir="C:\\arena-images-chrome"',
                  windows_with_url: 'chrome-url', linux: 'google-chrome', macos: 'mac-chrome' } },
  ],
};

const val = (h, id) => String(h.anyEl(id).value);
const txt = (h, id) => String(h.anyEl(id).textContent);

/** Boot the whole page with the bridge answering the browser payload. */
function boot(overrides = {}) {
  const h = bootPage({
    replies: {
      get_cdp_config: CONFIG,
      get_chrome_launch_command: { browser: 'chrome', windows: CONFIG.browsers[0].commands.windows },
      get_app_state: {},
      ...overrides,
    },
  });
  h.flushTimers();            // SettingsPanel.loadCDPConfig runs on a 1000 ms timer
  return h;
}

describe('browser debug connection panel (Chrome only)', () => {
  test('index.html mounts the shared + per-browser fields and dropped the Firefox block', () => {
    const start = html.indexOf('Browser Debug Connection');
    assert.ok(start > 0, 'the block is called "Browser Debug Connection"');
    assert.ok(!html.includes('Chrome / Firefox'), 'the multi-browser title is gone');
    const block = html.slice(start, html.indexOf('Page Load Timeout', start));
    for (const id of ['browserSelect', 'cdpHost', 'cdpPort', 'cdpUrlPattern', 'cdpUserDataDir', 'cdpExtraArgs',
                      'cdpResolvedPort', 'cdpLaunchCmd', 'cdpCopyCmdBtn', 'cdpTestUrl', 'cdpCapabilities',
                      'cdpBrowserNotes', 'cdpSaveBtn', 'cdpTestBtn', 'cdpScanLine']) {
      assert.ok(block.includes(`id="${id}"`), `${id} is inside the browser block`);
    }
    for (const gone of ['cdpPrefs', 'cdpPrefsFile', 'cdpStealth', 'cdpPrepareProfileBtn']) {
      assert.ok(!html.includes(`id="${gone}"`), `${gone} went with the debugger approach`);
    }
    assert.ok(!html.includes('--start-debugger-server'), 'no Firefox debugger flag anywhere in the page');
    assert.equal((html.match(/id="cdpUrlPattern"/g) || []).length, 1, 'one URL pattern control');
    assert.ok(html.indexOf('js/panels/browser-connection.js') < html.indexOf('js/panels/settings.js'),
      'the browser module loads before settings.js (which delegates to it)');
  });

  test('the removed Firefox machinery is gone from the module too', () => {
    for (const gone of ['prefsText', 'prepareProfile', 'onPrepared', 'start-debugger-server', 'user_pref']) {
      assert.ok(!moduleSrc.includes(gone), `${gone} must not survive in browser-connection.js`);
    }
    assert.equal((moduleSrc.match(/id: 'firefox'/g) || []).length, 0, 'the fallback list is chrome-only');
  });

  test('the payload drives the selector: one chrome option and the shared fields', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    assert.deepEqual(sel.children.map((o) => o.value), ['chrome']);
    assert.deepEqual(sel.children.map((o) => o.textContent), ['Chrome (Chromium)']);
    assert.equal(sel.value, 'chrome');
    assert.equal(val(h, 'cdpHost'), '127.0.0.1');
    assert.equal(val(h, 'cdpPort'), '9223', 'the shared field shows the BASE port');
    assert.equal(val(h, 'cdpUrlPattern'), 'arena.ai');
    assert.equal(val(h, 'cdpUserDataDir'), 'C:\\arena-images-chrome');
    assert.equal(txt(h, 'cdpResolvedPort'), '9223', 'Chrome derives base + 0');
    assert.equal(txt(h, 'cdpScanLine'), CONFIG.scan_line, 'the Python-built scan line is shown as-is');
    assert.ok(txt(h, 'cdpLaunchCmd').includes('chrome.exe'));
    assert.ok(txt(h, 'cdpTestUrl').endsWith('/json/list'));
  });

  test('the capability line names what the endpoint can do', () => {
    const h = boot();
    const caps = txt(h, 'cdpCapabilities');
    assert.ok(caps.includes('✅'), `capabilities shown: ${caps}`);
    for (const op of ['screenshot', 'set_files', 'input']) assert.ok(caps.includes(op), caps);
    assert.ok(!caps.includes('⛔'), 'chrome has no named gaps');
    assert.ok(txt(h, 'cdpBrowserNotes').includes('--user-data-dir'), 'the note carries the dir flag');
  });

  test('one Save posts the active browser plus its block', () => {
    const h = boot();
    h.anyEl('cdpSaveBtn').dispatch('click', {});
    const saves = h.calls.filter((c) => c.slot === 'set_cdp_config');
    assert.equal(saves.length, 1, 'one Save click, one save');
    const payload = JSON.parse(saves[0].args[0]);
    assert.equal(payload.browser, 'chrome');
    assert.equal(payload.host, '127.0.0.1');
    assert.equal(payload.port, 9223);
    assert.equal(payload.user_data_dir, 'C:\\arena-images-chrome');
    assert.equal(payload.url_pattern, 'arena.ai');
    assert.equal(payload.browsers.chrome.port, 9223);
    assert.equal(payload.browsers.chrome.user_data_dir, 'C:\\arena-images-chrome');
    assert.equal(payload.prepare_profile, undefined, 'Save never asks for a profile write');
  });

  test('an edited dir travels in the save payload', () => {
    const h = boot();
    h.anyEl('cdpUserDataDir').value = 'D:\\chrome-profile';
    h.anyEl('cdpSaveBtn').dispatch('click', {});
    const payload = JSON.parse(h.calls.filter((c) => c.slot === 'set_cdp_config').pop().args[0]);
    assert.equal(payload.user_data_dir, 'D:\\chrome-profile');
    assert.equal(payload.browsers.chrome.user_data_dir, 'D:\\chrome-profile');
  });

  test('the bridge payload is the source of truth for the registry', () => {
    const h = boot({ get_cdp_config: { host: '10.0.0.5', port: 9500, url_pattern: 'arena.ai', active_browser: 'edge',
      browsers: [{ id: 'edge', label: 'Edge (Chromium)', protocol: 'cdp', port_offset: 2, resolved_port: 9502,
                   user_data_dir: 'C:\\arena-images-edge', extra_args: '', dir_flag: '--user-data-dir',
                   binary: '"C:\\msedge.exe"', capabilities: ['tabs'], unavailable: [], notes: 'Chromium CDP.',
                   test_url: 'http://10.0.0.5:9502/json/list', commands: { windows: 'edge-cmd' } }] } });
    const sel = h.anyEl('browserSelect');
    assert.deepEqual(sel.children.map((o) => o.value), ['edge'], 'a registry change needs no JS change');
    assert.equal(sel.value, 'edge');
    assert.equal(val(h, 'cdpHost'), '10.0.0.5');
    assert.equal(txt(h, 'cdpResolvedPort'), '9502');
    assert.equal(txt(h, 'cdpLaunchCmd'), 'edge-cmd');
  });

  test('a local port edit refreshes the launch-command preview', () => {
    const h = boot();
    h.anyEl('cdpPort').value = '9333';
    if (h.sb.BrowserConnection) h.sb.BrowserConnection.updatePreview();
    const cmd = txt(h, 'cdpLaunchCmd');
    assert.ok(cmd.includes('--remote-debugging-port=9333'), `preview follows the base port: ${cmd}`);
    assert.ok(cmd.includes('--user-data-dir='), 'and keeps the dir flag');
  });
});
