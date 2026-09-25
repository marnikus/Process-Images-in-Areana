# Design — Firefox auto: protected tabs, pattern-driven locators, one run per running profile

Date: 2026-09-24 · Owner report: *recurring critical — (1) macro closes user-opened tabs on
error, (2) TAB TITLE/URL PATTERN from the UI never applied to the launch, (3) first run always
fails: the autostart page opens N times on the FIRST profile, the macro is re-clicked there,
other profiles are never reached. "Not fixed after two attempts — rebuild the logic."*

## Verified facts about the Ui.Vision extension (deep research, 2026-09-24)

Source: `github.com/A9T9/RPA` — tag **V9.6.1** (the build whose error codes match the owner's
log: E212) and **main/V10**, plus Firefox sources and docs:

| # | Fact | Evidence |
|---|---|---|
| F1 | `selectWindow` accepts exactly two locator types: `title=<glob>` and `tab=<relative offset \| open \| CLOSE \| CLOSEALLOTHER>`. **Any other type (e.g. `url=…`) throws `E209: window locator type 'url' not supported`.** | V9.6.1 `src/ext/bg.js` `case 'PANEL_SELECT_WINDOW'` switch (`title`/`tab`/`default → E209`); identical in V10 main. |
| F2 | No matching tab → `E210`; in V9 the catch path frequently re-surfaces it as **`E212`** (the code in the owner's log). | V9.6.1 `bg.js` `E210` throw + the `E212` catch fallback (`parseInt(locator)` is NaN for `title=…` → the fallback throws E212). |
| F3 | Firefox `browser.tabs.query({title})` does **glob** matching (`*` wildcards, case-sensitive) since **Firefox 59**; `tabs.query({url})` also supports match patterns but `selectWindow` never exposes it (F1). | Bugzilla 1334782 (VERIFIED FIXED, milestone mozilla59: `queryInfo.title = new MatchGlob(…)`); MDN `tabs/query` ("Match page titles against a pattern"). |
| F4 | `closeRPA=1` closes **only the RPA panel**, and only on `END_REASON.COMPLETE`; `closeBrowser=1` (which we never send) closes all windows. A macro error closes nothing. | V9.6.1 `src/index.js` `genPlayerPlayCallback` (`!err && reason === COMPLETE && closeRPA && !closeBrowser → window.close()`). |
| F5 | On the `file:` autorun page, `kantuInvokeSuccess` fires **when the macro is dispatched, not when it finishes**; `kantuInvokeError` is never dispatched in V9. The only honest completion contract is the **savelog file**. | V9.6.1 `src/ext/content_script/index.js` `bindInvokeEvent` (dispatches `kantuInvokeSuccess` first, before `CS_INVOKE`). |
| F6 | `CS_INVOKE` sets `firstPlay`/`toPlay` to the **invoking tab** (the autorun tab); `tab=N` offsets are anchored there. | V9.6.1 `bg.js` `case 'CS_INVOKE'`. |
| F7 | `selectWindow TAB=CLOSE` closes the **current** tab; if it is the only tab left it closes the browser. `TAB=CLOSEALLOTHER` closes every other tab. | V9.6.1 `bg.js`; official selectWindow docs page. |
| F8 | The invoke-URL whitelist (`INVOKE_URL_PARAMS`) is `macro, storage, direct, savelog, cmd_var1..10, closeRPA, …` — **unknown parameters ride the URL harmlessly** (the extension ignores them; the page's own JS can read them). | V9.6.1/V10 `src/common/constant.ts`. |

Consequence for the owner's literal "use `url=*{pattern}*`" request: **the installed extension
refuses a `url=` locator with E209** (F1) — the same failure class as E212, a different code.
The URL pattern therefore decides *which tab* in Python (matching), and the locator that rides
`cmd_var3` is the transport the extension actually accepts (F1/F3): a `title=` glob.

## Root causes (why two attempts did not fix it)

1. **Locator auto-construction (bug #2).** With a blank title pattern, `plan.selector_for`
   fell back to the **40-char clipped** session-store title (`title=*Directly Chat with
   Frontier Image Genera*`) — a machine-built fragment of the detected title, not the
   user's configured pattern. Any staleness or format drift in the live tab title → E210/E212.
2. **Wrong completion event (bug #1's cleanup path).** The vendor autostart page treated
   `kantuInvokeSuccess` as "macro finished" (F5 says: it fires at dispatch) and closed the
   autorun tab 500 ms after *start*; there was **no** cleanup that closed exactly the tab the
   run opened after the work, and nothing prevented the extension's stale `firstPlay` state
   (F6) from making a later run's cleanup target a **user** tab. Combined with the
   over-clicking of bug #3, mis-landed native XClicks and close commands acted on user tabs.
3. **Per-TAB run unit + all SAVED profiles (bug #3).** The plan made one run per matching
   **tab** (a profile with two matching windows/tabs → two runs → "first profile over-clicked"),
   and detection read the session stores of **every saved** profile — a closed profile's stale
   `recovery.jsonlz4` looked like open tabs, so phantom targets were planned and `-P` launches
   for dead profiles raced the first live instance. The owner's model: **every profile found
   with a matching tab is reached exactly once, and only OPEN profiles count.**

## The rebuild

### 1. Tab pattern resolution — the locator comes from the owner's patterns (one place)

`plan.selector_for(target, title_pattern, url_pattern)` is the ONE locator builder:

| title pattern | URL pattern | locator (`cmd_var3`) |
|---|---|---|
| `X` | *(blank)* | `title=*X*` — the user's pattern, verbatim (F3: Firefox globs `title=` since 59) |
| *(blank)* | `Y` | `title=*(full title of the tab whose URL matched Y)*` — the owner's URL pattern is the deciding filter; `url=` is refused by the extension (F1), so the transport is the matched tab's **full, unclipped** title, re-read at launch |
| `X` | `Y` | URL wins (owner's priority) → same as row 2; Python matching still requires BOTH |
| *(blank)* | *(blank)* | the profile's first open tab, by its full title (the "any tab" escape hatch, loud warning kept) |

The 40-char clip (`TITLE_SELECTOR_MAX`) is **deleted** — it was the E212 trigger. The
launch-time re-check (below) re-reads the store so the transport title is seconds fresh, not
detect-time stale.

### 2. Protected tab rule — only the tab the run opened may ever close (proof by enumeration)

After the change, the complete set of close actions in the system is:

1. **The macro's pinned final cleanup pair** (new, in `macro.build_commands`):
   `selectWindow title=*Ui.Vision Autostart Page*` → `selectWindow TAB=CLOSE`.
   It selects the autorun tab by the page's own fixed title (a tab this system opened) and
   closes it — after the click and the `echo done` marker, before the savelog verdict is
   written (the savelog is written by the panel/background, F4, not by the tab). If earlier
   failed runs left orphaned autorun tabs, the query's first match closes one of **those** —
   still a system-opened tab; the orphans eat themselves, one per successful run.
   `TAB=CLOSE` can only kill the browser if the autorun tab is the last tab in its window —
   impossible in practice because `-new-tab` joins a window that already holds the
   user's tabs (the run's precondition); documented edge: an emptied window closes.
2. **The autorun page's backstop timer** (new `autoclose=<sec>` URL param, F8: the
   extension ignores it, the page reads it): closes **itself** (`window.close()` — a tab can
   only be closed by a script running in that tab) after `timeout + 120 s`, and only while
   its own `document.title` is still "Ui.Vision Autostart Page". It is the failure-path
   cleanup: if the macro stops early (E210/E212), the orphan is removed after the verdict
   window; on success the macro's cleanup already closed it (the timer is moot).

Everything else is proven incapable of closing a user tab:

* the macro contains **no** other close command — the builder now refuses `open`/`open*`
  commands, `TAB=CLOSEALLOTHER` anywhere, and `TAB=CLOSE` outside the pinned final pair, and
  pins the exact 7-command shape (drift is a deliberate, reviewable change);
* the launch URL sends `closeRPA=1` (panel only, F4) and never `closeBrowser`;
* the old `onInvokeSuccess`/`onInvokeError` self-closes are **deleted** (F5: that event fired
  at dispatch, so the old page tore down the autorun tab 500 ms into a live macro).

Result: no script the system controls runs in any tab other than the autorun tab, and the
only close commands target the autorun tab — a user-prepared tab cannot be closed by this
system (a mis-aimed native XClick remains an OS-level possibility; the RED confirm rect, the
foreground rule and the now-correct per-profile targeting are the mitigations).

### 3. One run per running profile (bug #3)

* **Open-profile filter** — new `app/browser/uivision/profile_lock.py` (OS-level, no
  debugger): Firefox writes `<profile>/lock.ini` (`<hostname>:<pid>`) for the whole lifetime
  of a running instance and deletes it on clean shutdown — the browser's own "this profile is
  running" receipt, in the spirit of the app's read-only-on-OS-files philosophy.
  `profile_open()` → `(open, reason)`: no lock → not running; unparseable lock → not running;
  lock pid dead → stale lock → not running; pid alive → running (Windows: `OpenProcess` +
  best-effort `QueryFullProcessImageNameW`, so a **reused PID owned by a non-Firefox process**
  is treated as a stale lock; POSIX: `os.kill(pid, 0)`).
  `tabs.open_profile_sessions()` = `profile_sessions()` filtered to open profiles; a closed
  profile's stale store is **invisible** — the phantom targets of bug #3 cannot exist.
  Detection reports both sides: `firefox profiles: N running (…)` + `M not running —
  skipped (…)`. The profile list slot shows **open profiles only** (owner's on-screen rule);
  a selected-but-not-running profile is named in the skip/wait reports, and is **never
  launched** — the wait phase only catches it if the user actually starts it (its store
  appears in `open_profile_sessions()` while the poll runs).
* **Per-profile run unit** — `plan.plan_targets` returns **one Target per profile**: the
  first matching tab **with a non-empty title** (a titleless match cannot be selected, F1 —
  a profile whose matches are all titleless gets no run and a named warning). A profile with
  several matching tabs still gets exactly one run ("every profile found with a tab — exact
  one time"); the extras are reported, not clicked. `plan.match_counts` carries the warning
  data. `plan.clashes` is **deleted** (with one run per profile, two runs sharing a selector
  inside one profile is structurally impossible — dead code, RULE 16.4).
* **Handoff verification** — after a profile-targeted launch, `Sequence._handoff_misrouted`
  polls the running profiles' stores (1 s cadence, 8 s window) for the autorun marker
  (`ui.vision.html` in a tab URL): marker in the target profile → confirmed, proceed; marker
  in **another** profile → verdict `error` naming both profiles and the fix (duplicate
  `profiles.ini Name=` entries make `-P` routing ambiguous), and the rest of the sequence
  **aborts** — the same routing would fail again, and the old failure mode (silent
  over-clicking in the wrong account) is gone. No marker in the window → proceed; the
  savelog remains the verdict (no invented failure).

### 4. Launch-time tab re-check (the E212 class, closed)

`Sequence._fresh_locator`, real paths only (seams keep deterministic fixtures): re-read the
target profile's lock + store right before launch. Profile no longer open → the run is
skipped as `blocked` **without launching** ("the profile is not running any more — skipped");
the tab's URL row gone → skipped ("the tab … is gone — skipped"); title changed → the
locator is rebuilt from the fresh full title and a line is logged. A skipped run does **not**
abort the sequence (a launch refusal still does — same binary would refuse again);
`LogResult.abort_rest` distinguishes the two (RULE 4: distinct answers).

### 5. Autorun page contract (F5/F8)

`PAGE_HTML` keeps the vendor retry logic (extension-not-loaded `reload≤3`, the #203/#204
alerts, the `kantuSaveAndRunMacro` dispatch + 1 s re-dispatch interval). The interval and the
file-URL alert clear on `kantuInvokeSuccess` (accepted) — **no close**. New: the `autoclose`
backstop (item 2). `LaunchSpec.backstop_sec` (appended last, positional-safe) → `autoclose`
query param only when > 0; the runner sets `timeout_sec + 120`.

## Rejected alternatives (honesty, RULE 19)

* **Literal `url=*{pattern}*` in `cmd_var3`** — refused by the extension with E209 (F1) in
  both V9 and V10; it would have traded E212 for E209.
* **`selectWindow tab=N` relative offsets** — re-rejected (2026-09-23): anchored to
  `firstPlay` (F6), which the extension's **stale** state can point at a user tab — the exact
  protected-tab violation this fix removes; also window-scoped.
* **Keeping the 40-char clip** — the clip is what made `*Directly Chat with Frontier Image
  Genera*` a fragment of a detected title; full unclipped titles are strictly more specific
  as globs (F3).
* **Waiting out stale stores instead of the lock** — a running-but-idle Firefox may not
  rewrite `recovery.jsonlz4`; an mtime threshold would false-negative real profiles (the
  "other profiles never reached" failure again). `lock.ini` is deterministic.
* **One run per matching tab (old model)** — contradicts the owner's "every profile … exact
  one time" and is the direct source of the over-clicked first profile.

## Gates (RULE 16)

`tools/verify_quality.py --changed --allow-legacy` + `pytest` + coverage (per-file floors for
the touched uivision files are 98–100 % — every new line is test-covered, incl. the Windows
pid path via a stubbed `ctypes.windll`). New functions ≤ 20 LOC / CC ≤ 10 / nesting ≤ 4 /
params ≤ 4 (radon, below); the package grows 12 → 13 files (ideal 5–15). RED-first tests:
`tests/test_uivision_profile_lock.py` (new), updated `test_uivision_plan.py` (locator
priority matrix, per-profile dedup, no clip), `test_uivision_macro.py` (shape gate + cleanup
pair), `test_uivision_autorun.py` (backstop param, no dispatch-close), `test_uivision_runner.py`
(one run per profile, closed-profile invisibility, gone-target skip-continue, handoff
misroute/confirm/proceed, title refresh), `test_uivision_profiles.py` (open-only list).
