# Design — protected tabs, URL-first tab selection, one run per open profile (2026-09-24)

**Status:** implemented 2026-09-24 · supersedes `2026-09-24-uivision-url-pattern` (its
selectWindow-title-only shapes are retired)
**Entry:** SYSTEM_OF_RECORD.md → `Firefox auto with Extension` (I-62, I-63)

Four bugs stayed fixed after two attempts. All four root causes are now verified
against the shipped Ui.Vision extension source (AMO 10.0.276 == github.com/A9T9/RPA
tag, `src/` layout — confirmed identical via AMO API), so this design states exact
code-line causes, not theories.

## Root causes (source-verified)

1. **Protected tab closed on macro error** — our launch URL never sets
   `continueInLastUsedTab`. The extension's `decorateOptions`
   (`ext/content_script/index.js:1374`) defaults it to `'1'`; `prepareByOptions`
   (`src/index.js:630`, `parseBoolLike`) then asks the background for
   `PANEL_CLOSE_CURRENT_TAB_AND_SWITCH_TO_LAST_PLAYED` (`ext/bg.js:2056`), which
   closes the tab about to play (`toPlay`) when it differs from `lastPlay`. On a
   first run with the user's prepared tab that is *their* tab → "closing our
   tabs which have been already opened". Param is whitelisted
   (`constant.ts:30`); `parseBoolLike('0')` → false → no close.
2. **TAB URL PATTERN never used as locator** — `plan.selector_for(target, pattern,
   url_pattern)` only ever considered `pattern`; the macro's sole `selectWindow`
   target (`${!cmd_var3}`) therefore comes from the title pattern, else the clipped
   detected tab title — exactly the user's report (`title=*Directly Chat…*`).
   Ui.Vision `selectWindow` supports `title=`/`tab=` only (forum + source
   `PANEL_SELECT_WINDOW`, `bg.js:2350`): a literal `url=` yields **E209** every
   run, so the URL attempt must be the macro's *guarded first try*, not the only try.
3. **First-run repeats one profile** — `plan_targets` returns one `Target` per
   *matching tab*; `runs()` renders one macro run per target, so a profile with
   N matches (or the same title matching several tabs) re-runs N times while
   other profiles are queued behind it. The run order makes the repeats look
   like "stuck on profile one".
4. **"Find all profiles" lists closed profiles** — `tabs.profile_sessions()`
   reads every on-disk profile dir (`profile_dirs()`); Firefox's session store
   survives crash/shutdown, so stale profiles still "answer".

## Decisions

* **D1 — Bug #1:** `autorun.launch_url` always passes `continueInLastUsedTab=0`
  (string, like the extension's own `'0'`). Never `closeBrowser`/`closeRPA` tricks.
  The autorun page's self-close stays spawn-only (it closes *its own* tab after
  invoke; its comment is corrected — it does not wait for macro end).
* **D2 — Bug #2 (hybrid, race-free):** the `url=` primary is **baked into the macro
  file** (per-invocation constant; there is no 4th `cmd_var` slot —
  `genOverrideScope` seeds only `cmd_var1..3`), bracketed by the official
  errorignore idiom (`store true/false !errorIgnore`, shipped pattern
  `preinstall_macros.js:1371-1389`, `isBoolean` accepts `'true'/'false'`):
  `store true !errorignore` → `selectWindow url=*U*` (E209 today → caught,
  logged `[error][ignored]`, run continues — trace:
  `modules/run_command.ts:275` sets `extra.errorIgnore` from `!ERRORIGNORE` →
  `popup/run_command.ts:583` catch returns `{log:{error}}` → `players.tsx:494`
  logs `{ignored:true}` → `src/index.js:451` Status stays OK) → `store false
  !errorignore` → **hard** `selectWindow ${!cmd_var3}` → existing tail.
  **`cmd_var3` = hard fallback only** (today's semantics: title pattern if set,
  else the matched tab's title) — never a detected-foreground construction when a
  pattern exists. Title-only/blank configs keep today's single command (no dance).
  Rules still hold: no `tab=open`, no DOM click, no bare `url=` at runtime.
* **D3 — Bug #3:** `plan.one_per_profile(targets)` keeps the **first matching tab
  per profile** (session order) after profile-filter + unaddressable split; every
  target list that reaches `runs()` is deduped. `plan.clashes` dies with duplicate
  tabs and is deleted (RULE 16.4). The match report still shows *all* matches.
* **D4 — Bug #4:** profiles are **open iff their Firefox lock is held**
  (`toolkit/profile/nsProfileLock.cpp`, full source read): Unix `.parentlock`
  (macOS also `.parentlock`, old `lock`) held via `F_SETLK` — probe with a
  test lock, `EAGAIN/EACCES` ⇒ in use, file absent ⇒ not in use, other errno ⇒
  fall back to the legacy `lock` symlink existing; Windows `parent.lock` held as
  an unshared handle for the process lifetime (never deleted) — try
  `os.open(O_RDWR)`, success ⇒ free, `PermissionError`/sharing violation ⇒ in
  use, absent ⇒ not in use. Presence proves nothing; the test decides. New seams:
  `tabs.profile_in_use(profile, probe=None)`, `tabs.open_profile_dirs(in_use=None)`,
  `profiles.open_sessions(sessions, in_use=None)`; `profiles.list_profiles(in_use=None)`
  and the runner's real `_load_profiles` filter through it (test seam:
  `in_use=lambda p: True`). `addon_seen` stays on all dirs (static check).
