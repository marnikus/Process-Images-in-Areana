/** The autorun page's inline script, executed (RULE 8) — not string-matched.
 *
 *  The 2026-09-24 batch-automation contract: ONE macro dispatch (the vendored
 *  1 s interval re-ran the macro while it was still executing), and the helper
 *  tab closes itself on kantuInvokeSuccess (failsafe 120 s) so no helper tab
 *  survives the run. Design: docs/archive/2026-09-24-uivision-first-run-and-helper-cleanup/.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const page = fs.readFileSync(
  path.resolve(__dirname, '../../app/browser/uivision/autorun.py'), 'utf-8');
const script = page.match(/<script>\n([\s\S]*?)<\/script>/)[1];

/** Boot the page script in a vm with stub browser globals; return the spies. */
function bootPage({ extensionLoaded, protocol = 'file:' }) {
  const s = {
    timers: [], listeners: {}, dispatches: [], banners: [],
    opened: 0, closed: 0,
  };
  let nextTimer = 1;
  const documentStub = {
    title: '',
    documentElement: { getAttribute: () => (extensionLoaded ? '1' : null) },
    body: { appendChild: (el) => s.banners.push(el.textContent) },
    createElement: () => ({ setAttribute() {}, textContent: '' }),
  };
  const windowStub = {
    location: { protocol, href: 'file:///cfg/ui.vision.html?macro=M' },
    dispatchEvent: (evt) => s.dispatches.push(evt),
    addEventListener: (type, fn) => { (s.listeners[type] ||= []).push(fn); },
    open: (url, target) => { s.opened += 1; return target === '_self' ? windowStub : {}; },
    close: () => { s.closed += 1; },
  };
  windowStub.window = windowStub;
  const sandbox = {
    console,
    document: documentStub,
    window: windowStub,
    setTimeout: (fn, ms) => { s.timers.push({ id: nextTimer, fn, ms }); return nextTimer++; },
    clearTimeout: (id) => {
      const i = s.timers.findIndex((t) => t.id === id);
      if (i >= 0) s.timers.splice(i, 1);
    },
    CustomEvent: class { constructor(type, opts) { this.type = type; this.detail = opts.detail; } },
    URL: class {
      constructor(href) {
        this.href = href;
        const reload = String(href).match(/reload=(\d+)/);
        this.params = new Map(reload ? [['reload', Number(reload[1])]] : []);
      }

      get searchParams() {
        const params = this.params;
        return { get: (k) => params.get(k) ?? 0, set: (k, v) => params.set(k, v) };
      }

      toString() {
        const base = String(this.href).split('?')[0];
        const q = [...this.params].map(([k, v]) => `${k}=${v}`).join('&');
        return q ? `${base}?${q}` : base;
      }
    },
  };
  vm.createContext(sandbox);
  s.rerun = () => vm.runInContext(script, sandbox, { filename: 'ui.vision.html#inline' });
  s.rerun();                                          // the page's initial load
  s.window = windowStub;
  s.fire = (type) => { for (const fn of s.listeners[type] || []) fn({ type }); };
  s.runTimer = (ms) => {
    const t = s.timers.find((x) => x.ms === ms);
    assert.ok(t, `no timer scheduled for ${ms} ms (have: ${s.timers.map((x) => x.ms)})`);
    s.timers.splice(s.timers.indexOf(t), 1);
    t.fn();
  };
  s.pending = () => s.timers.map((t) => t.ms).sort((a, b) => a - b);
  return s;
}

describe('autorun page behaviour (executed)', () => {
  test('the extension is live: exactly ONE macro dispatch, no re-dispatch timer', () => {
    const s = bootPage({ extensionLoaded: true });
    s.runTimer(500);                                    // the main() tick
    assert.equal(s.dispatches.length, 1);
    assert.equal(s.dispatches[0].type, 'kantuSaveAndRunMacro');
    assert.equal(s.dispatches[0].detail.noImport, true);
    assert.deepEqual(s.pending(), [8000, 120000]);      // the #203 warn + failsafe close
    assert.ok(!s.pending().includes(1000), 'no 1 s re-dispatch interval exists');
    assert.equal(s.dispatches.length, 1, 'no re-dispatch while the macro runs');
  });

  test('the tab closes itself after kantuInvokeSuccess (failsafe cleared)', () => {
    const s = bootPage({ extensionLoaded: true });
    s.runTimer(500);
    s.fire('kantuInvokeSuccess');                       // the run finished
    assert.deepEqual(s.pending(), [2000]);              // failsafe + warn cleared
    s.runTimer(2000);                                   // the grace elapses → self-close
    assert.ok(s.closed >= 1, 'the helper tab closed itself');
  });

  test('the 120 s failsafe closes the tab even when no success event ever fires', () => {
    const s = bootPage({ extensionLoaded: true });
    s.runTimer(500);
    s.runTimer(120000);
    assert.ok(s.closed >= 1, 'the failsafe closed a stuck helper tab');
  });

  test('without the extension the page reloads (the retry), never dispatches', () => {
    const s = bootPage({ extensionLoaded: false });
    s.runTimer(500);
    assert.equal(s.dispatches.length, 0);
    s.runTimer(1000);                                   // the reload tick
    assert.match(s.window.location.href, /reload=1/);   // the page navigated itself
    assert.equal(s.dispatches.length, 0);
  });

  test('after MAX_TRY reloads the #204 banner shows and the tab self-closes', () => {
    const s = bootPage({ extensionLoaded: false });
    for (let n = 1; n <= 3; n += 1) {                   // each reload re-runs the page
      s.runTimer(500);
      s.runTimer(1000);
      s.rerun();
    }
    s.runTimer(500);                                    // reload=3 → the banner tick
    assert.match(s.banners.join('\n'), /Error #204/);
    s.runTimer(8000);                                   // the delayed self-close
    assert.ok(s.closed >= 1, 'the failing helper tab closed itself');
    assert.equal(s.dispatches.length, 0);               // it never ran the macro blind
  });
});
