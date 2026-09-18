/* test_window_presets.mjs — preset response parsing for the restore path
   (2026-09-18 window-preset-restore).

   Regression: load_window_preset used to answer an envelope
   {ok, name, payload, window_states}; _getDocument passed that envelope to
   validatePortablePreset, which requires `format` → every preset preview died
   with "unsupported window preset format or schema version". The slot now
   answers {ok, name, document} with the full portable document.
   Docs: docs/archive/2026-09-18-window-preset-restore/design.md
*/
import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../app/ui/web');
const sandbox = { console, JSON, Math, Object, Array, String };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(WEB, 'js', 'window-presets-actions.js'), 'utf-8'), sandbox);
const W = sandbox.WindowPresetsActions;

const DOC = { format: 'chat-v-bot.window-preset', schema_version: 1, name: 'Desk', grid: { type: 'sash-tree' } };

test('response: {ok, document} envelope → the document', () => {
  const raw = JSON.stringify({ ok: true, name: 'Desk', document: DOC });
  assert.deepStrictEqual(W._presetResponseDocument(raw), DOC);
});

test('response: raw portable document (older builds) → tolerated', () => {
  assert.deepStrictEqual(W._presetResponseDocument(JSON.stringify(DOC)), DOC);
  assert.strictEqual(W._presetResponseDocument(DOC), DOC);  // same object, no parse
});

test('response: old envelope without document (the 12:34 bug) → null', () => {
  const oldEnvelope = JSON.stringify({ ok: true, name: 'Desk', payload: '{"v":4}', window_states: {} });
  assert.strictEqual(W._presetResponseDocument(oldEnvelope), null);
});

test('response: failure envelope / bad JSON / junk → null', () => {
  assert.strictEqual(W._presetResponseDocument(JSON.stringify({ ok: false, error: 'not found' })), null);
  assert.strictEqual(W._presetResponseDocument('not json at all'), null);
  assert.strictEqual(W._presetResponseDocument(42), null);
  assert.strictEqual(W._presetResponseDocument(null), null);
});
