# Firefox macro: reuse the found tab, never open a page — plus the RED confirmation rectangle (2026-09-23)

Owner report (verbatim, abridged): *"Why the script try open new url? It should use the tab
it found and click the element 'new chat' on this already opened page. Draw rect visual
confirmation the element was found. No need to open any new web pages."*

The failing run (2026-09-23 13:29) found the Arena tab, raised its window, then
**timed out** waiting for the savelog verdict — and the owner saw the macro trying to
open a new page instead of clicking **New Chat** on the tab that was already open.

## 1. Root cause

The generated macro carried a **URL-opening fallback**:

```
selectWindow | ${!cmd_var3} | ${!cmd_var1}        ← Value column = the run's URL
if           | ${!statusOK} == false
selectWindow | tab=open       | ${!cmd_var1}      ← open the URL in a FRESH tab
...
```

`selectWindow` with a `title=` target opens the Value URL in a new tab whenever the
title query comes up empty (A9T9/RPA `src/ext/bg.js` `PANEL_SELECT_WINDOW`), and the
explicit `tab=open` fallback did the same. So whenever the in-extension title probe
missed, the macro answered "open a new web page" — exactly what the owner does not want.
And the macro had **no find/confirm step at all**: it went straight from `pause` to
`XClick`, with no rectangle, no "element was found" evidence.

## 2. Evidence (verified against the A9T9/RPA source, master 2026-09-21 + official docs)

* `selectWindow | title=*X*` (Value left empty): queries tabs by title, wildcards per
  the docs; **zero matches throws `E210: failed to find the tab with locator …`** and
  opens nothing (`src/ext/bg.js` `PANEL_SELECT_WINDOW`). Only `tab=open` + Value opens
  a tab (`E211` without a URL). → an empty Value column is the source-level guarantee
  of "never open a page".
* `highlight` is **not a registered command** in V10 (`src/common/command.ts`
  `commandScopes`); its docs page says the IDE's replay highlighting covers it.
* The replay highlight (Settings → Replay, `playHighlightElements`, **default ON**)
  draws a 500 ms mask over an element whenever a command resolves one — including the
  internal `locate` step of an element-locator `XClick`
  (`src/ext/content_script/command_runner.js` `case 'locate'`). Nice, but: 500 ms,
  and switchable off in the extension's settings — not the deterministic confirmation
  the owner asked for.
* `XClick | <element locator>`: the extension resolves the locator (implicit wait,
  `!timeout_wait`), takes the rect centre and fires a **native OS click** — the strict
  gate already exists in the macro; its honest not-found verdict is
  "timeout reached when waiting for element … to be present" (`Status=Error`).
* `executeScript` is a registered command (`CommandScope.All`) and the engine wraps the
  code in `Promise.resolve((function () { … })())` — a **returned promise is awaited**
  (up to `!timeout_wait`, default 30 s), and a thrown error becomes
  `Status=Error: Error in executeScript code: …` (`src/ext/content_script/command_runner.js`
  `case 'executeScript'`).
* Variable rendering inside `executeScript` uses `shouldStringify` — `${!cmd_varN}` is
  substituted as `JSON.stringify(value)`, i.e. a ready JS string literal
  (`src/common/variables.js` `render`); `replaceEscapedChar` is skipped for
  `executeScript` targets, so the JS text arrives byte-exact.
* **`cmd_var4…10` are whitelisted but NOT seeded** into the macro scope: the override
  scope only matches `^cmd_var(1|2|3)$` (`src/index.js` `genOverrideScope`). The macro
  therefore gets exactly `!CMD_VAR1..3`. With cmd_var1 freed from the URL it carries
  the pause budget.
* `INVOKE_URL_PARAMS` (whitelist, `src/common/constant.ts`): `direct`, `closeRPA`,
  `savelog`, `storage`, `macro`, `cmd_var1…10` — everything used is on it.

## 3. Design