* **D5 — threading:** `plan.Patterns` (frozen dataclass: `title`, `url`) replaces
  the `(pattern, url_pattern)` pairs so every planner takes ≤4 params
  (RULE 16.1). Runner builds it once from the spec.
* **D6 — evidence:** the launch line shows the primary locator and the fallback,
  e.g. `tab=url=*arena.ai/image* → title=*Arena*`, so both attempts are visible.

## File-by-file

| File | Change |
| --- | --- |
| `app/browser/uivision/plan.py` | `Patterns` dataclass; `matches/describe_search/selector_for/plan_targets/split_unaddressable/runs` take `patterns`; new `one_per_profile`; delete `clashes` |
| `app/browser/uivision/macro.py` | `build_commands(patterns=None, done_text=)` injects the errorignore-bracketed `url=*U*` attempt; `build_macro(name, patterns, today, done_text)` ≤4 params; refuse_dom_clicks unchanged (still forbids `open`) |
| `app/browser/uivision/autorun.py` | `launch_url` adds `continueInLastUsedTab=0`; self-close comment corrected |
| `app/browser/uivision/tabs.py` | `profile_in_use` + unix/win lock probes + `open_profile_dirs` |
| `app/browser/uivision/profiles.py` | `open_sessions`; `list_profiles(in_use=None)` = open profiles only |
| `app/browser/uivision/runner.py` | real `_load_profiles` filters open; detect keeps all-match report then `one_per_profile` before plan/runs/wait; `_report_profiles` = “N open (M closed — skipped)”; provision/runs/`_fallback_or_block` pass `Patterns`; drop `_report_clashes` |
| `app/browser/uivision/sequence.py` | `_launch` logs primary → fallback locator (D6) |
| tests | update the pins listed in `AGENT_RULES`-style inventory below; new tests: url-macro shape, dedupe, lock probe (fork-held + both OS branches), open-only listing/runner, launch param |

## Test inventory (what changes and why)

* `test_uivision_autorun.py` — param whitelist gains `continueInLastUsedTab`
  (still no arena.ai/https in query).
* `test_uivision_macro.py` — default (no url pattern) keeps today's 5-command
  shape; new: url config prepends `store/selectWindow/store`; “never opens a
  page” allows `store` rows (Value = `!errorignore`, not a URL).
* `test_uivision_plan.py` — `Patterns` signatures; per-profile dedupe; `clashes`
  test deleted; selector tests state the fallback contract (url primary lives
  in the file, cmd_var3 = hard fallback).
* `test_uivision_runner.py` — per-tab run tests → one-run-per-profile; flood
  tests unchanged (anonymous session = one profile); happy path unchanged
  (no url pattern); url tests gain macro-file assertions for the baked primary;
  new: real-path sessions filtered by `open_sessions`, open/closed report line.
* `test_uivision_tabs.py` — existing reads unchanged (they pass explicit
  profiles); new: `profile_in_use` free/absent/foreign-branch/fork-held.
* `test_uivision_profiles.py` — `list_profiles(in_use=...)` keeps answering
  sessions only when the probe says open.

## Out of scope / rejected

* `url=` as the *runtime-only* selection (E209 every run) — guarded attempt instead.
* `cmd_var4` (not seeded), `if_v2 !${!statusOK}` fallbacks (errorignore branch
  semantics + races), `executeScript` URL switching (no `uiv` bridge in page
  context), session-store mtime as “open” (1h idle writes), `closeBrowser`.
