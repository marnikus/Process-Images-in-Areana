/**
 * Round 9 (2026-09-22): ONE pass over every browser, and the panel says so.
 *
 * The owner's words: "every browser like chrome - firefox and others has it individual
 * port. if it starts from 9223 then app should parse all page on ws: 9223, ws: 9224 and
 * ws: 9225 (all that defined in win settings)".
 *
 * So the Settings block must show the endpoints one Refresh asks (each browser's own
 * port + channel, and a browser switched off marked off), every tab row must say which
 * browser it came from, and the log must count per browser instead of calling everything
 * "Chrome".
 *
 * RED at `741b771`: no scan line in the page, tab options had no browser tag, and the
 * receive log said "unique Chrome tab(s)" no matter what answered.
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
  scan_line: 'Scanning: chrome 127.0.0.1:9223 (CDP) · firefox 127.0.0.1:9224 (RDP) · edge — off',
  scan_targets: [
    { id: 'chrome', label: 'Chrome (Chromium)', host: '127.0.0.1', port: 9223, protocol: 'cdp', enabled: true },
    { id: 'firefox', label: 'Firefox (Mozilla)', host: '127.0.0.1', port: 9224, protocol: 'rdp', enabled: true },
    { id: 'edge', label: 'Edge (Chromium)', host: '127.0.0.1', port: 9225, protocol: 'cdp', enabled: false },
  ],
  browsers: [
    { id: 'chrome', label: 'Chrome (Chromium)', protocol: 'cdp', port_offset: 0, resolved_port: 9223,
      enabled: true, user_data_dir: 'C:\\arena-images-chrome', extra_args: '',
      dir_flag: '--user-data-dir', binary: '"C:\\chrome.exe"', notes: 'Full automation (CDP).',
      capabilities: ['tabs'], unavailable: [], test_url: 'http://127.0.0.1:9223/json/list',
      commands: { windows: 'chrome-cmd' } },
    { id: 'firefox', label: 'Firefox (Mozilla)', protocol: 'rdp', port_offset: 1, resolved_port: 9224,
      enabled: true, user_data_dir: 'C:\\arena-images-firefox', extra_args: '-no-remote',
      dir_flag: '-profile', binary: '"C:\\firefox.exe"', notes: 'DevTools RDP socket.',
      debug_flag: 'start-debugger-server',
      capabilities: ['click', 'evaluate', 'tabs'], unavailable: ['dom', 'input', 'screenshot', 'set_files'],
      test_url: 'tcp 127.0.0.1:9224', commands: { windows: 'ff-cmd' } },
    { id: 'edge', label: 'Edge (Chromium)', protocol: 'cdp', port_offset: 2, resolved_port: 9225,
      enabled: false, user_data_dir: '', extra_args: '', dir_flag: '--user-data-dir', binary: '"C:\\msedge.exe"',
      notes: 'Chromium CDP.', capabilities: ['tabs'], unavailable: [], test_url: 'http://127.0.0.1:9225/json/list',
      commands: { windows: 'edge-cmd' } },
  ],
};

/** Tabs as one pass lists them: two Chrome sockets and two Firefox `rdp://` handles. */
const TABS = [
  { id: 'tab-3', title: 'Arena', url: 'https://arena.ai/c/1',
    ws_url: 'ws://127.0.0.1:9223/devtools/page/tab-3', browser: 'chrome', protocol: 'cdp' },
  { id: 'tab-4', title: 'New Tab', url: 'chrome://newtab/',
    ws_url: 'ws://127.0.0.1:9223/devtools/page/tab-4', browser: 'chrome', protocol: 'cdp' },
  { id: 'ctx-3', title: 'Arena (Firefox)', url: 'https://arena.ai/c/1',
    ws_url: 'rdp://127.0.0.1:9224/ctx-3', browser: 'firefox', protocol: 'rdp' },
  { id: 'ctx-4', title: 'Проверка 🚀', url: 'https://arena.ai/c/2',
    ws_url: 'rdp://127.0.0.1:9224/ctx-4', browser: 'firefox', protocol: 'rdp' },
];

function boot(overrides = {}) {
  const h = bootPage({
    replies: {
      get_cdp_config: { ...CONFIG, ...overrides },
      get_app_state: {},
      get_page_pool_status: { total: 0, steady: 0, busy: 0, cooling: 0, free: 0, pages: [] },
    },
  });
  h.flushTimers();          // SettingsPanel.loadCDPConfig runs on a 1000 ms timer
  return h;
}

const txt = (h, id) => String(h.anyEl(id).textContent);

