/* test_sash_restore.mjs — boot restore: callback path, signal-push fallback,
   double-delivery idempotency, and the no-response observable (2026-09-18).

   Regression: the grid was saved to session.json fine, but the boot restore
   relied on a single QWebChannel invokeMethod→response round trip; when that
   response is lost the callback never fired and the grid silently reset. The
   signal push (grid_layout_restored / window_states_restored, requested via
   request_grid_restore / request_window_states_restore) is the fallback.
   Docs: docs/archive/2026-09-18-grid-restore-push/design.md
*/
import test from 'node:test';
import assert from 'node:assert';
import { createSashGrid } from './sash_harness.mjs';

/* Fake QWebChannel bridge. cbFires=false models a LOST invokeMethod response
   (the callback never fires — the production failure mode). pushFires=false
   models the signal push never arriving either. */
function makeFakeBridge({ cbFires = true, pushFires = true } = {}) {
  const state = { gridPayload: null, statesPayload: null, cbFires, pushFires };
  const gridHandlers = [];
  const statesHandlers = [];
  const calls = { grid: 0, states: 0, reqGrid: 0, reqStates: 0 };
  const bridge = {
    get_grid_layout: (cb) => {
      calls.grid += 1;
      if (state.cbFires) cb(state.gridPayload || '');
      return undefined;
    },
    get_window_states: (cb) => {
      calls.states += 1;
      if (state.cbFires && state.statesPayload) cb(state.statesPayload);
      return undefined;
    },
    request_grid_restore: () => {
      calls.reqGrid += 1;
      if (state.pushFires && state.gridPayload) gridHandlers.forEach((h) => h(state.gridPayload));
      return state.gridPayload || '';
    },
    request_window_states_restore: () => {
      calls.reqStates += 1;
      if (state.pushFires && state.statesPayload) statesHandlers.forEach((h) => h(state.statesPayload));
      return state.statesPayload || '';
    },
    grid_layout_restored: { connect: (fn) => gridHandlers.push(fn) },
    window_states_restored: { connect: (fn) => statesHandlers.push(fn) },
  };
  return {
    state,
    calls,
    bridge,
    emitGrid: (p) => gridHandlers.forEach((h) => h(p)),
    emitStates: (p) => statesHandlers.forEach((h) => h(p)),
  };
}

/* Boot the grid WITHOUT a bridge (harness default), then install the fake
   App/LogConsole and run the single restore pass — the unit under test. */
function bootRestore(fake, logs) {
  const h = createSashGrid();
  h.sandbox.App = { bridge: fake.bridge };
  h.sandbox.LogConsole = { logs, log: (m, l = 'info') => logs.push([String(m), l]) };
  h.SashGrid._restorePending = true;
  h.SashGrid._loadFromBackend();
  return h;
}

function customPayload(h) {
  const t = h.SashCore.defaultTree();
  t.sizes = [90, 5, 5];
  return h.SashCore.serialize(t);
}

test('restore: lost response → signal push still delivers the layout', () => {
  const logs = [];
  const fake = makeFakeBridge({ cbFires: false });
  const h = bootRestore(fake, logs);
  fake.state.gridPayload = customPayload(h);
  fake.emitGrid(fake.state.gridPayload);  // the push arrives after the request
  assert.strictEqual(fake.calls.reqGrid, 1, 'must request the signal push once');
  const expected = h.SashCore.deserialize(fake.state.gridPayload).tree;
  assert.deepStrictEqual(h.SashGrid.root, expected, 'pushed layout applied');
});

test('restore: callback AND push both deliver → applied exactly once', () => {
  const logs = [];
  const fake = makeFakeBridge({ cbFires: true, pushFires: true });
  const h = createSashGrid();
  fake.state.gridPayload = customPayload(h);
  h.sandbox.App = { bridge: fake.bridge };
  h.sandbox.LogConsole = { logs, log: (m, l = 'info') => logs.push([String(m), l]) };
  h.SashGrid._restorePending = true;
  h.SashGrid._loadFromBackend();
  const expected = h.SashCore.deserialize(fake.state.gridPayload).tree;
  assert.deepStrictEqual(h.SashGrid.root, expected);
  const applied = logs.filter(([m]) => m.startsWith('🪟 Grid restored from session'));
  assert.strictEqual(applied.length, 1, 'double delivery must render once');
});

test('restore: nothing delivered → default kept + observable warning', () => {
  const logs = [];
  const fake = makeFakeBridge({ cbFires: false, pushFires: false });
  const h = bootRestore(fake, logs);
  const before = JSON.stringify(h.SashGrid.root);
  h.SashGrid._finishRestore();  // the 3 s guard timeout (no-op in the harness)
  assert.strictEqual(JSON.stringify(h.SashGrid.root), before, 'root untouched');
  const warn = logs.find(([m]) => m.startsWith('🪟 Grid restore: no backend response'));
  assert.ok(warn, 'the failed restore must be visible in the LogConsole');
});

test('restore: saved layout via callback applies and logs', () => {
  const logs = [];
  const fake = makeFakeBridge({ cbFires: true, pushFires: false });
  const h = createSashGrid();
  fake.state.gridPayload = customPayload(h);
  h.sandbox.App = { bridge: fake.bridge };
  h.sandbox.LogConsole = { logs, log: (m, l = 'info') => logs.push([String(m), l]) };
  h.SashGrid._restorePending = true;
  h.SashGrid._loadFromBackend();
  const expected = h.SashCore.deserialize(fake.state.gridPayload).tree;
  assert.deepStrictEqual(h.SashGrid.root, expected);
  assert.ok(logs.some(([m]) => m.startsWith('🪟 Grid restored from session')));
});

test('restore: window states delivered via signal push', () => {
  const logs = [];
  const fake = makeFakeBridge({ cbFires: false, pushFires: true });
  fake.state.statesPayload = JSON.stringify({ closed: ['log'], minimized: ['progress'] });
  const h = bootRestore(fake, logs);
  assert.ok(h.SashGrid.closedWindows.has('log'));
  assert.ok(h.SashGrid.minimizedWindows.has('progress'));
  assert.strictEqual(fake.calls.reqStates, 1);
});

test('restore: no bridge at all → guard released, no crash, no warning', () => {
  const logs = [];
  const h = createSashGrid();
  assert.strictEqual(h.SashGrid._restorePending, false, 'guard released on no-bridge boot');
  assert.ok(h.SashGrid.root, 'default tree in place');
  assert.ok(!logs.some(([m]) => m.includes('Grid restore')), 'no restore noise in standalone mode');
});
