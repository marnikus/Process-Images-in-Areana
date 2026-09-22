/**
 * cdp-listeners.js — connection status names the real browser (I-63).
 *
 * The reported bug: the log said "Chrome connection error" while the app was
 * pointing at Firefox on port 9224, which made the failure unreadable.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS = path.resolve(__dirname, '../../app/ui/web/js');

function load() {
  const logs = [];
  const dot = { className: '', title: '' };
  const sandbox = {
    console, JSON, Set, Map, Object, Array, String, setTimeout,
    document: { getElementById: (id) => (id === 'connectionStatus' ? dot : null) },
    LogConsole: { log: (msg, level) => logs.push([msg, level]) },
    CDPStore: { connected: false, dedupTabs: (t) => t },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(JS, 'panels/cdp/cdp-listeners.js'), 'utf-8'),
                  sandbox, { filename: 'cdp-listeners.js' });
  const panel = { updateUrlRowsConnection() {} };
  return { L: sandbox.window.CDPListeners || sandbox.CDPListeners, logs, panel, dot };
}

describe('connection status names its browser', () => {
  test('a Firefox error never says Chrome', () => {
    const { L, logs, panel } = load();
    L.onConnectionStatus(panel, 'error', 'Firefox');
    const [msg] = logs.at(-1);
    assert.match(msg, /Firefox connection error/);
    assert.doesNotMatch(msg, /Chrome/);
  });

  test('a Chrome error says Chrome', () => {
    const { L, logs, panel } = load();
    L.onConnectionStatus(panel, 'error', 'Chrome');
    assert.match(logs.at(-1)[0], /Chrome connection error/);
  });

  test('connected and disconnected are named too', () => {
    const { L, logs, panel } = load();
    L.onConnectionStatus(panel, 'connected', 'Firefox');
    L.onConnectionStatus(panel, 'disconnected', 'Firefox');
    assert.match(logs[0][0], /Firefox connected/);
    assert.match(logs[1][0], /Firefox disconnected/);
  });

  test('an unnamed browser falls back to a neutral word, never Chrome', () => {
    const { L, logs, panel } = load();
    L.onConnectionStatus(panel, 'error');
    const [msg] = logs.at(-1);
    assert.match(msg, /Browser connection error/);
    assert.doesNotMatch(msg, /Chrome/);
  });

  test('the status dot still reflects the state', () => {
    const { L, panel, dot } = load();
    L.onConnectionStatus(panel, 'error', 'Firefox');
    assert.match(dot.className, /error/);
  });
});