describe('one pass over every browser (round 9)', () => {
  test('the browser block mounts the scan line', () => {
    const start = html.indexOf('Browser Debug Connection');
    assert.ok(start > 0, 'the browser block exists');
    const block = html.slice(start, html.indexOf('Page Load Timeout', start));
    assert.ok(block.includes('id="cdpScanLine"'), 'the block says which endpoints a pass scans');
  });

  test('the scan line is what the bridge computed — one line for every endpoint', () => {
    const h = boot();
    const line = txt(h, 'cdpScanLine');
    assert.equal(line, CONFIG.scan_line, 'the Python-built line is shown verbatim, never re-derived');
    assert.ok(line.includes('9223') && line.includes('9224'), 'both live endpoints are named');
    assert.ok(line.includes('RDP'), 'and the channel Firefox is read over');
    assert.ok(line.toLowerCase().includes('off'), 'a browser switched off says so instead of looking scanned');
  });

  test('without a bridge-computed line the panel still lists every browser it knows', () => {
    const h = boot({ scan_line: '' });
    const line = txt(h, 'cdpScanLine');
    assert.ok(line.startsWith('Scanning: ') && !line.endsWith('—'), `not left at the placeholder: ${line}`);
    assert.ok(line.includes('9223') && line.includes('9224'), `both endpoints: ${line}`);
    assert.ok(line.includes('(CDP)') && line.includes('(RDP)'), `each channel: ${line}`);
    assert.ok(line.toLowerCase().includes('off'), `Edge is switched off: ${line}`);
  });

  test('every tab row says which browser it came from', () => {
    const h = boot();
    h.emit('tabs_received', JSON.stringify(TABS));
    const sel = h.anyEl('tabSelect');
    assert.equal(sel.children.length, TABS.length, 'every tab of the pass is rendered (the placeholder is innerHTML)');
    const rendered = sel.children.map((o) => String(o.textContent));
    assert.ok(rendered.some((t) => t.includes('[chrome]')), rendered.join(' | '));
    assert.ok(rendered.some((t) => t.includes('[firefox]')), 'a Firefox handle is not dressed up as Chrome');
    const firefox = sel.children.find((o) => String(o.value).startsWith('rdp://'));
    assert.ok(firefox, 'the rdp:// handle is what gets connected');
    assert.ok(String(firefox.title).includes('firefox'), 'the tooltip names the browser too');
  });

  test('the browser selector shows each browser’s endpoint and channel', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    const firefox = sel.children.find((o) => o.value === 'firefox');
    assert.ok(String(firefox.title).includes('9224'), `endpoint in the tooltip: ${firefox.title}`);
    assert.ok(String(firefox.title).includes('RDP'), 'and the channel it is read over');
  });

  test('a pass from several browsers is counted per browser, never as “Chrome”', () => {
    const h = boot();
    h.emit('tabs_received', JSON.stringify(TABS));
    const line = h.logs.find((m) => m.includes('📑 Received'));
    assert.ok(line, `a receive line is logged: ${h.logs.join(' / ')}`);
    assert.ok(line.includes('4'), `the total: ${line}`);
    assert.ok(line.includes('chrome 2'), `Chrome's share: ${line}`);
    assert.ok(line.includes('firefox 2'), `Firefox's share: ${line}`);
    assert.ok(!line.includes('Chrome tab'), 'the count is not called Chrome anymore');
  });

  test('a session log line no longer claims the connection is Chrome', () => {
    const h = boot();
    h.emit('connection_status', 'connected');
    const line = h.logs.find((m) => m.includes('connected'));
    assert.ok(line && !line.includes('Chrome'), `neutral wording: ${line}`);
  });

  test('the Firefox preview leaves the profile flag out when no dir is configured', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    h.anyEl('cdpUserDataDir').value = '';
    if (h.sb.BrowserConnection) h.sb.BrowserConnection.updatePreview();
    const cmd = String(h.anyEl('cdpLaunchCmd').textContent);
    assert.ok(cmd.includes('--start-debugger-server'), `the DevTools flag is still there: ${cmd}`);
    assert.ok(cmd.includes('-no-remote'), `and the flag that makes the socket open: ${cmd}`);
    assert.ok(!cmd.includes('-profile'), `no forced dir means Firefox's own profile: ${cmd}`);
  });

  test('the dir label says when the browser\'s own profile is used', () => {
    const h = boot();
    const sel = h.anyEl('browserSelect');
    sel.value = 'firefox';
    sel.dispatch('change', { target: sel });
    const ff = h.sb.BrowserConnection.browsers.find((b) => b.id === 'firefox');
    ff.user_data_dir = '';
    ff.profile_dir = 'C:\\Users\\me\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\xy.default-release';
    h.sb.BrowserConnection.showBrowser('firefox');
    const label = String(h.anyEl('cdpDirLabel').textContent);
    assert.ok(label.toLowerCase().includes('own profile'), `the label is honest: ${label}`);
    assert.ok(label.includes('xy.default-release'), `and names the dir Prepare Profile writes: ${label}`);
  });

  test('the empty tab-select placeholder does not promise Chrome only', () => {
    const render = fs.readFileSync(path.join(WEB, 'js/panels/cdp/cdp-render.js'), 'utf-8');
    assert.ok(!html.includes('— Select Chrome Tab —'), 'the picker is browser-shaped');
    assert.ok(!render.includes('— Select Chrome Tab —'), 'and its placeholder is too');
    assert.ok(render.includes('— Select Browser Tab —'), render.match(/— Select [^—]*—/)[0]);
  });
});
