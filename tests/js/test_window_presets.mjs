/* Tier A — window-presets-actions load contract (Node.js, no browser).
   Regression: bridge load_window_preset returned an {ok,name,payload,...}
   envelope while _showPreview validates a portable doc (format/grid/windows)
   → every backend preset load failed with 'unsupported window preset
   format or schema version'. The bridge now returns the doc itself, or
   {ok:false,error}; _getDocument must surface the error and pass the doc
   through untouched. RULE 8: executes the real file with stubbed bridge. */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const actionsPath = path.resolve(__dirname, '../../app/ui/web/js/window-presets-actions.js');
const actionsCode = fs.readFileSync(actionsPath, 'utf-8');

function loadActions(bridgeRaw) {
  const messages = [];
  const sandbox = {
    console, JSON, Object, Array, Set, Error,
    localStorage: { getItem: () => null, setItem: () => {} },
    App: { bridge: { load_window_preset: (name, cb) => cb(bridgeRaw) } },
  };
  vm.createContext(sandbox);
  const loaded = vm.runInContext(`${actionsCode}\nWindowPresetsActions;`, sandbox,
    { filename: 'window-presets-actions.js' });
  const facade = { ...loaded, _message: (t, l) => messages.push([t, l]) };
  return { facade, messages };
}

describe('window-presets-actions _getDocument — Tier A (no browser)', () => {
  test('ok:false envelope surfaces the error and yields null (no preview crash)', () => {
    const { facade, messages } = loadActions(JSON.stringify({ ok: false, error: 'nope' }));
    let got = 'unset';
    facade._getDocument('Desk', (doc) => { got = doc; });
    assert.equal(got, null);
    assert.equal(messages.length, 1);
    assert.match(messages[0][0], /could not be loaded.*nope/);
    assert.equal(messages[0][1], 'error');
  });

  test('portable doc passes through untouched for the preview', () => {
    const doc = { format: 'chat-v-bot.window-preset', name: 'Desk', grid: { tree: { t: 'leaf' } } };
    const { facade, messages } = loadActions(JSON.stringify(doc));
    let got = null;
    facade._getDocument('Desk', (d) => { got = d; });
    assert.deepEqual(got, doc);
    assert.equal(messages.length, 0);
  });
});
