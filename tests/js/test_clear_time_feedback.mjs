/**
 * Clear Time gives visible confirmation (bug report item 5).
 *
 * Report: "Pressing Clear Time should reset countdown to 0 with visual
 * confirmation for user (change color on sec or similar). Set URL status to
 * 'ready' immediately."
 *
 * The slot already cleared the timer correctly; what was missing was feedback —
 * the cell kept its old number until the next poll, so the button looked dead.
 * `PagePoolActions.flashCleared` repaints every clock for that tab to 00:00 and
 * marks it `.cool-cleared` for ~1.5 s. Both tables anchor their clocks on the
 * same `data-cool-tab` attribute, so one call covers the pool view and the URL
 * row together.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';
import './page_harness.mjs';   // installs the El setAttribute/getAttribute polyfills

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const readJs = (rel) => fs.readFileSync(path.join(WEB, 'js', rel), 'utf-8');

const TAB = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d';

/** A clock element exactly as both renderers emit it. */
function clock(tabId = TAB, left = 300) {
  const el = new El('span');
  el.setAttribute('data-cool-tab', tabId);
  el.setAttribute('data-cool-left', String(left));
  el.setAttribute('data-cool-at', String(Date.now()));
  el.textContent = '05:00';
  return el;
}

/** Boot page-pool actions with a document whose clocks we control. */
function boot(clocks) {
  const timers = [];
  const sandbox = {
    console, JSON, Object, Array, Math, Number, String, Date, parseInt, parseFloat, isNaN,
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    document: {
      getElementById: () => null,
      querySelectorAll: (sel) => {
        const m = /\[data-cool-tab="([^"]*)"\]/.exec(sel);
        return m ? clocks.filter((c) => c.getAttribute('data-cool-tab') === m[1]) : [];
      },
      querySelector: () => null,
      readyState: 'complete', addEventListener() {}, createElement: (t) => new El(t),
    },
    LogConsole: { log() {} },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'core/boot.js' });
  vm.runInContext(readJs('panels/page-pool/store.js'), sandbox, { filename: 'store.js' });
  vm.runInContext(readJs('panels/page-pool/actions.js'), sandbox, { filename: 'actions.js' });
  return { sandbox, timers };
}

describe('Clear Time — visible confirmation', () => {
  test('the countdown drops to 00:00 immediately, not on the next poll', () => {
    const el = clock();
    const { sandbox } = boot([el]);
    assert.equal(sandbox.PagePoolActions.flashCleared(TAB), 1);
    assert.equal(el.textContent, '00:00');
    assert.equal(el.getAttribute('data-cool-left'), '0');
  });

  test('the cell is marked so the user sees the change (colour flash)', () => {
    const el = clock();
    const { sandbox } = boot([el]);
    sandbox.PagePoolActions.flashCleared(TAB);
    assert.ok(el.classList.contains('cool-cleared'), 'flash class applied');
  });

  test('the flash is temporary — it clears itself again', () => {
    const el = clock();
    const { sandbox, timers } = boot([el]);
    sandbox.PagePoolActions.flashCleared(TAB);
    assert.ok(el.classList.contains('cool-cleared'));
    timers.forEach((fn) => fn());           // run the scheduled cleanup
    assert.ok(!el.classList.contains('cool-cleared'), 'flash removed');
    assert.equal(el.textContent, '00:00', 'but the cleared time stays');
  });

  test('every clock for that tab clears — the pool view and the URL row', () => {
    const a = clock();
    const b = clock();
    const other = clock('some-other-tab');
    const { sandbox } = boot([a, b, other]);
    assert.equal(sandbox.PagePoolActions.flashCleared(TAB), 2);
    assert.equal(a.textContent, '00:00');
    assert.equal(b.textContent, '00:00');
    assert.equal(other.textContent, '05:00', 'an unrelated tab is untouched');
  });

  test('a successful reset flashes; a failed one does not lie to the user', () => {
    const el = clock();
    const { sandbox } = boot([el]);
    let flashed = 0;
    sandbox.PagePoolActions.flashCleared = () => { flashed += 1; return 1; };
    sandbox.PagePoolActions.refresh = () => {};
    sandbox.TabLabel = { of: () => 'marnikus@gmail.com_3045' };
    sandbox.App = { bridge: { reset_page_cooldown: (_t, cb) => cb('{"ok": false, "error": "unknown tab"}') } };
    sandbox.PagePoolActions.resetCooldown(TAB);
    assert.equal(flashed, 0, 'no confirmation when the reset failed');

    sandbox.App = { bridge: { reset_page_cooldown: (_t, cb) => cb('{"ok": true}') } };
    sandbox.PagePoolActions.resetCooldown(TAB);
    assert.equal(flashed, 1, 'confirmation when it worked');
  });

  test('flashCleared is safe with no document (boot order, RULE 4)', () => {
    const { sandbox } = boot([]);
    sandbox.document = undefined;
    assert.equal(sandbox.PagePoolActions.flashCleared(TAB), 0);
  });
});
