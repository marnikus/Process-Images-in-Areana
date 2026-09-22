/**
 * Firefox round (2026-09-21): the Settings panel speaks about *browsers*, not
 * just Chrome.
 *
 * The owner's acceptance: one panel covering Chrome AND Firefox, one shared
 * host/port/URL-pattern, a per-browser block (data dir, extra args, resolved
 * endpoint, launch command) and a capability line that NAMES what the selected
 * browser cannot do yet (a BiDi Firefox has no screenshot / file-attach), so the
 * panel never pretends parity it does not have.
 *
 * The browser table itself lives in Python (`app/browser/browsers.py`); the
 * panel renders whatever the bridge sends (`browsers` in the `get_cdp_config`
 * payload) and keeps only a two-entry id/label fallback for the first paint.
 *
 * RED at `bce5a01`: no `browser-connection.js`, index.html still said
 * "Chrome Debug Connection".
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

const CONFIG = {
  host: '127.0.0.1',
  port: 9223,
  url_pattern: 'arena.ai',
  active_browser: 'chrome',
  browsers: [
    { id: 'chrome', label: 'Chrome (Chromium)', protocol: 'cdp', port_offset: 0, resolved_port: 9223,
      user_data_dir: 'C:\\arena-images-chrome', extra_args: '--disable-extensions',
      dir_flag: '--user-data-dir', binary: '"C:\\chrome.exe"', notes: 'Full automation (CDP).',
      capabilities: ['dom', 'evaluate', 'input', 'navigate', 'screenshot', 'set_files', 'tabs'], unavailable: [],
      test_url: 'http://127.0.0.1:9223/json/list',
      commands: { windows: '"C:\\chrome.exe" --remote-debugging-port=9223 --user-data-dir="C:\\arena-images-chrome"',
                  windows_with_url: 'chrome-url', linux: 'google-chrome', macos: 'mac-chrome' } },
    { id: 'firefox', label: 'Firefox (Mozilla)', protocol: 'rdp', port_offset: 1, resolved_port: 9224,
      user_data_dir: 'C:\\arena-images-firefox', extra_args: '-no-remote',
      dir_flag: '-profile', binary: '"C:\\firefox.exe"',
      debug_flag: 'start-debugger-server',
      notes: 'DevTools RDP — attach/detach freely; navigator.webdriver stays false.',
      capabilities: ['click', 'evaluate', 'tabs'],
      unavailable: ['dom', 'input', 'screenshot', 'set_files'],
      test_url: 'tcp 127.0.0.1:9224 — start Firefox with --start-debugger-server 9224 (DevTools socket, no Remote Agent)',
      prefs: [{ name: 'devtools.debugger.remote-enabled', value: true },
              { name: 'devtools.debugger.prompt-connection', value: false }],
      prefs_file: 'C:\\arena-images-firefox\\user.js',
      user_js: 'user_pref("devtools.debugger.remote-enabled", true);\nuser_pref("devtools.debugger.prompt-connection", false);',
      stealth: 'Keeps the browser unflagged: no geckodriver, no Marionette, no Remote Agent — navigator.webdriver stays false. Start it with --start-debugger-server, never with --remote-debugging-port (Firefox bug 1719505 sets that flag for the whole session).',
      commands: { windows: '"C:\\firefox.exe" --start-debugger-server 9224 -profile="C:\\arena-images-firefox" -no-remote',
                  windows_with_url: 'ff-url', linux: 'firefox', macos: 'mac-firefox' } },
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

describe('browser debug connection panel (Firefox round)', () => {
  test('index.html renames the block and mounts the shared + per-browser fields', () => {
    const start = html.indexOf('Browser Debug Connection');
    assert.ok(start > 0, 'the block is called "Browser Debug Connection"');
    assert.ok(!html.includes('Chrome Debug Connection (user configurable)'), 'the Chrome-only title is gone');
    const block = html.slice(start, html.indexOf('Page Load Timeout', start));
    for (const id of ['browserSelect', 'cdpHost', 'cdpPort', 'cdpUrlPattern', 'cdpUserDataDir', 'cdpExtraArgs',
                      'cdpResolvedPort', 'cdpLaunchCmd', 'cdpCopyCmdBtn', 'cdpTestUrl', 'cdpCapabilities',
                      'cdpBrowserNotes', 'cdpSaveBtn', 'cdpTestBtn', 'cdpPrefs', 'cdpStealth',
                      'cdpPrepareProfileBtn']) {
      assert.ok(block.includes(`id="${id}"`), `${id} is inside the browser block`);
    }
    assert.equal((html.match(/id="cdpUrlPattern"/g) || []).length, 1, 'one URL pattern for every browser');
    assert.ok(html.indexOf('js/panels/browser-connection.js') < html.indexOf('js/panels/settings.js'),
      'the browser module loads before settings.js (which delegates to it)');
  });

  test('the payload drives the selector: labels, order and the active browser', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    assert.deepEqual(sel.children.map((o) => o.value), ['chrome', 'firefox']);
    assert.deepEqual(sel.children.map((o) => o.textContent), ['Chrome (Chromium)', 'Firefox (Mozilla)']);
    assert.equal(sel.value, 'chrome', 'active_browser wins');
    assert.equal(val(h, 'cdpHost'), '127.0.0.1');
    assert.equal(val(h, 'cdpPort'), '9223', 'the shared field shows the BASE port');
    assert.equal(val(h, 'cdpUrlPattern'), 'arena.ai');
    assert.equal(val(h, 'cdpUserDataDir'), 'C:\\arena-images-chrome');
    assert.equal(txt(h, 'cdpResolvedPort'), '9223', 'Chrome derives base + 0');
  });

  test('switching the selector swaps the per-browser block and keeps the shared row', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    assert.equal(val(h, 'cdpUserDataDir'), 'C:\\arena-images-firefox');
    assert.equal(val(h, 'cdpExtraArgs'), '-no-remote');
    assert.equal(txt(h, 'cdpResolvedPort'), '9224', 'Firefox derives base + 1 — one port cannot host two servers');
    assert.ok(txt(h, 'cdpLaunchCmd').includes('firefox.exe'), 'its own launch command');
    assert.ok(txt(h, 'cdpTestUrl').includes('9224'), 'the debugger socket of THIS browser');
    assert.ok(txt(h, 'cdpTestUrl').includes('debugger'), 'and how to open it');
    assert.equal(val(h, 'cdpHost'), '127.0.0.1', 'shared host untouched');
    assert.equal(val(h, 'cdpPort'), '9223', 'shared port untouched');
    assert.equal(val(h, 'cdpUrlPattern'), 'arena.ai', 'one pattern for all browsers');
  });

  test('the capability line names what the selected browser cannot do', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    const caps = txt(h, 'cdpCapabilities');
    assert.ok(caps.includes('click') && caps.includes('evaluate'), `capabilities shown: ${caps}`);
    for (const missing of ['screenshot', 'set_files', 'input']) {
      assert.ok(caps.includes(missing), `${missing} is named as unavailable, never a silent timeout`);
    }
    assert.ok(txt(h, 'cdpBrowserNotes').includes('RDP'), 'the note explains which protocol is in use');
  });

  test('one Save posts the active browser plus every per-browser block', () => {
    const h = boot();
    h.anyEl('cdpSaveBtn').dispatch('click', {});
    const saves = h.calls.filter((c) => c.slot === 'set_cdp_config');
    assert.equal(saves.length, 1, 'one Save click, one save');
    const payload = JSON.parse(saves[0].args[0]);
    assert.equal(payload.browser, 'chrome');
    assert.equal(payload.host, '127.0.0.1');
    assert.equal(payload.port, 9223);
    assert.equal(payload.user_data_dir, 'C:\\arena-images-chrome');
    assert.ok(payload.browsers.firefox, 'the other browser travels too (both are configurable at once)');
    assert.equal(payload.browsers.firefox.port, 9224);
    assert.equal(payload.browsers.firefox.user_data_dir, 'C:\\arena-images-firefox');
  });

  test('an edit survives switching browsers and travels in its own block', () => {
    const h = boot();
    h.anyEl('cdpUserDataDir').value = 'D:\\chrome-profile';   // edited while Chrome is active
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    assert.equal(val(h, 'cdpUserDataDir'), 'C:\\arena-images-firefox', 'Firefox shows ITS dir, not Chrome\'s');
    sel.value = 'chrome';
    sel.dispatch('change', { target: sel });
    assert.equal(val(h, 'cdpUserDataDir'), 'D:\\chrome-profile', 'the Chrome edit came back');
    h.anyEl('cdpSaveBtn').dispatch('click', {});
    const payload = JSON.parse(h.calls.filter((c) => c.slot === 'set_cdp_config').pop().args[0]);
    assert.equal(payload.browser, 'chrome');
    assert.equal(payload.user_data_dir, 'D:\\chrome-profile');
    assert.equal(payload.browsers.firefox.user_data_dir, 'C:\\arena-images-firefox', 'both dirs persist');
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

  test('the Firefox block shows the prefs that make the DevTools socket reachable', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    const prefs = txt(h, 'cdpPrefs');
    assert.ok(prefs.includes('user_pref("devtools.debugger.remote-enabled", true);'), prefs);
    assert.ok(prefs.includes('user_pref("devtools.debugger.prompt-connection", false);'), prefs);
    assert.ok(txt(h, 'cdpPrefsFile').includes('user.js'), 'and where they belong');
  });

  test('the stealth line names why this channel keeps the browser unflagged', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    const stealth = txt(h, 'cdpStealth');
    assert.ok(stealth.includes('webdriver'), `says what stays false: ${stealth}`);
    assert.ok(stealth.includes('--remote-debugging-port'), 'and which flag to avoid');
    assert.ok(stealth.includes('geckodriver') || stealth.includes('Marionette'), 'and what is not loaded');
  });

  test('Prepare Profile asks the bridge to write user.js — exactly once', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    h.anyEl('cdpPrepareProfileBtn').dispatch('click', {});
    const saves = h.calls.filter((c) => c.slot === 'set_cdp_config');
    assert.equal(saves.length, 1, 'one click, one save');
    const payload = JSON.parse(saves[0].args[0]);
    assert.equal(payload.browser, 'firefox');
    assert.equal(payload.prepare_profile, true, 'the write is explicitly requested, never a side effect of Save');
    assert.equal(payload.browsers.firefox.user_data_dir, 'C:\\arena-images-firefox');
  });

  test('a local port edit refreshes the preview for the selected browser', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    h.anyEl('cdpPort').value = '9333';
    if (h.sb.BrowserConnection) h.sb.BrowserConnection.updatePreview();
    assert.ok(txt(h, 'cdpLaunchCmd').includes('9334'), `Firefox preview follows base+1: ${txt(h, 'cdpLaunchCmd')}`);
    assert.ok(txt(h, 'cdpLaunchCmd').includes('-profile='), 'and keeps its own dir flag');
  });
});
