# Design — the `watcher_status` signal/slot name clash (and a traceable JS console) (2026-09-25)

**Status:** implemented 2026-09-25
**Entry:** SYSTEM_OF_RECORD.md → I-19 (Captcha window), I-63 unaffected
**Owner report (entry):** `python -m app.main` → `js: Uncaught TypeError: fn is not a
function` right after *Starting Arena Image Processor* — "small uncaught err but no
idea how to trace and fix".

## 1. The crash, traced

The terminal line is the **page's JS console** forwarded by Qt WebEngine (the
`js:` channel). Enumerating every `fn(...)` call site in `app/ui/web/js` left one
data-driven candidate: `CaptchaPanel._call` (`panels/captcha.js`) —
`const fn = App.bridge?.[name]; if (!fn) return false; … fn(…)`. It runs at startup
(`CaptchaPanel.init` → `setTimeout(refresh, 1200)` → `loadStatus()` →
`_call('watcher_status', …)`).

**Root cause — a Signal named like a Slot.** `app/ui/bridge.py` declared
`watcher_status = Signal(str)` (the push) while `WatcherSolverMixin` defines
`@Slot def watcher_status(self)` (the pull). On the real `Bridge` the class-body
Signal shadows the mixin method, and QWebChannel makes it fatal:

```js
// qwebchannel.js (Qt source, verified): methods first, signals LAST —
data.methods.forEach(addMethod);            // object[name] = callable …
data.signals.forEach(function (signal) { addSignal(signal, false); });
// addSignal: object[signalName] = { connect(…), disconnect(…) }   ← NOT callable
```

A name clash therefore overwrites the callable with the `{connect, disconnect}`
subscription object → truthy, so the old `if (!fn)` guard passed →
`fn(onRes)` → **`TypeError: fn is not a function`** — reproduced exactly in
`tests/js/test_captcha_provider_panel.mjs` (signal-shaped raw bridge prop).
Exactly **one clash existed in the whole app** (AST scan: 26 signals vs all
`@Slot` names → intersection = `{watcher_status}`). Tests never caught it: JS
tests use a fake bridge where *every* property is callable, and the Python slot
tests use mixin hosts that don't carry the Signal.

## 2. Decisions

1. **Rename the push signal, keep the slot name.** `watcher_status = Signal(str)` →
   `watcher_status_updated` (emitted in `panels/watcher_captcha.py`, subscribed in
   `arena-app/listeners.js` registry). The `watcher_status` @Slot (documented in
   SOR I-19, called by `CaptchaPanel._call`) stays and is reachable again.
2. **Never trust truthiness on the bridge** — `CaptchaPanel._call` now requires
   `typeof fn === 'function'`: any future non-callable (signal/property) is a
   silent `false`, never an uncaught TypeError.
3. **Regression locks (both red first):**
   * `tests/test_bridge_slots.py::test_no_signal_named_like_a_slot` — AST scan,
     signal ∩ slot must be ∅ (the whole class of bugs, not just this name).
   * `tests/js/test_captcha_provider_panel.mjs` — a signal-shaped
     `watcher_status` on the bridge is skipped and `refresh()` continues
     (harness gained `rawBridgeProps` to model real QWebChannel shapes).
4. **Traceability — the console now names file:line.** The bare `js:` line gave
   nowhere to look, so `app/utils/js_console.py` holds the pure formatter
   `js_console_line(level, message, location)` → `js: <message> (<location>)`
   (own file: the formatter's 3 params must not push `logging.py`'s recorded
   `max_params=1` — zero-tolerance ratchet), and `main_window.py` installs
   `_ConsolePage(QWebEnginePage)` through the module-level `_build_view()`
   (keeps `MainWindow`'s recorded `max_class_loc=126` line-for-line). The
   `javaScriptConsoleMessage(self, *args)` override takes `*args` because the Qt
   virtual's fixed 4-arg signature would blow `max_params` (self excluded → 1) —
   and routes every console message, including the next uncaught TypeError,
   into the app logger (file + terminal) instead of the location-less default.
   Pinned by AST + format tests in `tests/test_ui_wiring.py` (no Qt needed —
   the sandbox has no libGL).

## 3. Structure (RULE 16/18)

| symbol | file | LOC | limit |
|---|---|---|---|
| `js_console_line` | `app/utils/js_console.py` (new) | 5 | ≤20 prefer, ≤30 fail; params 3 = PREFER |
| `_ConsolePage.javaScriptConsoleMessage` | `main_window.py` | 4 | params 1 via `*args` (baseline max_params 2 held) |
| `_build_view` | `main_window.py` | 4 | keeps `MainWindow` at recorded 126 class LOC |
| signal/slot clash + format tests | tests | — | tests out of scope |

No production function grew past its baseline; `captcha.js:_call` replaced one
guard line with another (+2 comment lines).

## 4. Supersession / notes

* `docs/research_summary.md` (historical) still says "Signals `watcher_status`" —
  it describes the 2026-09 era design; the current truth is
  `watcher_status_updated` (push) + `watcher_status` (slot), recorded here and
  in the code comments.
* The mystery of *who* printed the original `js:` prefix on the owner's Windows
  box (default Qt forwarding) is moot: `_ConsolePage` owns the channel now.