**D-1 — The macro never opens anything.** `selectWindow | ${!cmd_var3}` with an
**empty Value column**; no `tab=open`, no `open`, no URL command. Missing tab →
`E210` → `Status=Error` in the savelog → the run reports `error` (RULE 4: "no matching
tab" is a named answer, not a timeout and not a fresh page). A blank window-title
pattern is **blocked in Python before launch** (the macro could never find its tab and
must never open one to compensate).

**D-2 — The RED confirmation rectangle is one `executeScript`.** The script (a JS
literal in `macro.py`, the 16.1.5 embedded-JS exception) waits up to the run's pause
budget for the target element, then draws the app's own find-rectangle —
**`#ff2d2d` border, `pointer-events:none`, transparent** (RULE 1's `COLOR_FIND`, the
same outline the Chrome visual runner draws — one visual language across both
pipelines) over the element's bounding box (viewport-`fixed` div, so no scroll math),
holding it for the rest of the budget. It resolves the locator itself
(`xpath=` / `id=` / `css=` / `dom=` / `text=` / `link=` — the element-locator half of
Ui.Vision's grammar); targets that are **not** element locators (image `x.png@@0.8`,
OCR text, raw `x,y`) are skipped — the extension draws its own vision boxes for those
(`visualAssert`'s green box on the `XClick` image path).

**D-3 — Best effort: the script never fails the run.** Any internal error resolves to
"skipped: …" instead of throwing; the element's absence is not a macro failure —
the **`XClick`'s own lookup is the strict gate** (extension implicit wait + honest
`Status=Error`). The observation never stops the action (RULE 9's fail-open shape).

**D-4 — One control per decision (RULE 10).** The `url` field, `RunSpec.url`,
`LaunchSpec.url` and `cmd_var1=<url>` are **deleted**, not kept-but-ignored; the
retired key is dropped on validate so old `session.json` files never re-persist it
(RULE 10's dead-key corollary, RULE 13's tolerant load). The `pause_ms` field keeps
its one job — re-labelled "Wait for element + confirm rect (ms)" — and rides the freed
`cmd_var1` slot. `tab_target()` returns `None` for a blank pattern (it used to invent
`tab=open`).

**D-5 — Values still ride the command line.** The on-disk macro stays generic:
`${!cmd_var1}` = pause budget ms, `${!cmd_var2}` = the XClick locator,
`${!cmd_var3}` = the tab target — all rendered by the extension at run time
(`shouldStringify` ⇒ the locator arrives as a JSON string literal into the JS).

### The macro after (was 11 commands, now 5)

```
selectWindow               | ${!cmd_var3} | ""            reuse the tab — never open
bringBrowserToForeground                                     native input needs front
executeScript              | <FIND_RECT_JS>                wait for the element, draw RED rect
XClick                     | ${!cmd_var2}                  native OS click (the gate)
echo                       | done …                        savelog completion marker
```

## 4. Metrics (radon, before → after; after = measured on the landed code)

| file | before | after |
|---|---|---|
| `uivision/macro.py` | 116 LOC, all functions A (CC ≤ 3) | 206 LOC (JS literal dominates), functions A |
| `uivision/autorun.py` | 148 LOC, A | 152 LOC, A |
| `uivision/runner.py` | 313 LOC (legacy-size, unchanged metrics) | 334 LOC, `run_test` held to its legacy ≤30-LOC ratchet via the `_blocked_no_pattern` helper |
| `ui/panels/firefox_auto.py` | 198 LOC, A | ~200 LOC, A (no new CC — the retired-key drop rides the defaults rebuild) |

`_provision`/`_launch`/`run_test` keep their parameter counts (≤ 4, RULE 16).
No new class, no new method on a legacy hotspot.

## 5. Tests (RULE 8 — execute the real thing)

* `test_uivision_macro.py` — the 5-command sequence; **Value column of selectWindow is
  empty** (the never-open guarantee); no `open`/`tab=open` command anywhere; the
  `executeScript` target carries the locator + budget references and the `#ff2d2d`
  colour; DOM-mouse-command refusal unchanged; `render_find_rect_js` mirrors the
  extension's `JSON.stringify` rendering (a positive control: the rendered JS contains
  the locator as a quoted literal).
* **New Node lane `tests/js/test_find_rect.mjs`** — the rendered payload is generated
  by the real Python builder and **executed** in a `vm` against a stub DOM: element
  found ⇒ one `#ff2d2d` rectangle appended over the element, removed by its timer;
  element absent ⇒ resolves "not found" (never throws); image-style target ⇒
  resolves "skipped"; `text=` locator resolves through the stub `document.evaluate`.
* `tests/test_js_payload_syntax.py` — the rendered payload joins `payloads()` (bracket
  lane always, `node --check` lane when node exists); `uivision.macro` joins
  `_BUILDERS_COVERED`.
* `test_uivision_autorun.py` — launch URL carries `cmd_var1=<pause ms>`, `cmd_var2`,
  `cmd_var3` and **no URL**; `test_uivision_runner.py` — blank pattern ⇒ `blocked`
  before launch with no files written; `test_firefox_auto_panel.py` — `url` dropped
  from defaults, retired key not re-persisted.
* `tests/js/test_firefox_auto_panel.mjs` — `faUrl` out of the id table.

## 6. Deviations / notes

* The **autorun page tab** (`ui.vision.html`) is the extension's own command-line
  contract — the running Firefox opens it, and `closeRPA=1` closes it after the run.
  It is not a "new web page" in the sense the owner meant (the run's URL); it stays.
* The extension's own 500 ms replay mask may draw **on top of** the macro's rectangle
  during the XClick step (Settings → Replay highlight, default ON) — two reds, same
  element, no harm.
* `XClick` with an image/OCR/coordinate target still has no macro-drawn rectangle —
  the extension's vision box covers it; the window help says so.
* If the owner later wants the rectangle colour/duration user-configurable, that is a
  new field — not added now (RULE 10).
* Stop ordering kept as on HEAD: **detect always runs first**, the stop check follows
  (the "detect runs, then stop wins" contract the runner tests pin), then the
  blank-pattern block — so a run that is both stopped and unsatisfiable answers
  `stopped`, and an unsatisfied run with no stop writes no files and never launches.
