# Firefox auto with Extension — Ui.Vision RPA replaces the debugger channel (I-65)

**Date:** 2026-09-22 · **Supersedes:** I-62, I-63, I-64 (Firefox DevTools RDP)

## The problem with the approach being deleted

I-62…I-64 automated Firefox through its DevTools Remote Debugging Protocol.
That required launching the browser with `--start-debugger-server 9224`, which
brought three costs that no amount of polish removes:

1. **Firefox authorises every incoming debugger connection** with a modal
   dialog. I-64 reduced it to one connection per browser, but "one dialog" is
   still a dialog, and the user must keep the setting disabled by hand.
2. The debugger port **is** the automation surface: anything that can reach it
   can drive the browser, and the configuration is visible to the page's
   environment in ways a normal profile is not.
3. It is a second protocol to maintain beside Chrome's CDP — a parallel
   transport, framing, session cache and pool client, all Firefox-specific.

The user's instruction was to remove that channel entirely, leave **Chrome
exactly as it was**, and drive Firefox through the Ui.Vision RPA extension
instead.

## What replaced it

Firefox is now an **ordinary browser**. No debugger port, no geckodriver, no
Selenium, Playwright or Puppeteer, and no automation flags of any kind. The
work happens inside a signed extension:

```
Python  →  firefox -new-tab "file:///…/ui.vision.html?macro=…&cmd_var1=…"
                                    ↓
                        Ui.Vision extension runs the macro
                                    ↓
                    XClick → XModules → real OS mouse event
                                    ↓
Python  ←  polls the savelog file for the verdict
```

Because XClick moves the **actual OS cursor** rather than dispatching a DOM
event, the page receives `isTrusted: true`. That is the property the RDP path
could never provide through a scripted `click`.

### The Command Line API is a URL, not a CLI

Ui.Vision has no socket and no RPC. A macro is started by opening the
extension's autorun page with GET parameters, so building that URL correctly is
the entire integration contract (`app/browser/uivision/command_url.py`):

| Parameter | Value used | Why |
|---|---|---|
| `macro` | `Python_XClick_Demo` | which macro to run |
| `direct` | `1` | skip the "run this macro?" prompt, which would stall the run |
| `closeRPA` | `0` | **the default is 1** — closing would tear the log down mid-poll |
| `closeBrowser` | `0` | never close the user's browser |
| `savelog` | absolute path | with a full path the log is *written directly* instead of downloaded |
| `cmd_var1..3` | url, target | read in-macro as `${!cmd_var1}`; only three exist |
| `storage` | `browser` \| `xfile` | where the macro lives |

Two encoding rules are load-bearing and both are tested. The page must be a
`file:///` URL — a bare `C:\…` path makes the browser treat the `?…` as part of
the filename and report "file not found". And every value must be
percent-encoded, because the real XClick target
(`xpath=//a[span[text()='New Chat']]`) is full of `/ [ ] ' =`.

### XClick, never Click — enforced by construction

`macro.py` refuses to emit `Click`, `ClickAt`, `Type` or `SendKeys`:
`build_macro` raises on any of them. The rule is enforced where macros are
built rather than left to review, because a DOM click is silently wrong — it
works, it just carries `isTrusted:false`.

The demo macro is the framework proof the task asked for:

```
open       ${!cmd_var1}      # the tab the pattern resolved to
pause      2000              # let the SPA settle
storeText  ${!cmd_var2}      # read-only presence probe
XClick     ${!cmd_var2}      # native OS click
pause      500
echo       done
```

`storeText` only reads the element, so it is a presence check that cannot
itself produce an untrusted event.

### Completion: polling the log

There is no callback and no exit code — the extension reports by writing
`savelog`. `run_log.py` parses it with one distinction that matters: a log with
no verdict line yet means **still running**, not failed. Conflating the two
would make every slow macro look broken and would end the poll early. A stale
log is deleted *before* each run, and if it cannot be deleted the run is
refused rather than launched into an unreadable result (RULE 4).

### The no-automation-flags guarantee

`runner.LAUNCH_BANNED_FLAGS` lists `--start-debugger-server`, `--marionette`,
`--remote-debugging-port` and `--headless`; `launch_argv` raises if any appears.
This is deliberately stated as data and asserted on the real argv, so a future
"just add one flag" cannot quietly reintroduce a detectable browser. Five tests
fail if the guard is removed (verified by mutation).

## The 18th window

`uivision` — **"Firefox auto with Extension"** — registered in the one ordered
table (`window_catalog.WINDOWS`) and its four mirrors, `GRID_VERSION` 7 → 8, all
four JS preset layouts extended to 18 leaves. The **tab pattern is a control**,
as required: the operator states which URL the macro should open, matched
case-insensitively against the app's URL rows. A blank pattern matches
*nothing* rather than everything — a blank field must never silently select an
arbitrary tab.

Four slots (`get`/`save` settings, `get_uivision_macro`, `run_uivision_test`),
surface 137 → 141. The run slot returns as soon as the macro is scheduled and
the verdict arrives later on the `uivision_result` signal, because polling can
take the full timeout and must not block the UI thread.

## What this iteration is not

Per the user: *"create only this simple test of framework then it will be
replaced with same functional as chrome has now."* This ships the framework and
one proven action (XClick the Arena "New Chat" anchor). The Chrome-equivalent
feature set comes later.

## Requirements the user must satisfy

* the Ui.Vision extension (Firefox add-on) **and** the RealUser XModules —
  XClick/XType are native OS input and do nothing without them;
* Firefox **visible and in the foreground**, desktop unlocked — a real cursor
  cannot click a hidden window. (V10's background `uiv.browser.*` tier is
  Chrome/Edge only and unavailable here.)

## Removed

`app/browser/rdp/` (whole package), `endpoints.py`, `browser_scan.py`,
`services/browser_connect.py` and 14 test files — 26 files. `browser_tabs.py`,
`page_pool.py`, `config_manager.py` and the CDP JS listeners were restored to
their Chrome-only form, so `bridge.cdp.fetch_tabs()` is once again the single
unconditional tab path.

## Verification

* pytest **2133 passed**, 4 skipped, **0 failed**
* JS **345 passed, 0 failed** (the 9 long-standing failures were a missing
  `node_modules` — `npm ci` cleared them, as did the `test_40loc_js_function_fails`
  Python failure)
* coverage **89.45 % line** (from 88.83), branch 85.31; every new module
  100 % except `runner.py` 98.6
* quality gate: **0 fails on every file authored here** (6 pre-existing ratchet
  failures reproduce identically on a stashed clean tree)
* vulture clean; radon CC all A, no function above B
* RULE 18: all 7 new modules 43–152 lines, every function ≤ 20 LOC except one
  23-line macro builder that is mostly docstring

One real bug was caught by the panel tests before it shipped: `save_settings`
called `config.set_state(key, value)` positionally when the API takes kwargs,
so **no setting would ever have persisted**.
