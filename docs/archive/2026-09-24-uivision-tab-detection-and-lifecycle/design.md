# Design — Ui.Vision tab detection (full title, no truncation) + protected-tab lifecycle

Date: 2026-09-24 · Owner bug report — recurring (not fixed after two attempts).
Two interconnected failures in the **Firefox auto with Extension** window's
framework-test runner:

1. **Tab title is truncated to 40 chars, breaking `selectWindow`.** With
   `Tab title pattern` blank and `Tab URL pattern` = `arena.ai/image`, the
   macro's `cmd_var3` is built from the tab's **40-char truncated title**
   (`title=*Directly Chat with Frontier Image Genera*`, the session
   store's clip). The actual tab title is *longer* — Ui.Vision's
   `selectWindow` is a substring glob (`title=*…*`), but the truncated
   anchor stops at an arbitrary character boundary inside the marketing
   copy and on a slow page (the user's "first run fails, subsequent runs
   work" report — the autorun page reloads three times before the tab's
   real title settles) the substring misses, the macro fails with **E212**.
   The URL pattern from the UI config is **never used** as the selector
   in this case — the runner falls back to the truncated tab title.
2. **Tab closure on macro stop/error.** When the macro aborts on the
   first run, the autorun page's error path runs `window.close()` *and*
   `window.location.href = 'about:blank'`. The `about:blank` fallback
   navigates the page even when `window.close()` is a no-op (Firefox
   refuses to close a tab opened by another component), which can race
   the extension's cleanup and overwrite the user-prepared tab. The
   user's Arena session, login state and in-progress generation are
   destroyed.

Both fixes ship in one change because both stem from the same
misunderstanding of the `selectWindow` contract.

## Semantics (the owner's rule, as code)

### Tab pattern resolution — full title, never truncated

Ui.Vision's `selectWindow` matches on **`document.title` only** (the A9T9
source, `src/ext/playback/playback.js`, matches by `tab.title` with
`title=*<glob>*` substring wildcards). There is no `url=` selector and
no `tab=url=` selector. The correct selector for one tab is therefore
always `title=*<glob>*`. Priority:

| TAB TITLE PATTERN | TAB URL PATTERN | what `cmd_var3` becomes |
|---|---|---|
| `X` | *(blank)* | `title=*X*` (today's behaviour, unchanged) |
| `X` | `Y` | `title=*X*` — title wins (the narrower, explicit signal) |
| *(blank)* | `Y` | `title=*<tab's full title>*` (was the 40-char clip) |
| *(blank)* | `Y` + tab has no title | `title=*Y*` — URL pattern rides the title glob (the only anchor we have for `about:blank`) |
| *(blank)* | *(blank)* | today: every open tab, with a loud warning; unchanged |

Two specific changes:

1. **Remove the arbitrary 40-char truncation.** Ui.Vision's
   `title=*<full title>*` matches by substring definition; a 40-char
   clip that cuts in the middle of a distinctive token was the bug. The
   previous `TITLE_SELECTOR_MAX = 40` constant is deleted. The fallback
   single-run selector (no targets, just the user's pattern) stays
   exact and untruncated.
2. **URL pattern is the last-resort title glob.** A tab matched by URL
   whose title is empty (e.g. `about:blank` just opened) has no title
   to anchor `selectWindow` on — the URL pattern is the only signal
   the user gave us, and it rides the title glob. A tab matched by URL
   *with* a title keeps its full title (the title is more specific than
   a URL substring shared by every matching tab).

### Protected-tab rule — never close what existed before launch

The autorun page is the **only** tab the run is allowed to close, and
only on success; on error the autorun page stays where it is so the
user can read the verdict. Concretely:

* The autorun page's success path keeps `window.close() + about:blank`
  (the page itself, opened by the command-line API).
* The autorun page's **error path no longer closes or navigates**. It
  just dismisses the timers and stays visible until the user closes it
  manually — this matches the Ui.Vision docs' documented UX: *"the
  Ui.Vision RPA window stays open if you manually press STOP during
  the macro run or if the macro stops with an error"*. The `Error #203`
  timer is kept so a missing file-URL permission still surfaces.
* `closeRPA=1` stays in the launch URL (it closes the extension's own
  popup, not browser tabs).

Combined effect: the user's prepared tab is never touched by the
runner, whether the macro succeeds, errors or times out.

### Multi-profile advancement — first run no longer cycles on one profile

The recurring "first run fails, subsequent runs work" symptom is closed
by the two changes above working together:

1. **The full-title selector is stable.** When the pattern is blank and
   the tab has a title, the selector is the tab's own title — the same
   tab cannot be re-addressed by the same selector on a re-pass (the
   `plan.clashes` warning already names this).
2. **A per-`run_test` `seen` set drops already-planned targets before
   the planned-run loop.** `plan.dedupe_targets(targets, seen)` removes
   any `(profile_dir, url)` already in `seen`; the runner records every
   target it actually plans, then a re-pass of the same call (which
   the owner's report describes) no longer re-plans the same tab. One
   helper, one place: `runner.run_test`.

## Changes

### `app/browser/uivision/plan.py`

* `selector_for(target, pattern, url_pattern="")` — three-tier priority
  (title > full tab title > URL pattern); `url_pattern` is appended
  last so positional constructors survive. `TITLE_SELECTOR_MAX` is
  removed.
* `dedupe_targets(targets, seen)` — pure filter for the no-cycle gate.
* `split_unaddressable`, `clashes` — pass `url_pattern` through.
* `runs(targets, pattern, config_dir, stamp, url_pattern="")` — same
  trailing-optional pattern.
* `run_label`, `summarize` — unchanged (read `title` for display only).

### `app/browser/uivision/runner.py`

* `run_test` — builds a `seen: set[(profile_dir, url)]` from the
  freshly-detected session rows, calls `plan.dedupe_targets` once,
  passes `url_pattern` to `plan.runs`. The detect phase still reports
  the full target list; dedupe is a `seen`-aware filter that runs
  before the planned-run loop.
* `_drop_unaddressable`, `_report_clashes` — pass `url_pattern`
  through.
* `_fallback_or_block`, `_detect_phase`, `_provision` — unchanged.

### `app/browser/uivision/autorun.py`

* `PAGE_HTML` — the success path keeps `window.close() + about:blank`;
  the error path **drops both calls**, leaving the page visible with
  the error message. The 8 s `Error #203` timer is kept on both paths
  so a missing file-URL permission still surfaces.

### Runtime-file lifecycle — what gets regenerated, what doesn't

Three files are produced by the app and live OUTSIDE the git tree
(config/* and the XModule home are both git-ignored). This matters
because an older chat session may have left an older copy on disk, and
the fix has to reach that copy too. The three paths are:

| File | Path | Writer | Self-heals on next run? |
|---|---|---|---|
| **Autorun page** | `<config>/uivision/ui.vision.html` | `autorun.write_page()` (idempotent — rewrites when content differs) | YES — first run after the code update picks up the new `PAGE_HTML` |
| **Macro file (xfile)** | `<User Desktop>/uivision/macros/<Name>.json` | `runner._provision()` (`target.write_text(...)` UNCONDITIONAL on every run) | YES — first run after the code update picks up the new `build_macro()` |
| **Macro file (browser)** | `<config>/uivision/macros/<Name>.json` | `runner._provision()` writes the **import artefact**, but the extension keeps its own copy in HTML5 storage | **NO** — user must delete the old macro in the Ui.Vision UI (Macros tab) and re-import the new one |

The macro file itself is selector-neutral: it only carries
`selectWindow ${!cmd_var3}` (a placeholder). The actual `title=*…*`
string is built at launch time by `plan.selector_for(target, pattern,
url_pattern)` and passed via the launch URL. So even with an OLD macro
file on disk, the NEW selector reaches the extension on the very next
run — both the full-title fix (Bug #2) and the priority order apply
immediately. The autorun page's error-path fix is the same: the
`onInvokeError` handler is in the rewritten page (idempotent
`write_page`), so the first run after the code update gets the new
behavior.

The one path that does NOT self-heal is `storage=browser`: the
extension imported the macro into its HTML5 storage once, and that
copy is what runs. The detect log line `storage=browser: import this
macro ONCE in the Ui.Vision UI` already names this; the design does
not change that contract, because Ui.Vision's extension has no public
way to overwrite an imported macro from the command line. The fix
instructions for an existing browser-storage user are: open Ui.Vision
→ Macros → delete `Python_XClick_Demo` → Run from this app once (the
new file lands at `<config>/uivision/macros/<Name>.json`) → import
once. After that the new copy is used.

### `tests/`

* `tests/test_uivision_plan.py` — `selector_for` matrix (title-only /
  url-only / both / neither); `dedupe_targets` cases.
* `tests/test_uivision_runner.py` — full-title happy path (cmd_var3 is
  `title=*<full title>*`, no truncation); URL-pattern as last-resort
  title glob (titleless tab now runs, not skipped).
* `tests/test_uivision_autorun.py` — the autorun page contract on
  error: no `window.close()` in the error handler, `Error #203` alert
  still present.

### No changes

* `app/ui/panels/firefox_auto.py`, `app/ui/web/js/panels/firefox-auto.js`,
  `app/ui/web/index.html` — the two fields and their config keys stay
  as they are (`pattern`, `url_pattern`); only the meaning of
  `cmd_var3` changes.
* `launch.py`, `paths.py`, `macro.py`, `logread.py`, `desktop.py`,
  `tabs.py`, `profiles.py` — out of scope.

## Sizes (RULE 18) and gates (RULE 16)

* `plan.selector_for` ≤ 14 LOC, CC ≤ 6 (priority chain, not nested).
* `plan.dedupe_targets` ≤ 12 LOC, CC ≤ 5 (one comprehension, one set).
* `runner.run_test` keeps its single-purpose detect + provision +
  sequence shape; the dedupe is one extra line.
* New tests: ≥ 6 (selector matrix + URL-as-glob + dedupe + happy paths).
* Coverage: existing `test_uivision_runner.py` already covers both
  patterns; new tests cover the no-truncation contract and the
  multi-profile advancement regression.

The autorun page is one string literal (the existing 16.1.5 exception
applies — embedded JS payload, splitting the string would break the
in-page agent contract).
