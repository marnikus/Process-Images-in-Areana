# Firefox multi-profile — scan every open profile, run the macro on each match

Date: 2026-09-23. Amends I-63. The window still drives the same XClick macro; what changes is *which Firefox instances* it can see and reach.

## Problem

`tabs._best_session` keeps the profile whose session file has the newest mtime and drops the rest. A running Firefox rewrites `recovery.jsonlz4` about every 15 s, so "freshest" is the last-focused profile. The launch line is exactly `[binary, url]`. Firefox's remoting then hands that URL to the install-default instance — the profile last used to start Firefox — and Ui.Vision in that instance can only `selectWindow` its own tabs. A matching tab in any other open profile is never seen and never clicked.

## Decisions

**D-1 — An open profile is one whose lock is held.** Unix: the `lock` symlink names a live PID (`ip:+pid`), or `.parentlock` / `parent.lock` is flock-held. Windows: `parent.lock` cannot be renamed onto itself (sharing violation). A missing lock is closed, not unknown. A probe that throws is `unknown`: include the profile only when its session file is younger than 90 s (the live rewrite), otherwise skip it and say so. A closed profile is never launched — `-P` on a closed profile would *start* it.

**D-2 — Every open profile is read.** `scan_open` calls the per-profile session reader for each open dir. It does not rank by mtime. Each row keeps its profile name (from `profiles.ini` `Name=`), folder, url and title.

**D-3 — A tab matches when the pattern is in the URL or the title** (case-insensitive). A blank pattern still blocks the run before any file is written (the macro never opens a page).

**D-4 — One launch per addressable tab, into that profile.** Argv is `[binary, "-P", <profiles.ini Name>, url]` — the switch Ui.Vision documents for concurrent instances. When the name is missing or itself contains a banned marker, argv is `[binary, "--profile", <path>, url]`. A job with neither name nor path is refused: handing a bare URL to Firefox would land in the default profile again (the bug). `-no-remote` stays banned; it would start an isolated browser instead of the handoff. The URL is still the official `file:///…/ui.vision.html?…` command-line API. `cmd_var3` is `title=<that tab's exact title>` so `selectWindow` (empty Value column — nothing is opened) lands on that tab, not on the first title that contains the pattern. An untitled tab falls back to `title=*<pattern>*` and the log says so.

**D-5 — Identical titles in one profile are not double-clicked.** `selectWindow` returns the first title match. A second tab with the same target is logged as skipped, with a result line, and is not launched. Distinct titles each get a run.

**D-6 — Sequential, not parallel.** XClick is native OS input. The next tab waits for this tab's savelog. Stop is checked before every tab (RULE 7). Each tab has its own savelog (`run-<stamp>-t<n>.txt`) so the verdicts cannot overwrite each other.

**D-7 — Empty is not a launch.** No open profile, or none of them have a matching tab → `blocked`, nothing started. That is the empty answer (RULE 4), not a success and not a launch into the wrong profile.

**D-8 — New modules, not a growth of the legacy hotspots.** `runner.py`, `tabs.py`, `launch.py` and `desktop.py` already exceed the recorded ratchet maxima. Touching them fails the gate even when the edit does not grow them. `profiles.py` owns the eyes; `dispatch.py` owns the multi-profile run. The window's `do_run_test` calls `dispatch.run_profiles` (same line count — `firefox_auto.py` sits on its `max_func_loc` 20). `runner.run_test` stays the single-launch helper the existing tests pin.

## Rejected

* Aggregating tab lists but still launching `[binary, url]` — the URL still arrives in one profile. Finding a tab and then not running on it is the bug.
* `-no-remote` / a debugger port — banned (I-62 / I-63), and `-no-remote` refuses the handoff.
* `tab=<index>` — Ui.Vision's index is relative to the autorun tab and per window. It would click the wrong tab. Exact `title=` is the documented selector.
* Starting every profile dir on disk — closed profiles have stale sessions; launching them opens a browser the user does not have open.
* Splitting `runner.py` only to get under the stale baseline — metric-gaming (RULE 16 §16.2). The new responsibility gets its own module.

## Log contract

* `firefox profiles open: N (labels); M closed skipped (folders)`
* `profile <label>: T tab(s), K match “<pattern>” (<session file>)`
* `match i: <url> — <title>`
* `profile <label> tab i/n: -P <name> — <url> — target title=…`
* `profile <label> tab i/n: <kind>: <message> — <url>`
* summary: `ok/launched tab(s) ok, matching count, profile names`

## Measured (RULE 16 / 18)

Gate on the new modules: 0 fails (`verify_quality.py`, hard limits only — these files are not in the baseline). New-module coverage in their tests: 100% line and branch. `firefox_auto.do_run_test` stays at 20 lines (one import swapped; the file was already on its ratchet ceiling).

| File | Lines | Notes |
|---|---:|---|
| `profile_lock.py` | 100 | leaf; under 150 is right for one OS question |
| `profiles.py` | 246 | names, scan, match, argv |
| `dispatch.py` | 321 | ideal-size comment: the log wording and the step that emits it are one contract |

`_run_jobs` is 21 physical lines (ideal 20, fail 30) — binary check, one provision, then the tab loop. `names_in` / `profile_flag` sit at CC 8 (fail 10): each branch is a real refusal, not a split waiting to happen.

## Files

* `app/browser/uivision/profile_lock.py` — is this instance running (symlink PID, flock, Windows rename)
* `app/browser/uivision/profiles.py` — names, scan, match, argv
* `app/browser/uivision/dispatch.py` — scan → provision once → launch/poll per tab
* `app/ui/panels/firefox_auto.py` — the window calls `run_profiles` (one import line)
* tests: `tests/test_uivision_profiles.py`, `tests/test_uivision_dispatch.py`
