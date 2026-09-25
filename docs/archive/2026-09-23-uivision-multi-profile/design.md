# Design — Ui.Vision runs reach every Firefox profile and every matching tab

Date: 2026-09-23 · Owner report: *"it always open only the last profile of Firefox and if
2 profiles are open it never do search and run macro on the other profile tab."*
Requested: look at **every** profile → find **all** tabs matching the pattern → run the
macro for **every** matching tab in **every** profile, not just the last-opened one.

## Root cause (two halves, one symptom)

1. **Detection saw one profile.** `tabs._best_session` returned only the *freshest*
   readable session store, so `tab_rows()` / `session_windows()` described a single
   profile — the last one Firefox rewrote. Every other running profile was invisible
   to the detect phase.
2. **The launch addressed no profile.** The autorun URL rode `[binary, url]`, so the OS
   handoff dropped it into one instance (the default / last-started one). Only that
   instance's Ui.Vision extension ran the macro, and its `selectWindow title=*…*` can
   only see tabs of its own instance — matching tabs in the other profile were never
   selected, never clicked.

## Mechanism that makes per-profile runs possible (no debugger)

* `firefox -P "<name>" <url>` — Firefox's own per-profile remoting (default since ~52):
  when an instance of *that named profile* is already running, the URL is handed to
  **that** instance (its Ui.Vision runs the macro); when it is not running, Firefox
  starts with that profile. No `-no-remote`, no second isolated browser, no debugger
  vocabulary — the banned-marker scan still runs over the whole argv.
  **Superseded 2026-09-25 — name-keyed delivery proved unreliable against a running
  multi-instance setup (`profiles.ini` `Name=` may be absent/duplicated/unstable, and
  `-P` can hand the URL to the *current* instance instead of the named one): delivery
  is directory-first (`-profile <abs dir>`), `-P` only as the name-only fallback —
  `2026-09-25-uivision-delivery-by-directory/design.md`.**
* A profile directory that no `profiles.ini` section names gets `-profile <abs dir>`
  (same remoting, keyed on the profile directory). *Since 2026-09-25 this is the
  primary form for EVERY profile with a known directory.*
* Per-tab addressing rides `selectWindow title=…` (Ui.Vision's own tab switcher): each
  run passes **that tab's own title glob** (`title=*<exact title>*`) as `cmd_var3`, so
  the second matching tab of a profile is selected even though the bare pattern would
  always land on the first match. Two tabs in one profile sharing a title cannot be
  told apart by `title=` — the detect phase says so out loud (RULE 4) instead of
  pretending (the fragile alternative, `tab=N` relative offsets, depends on which
  window received the autorun tab and can click the wrong tab; rejected).

## Structure (RULE 16/18: planner + executor extracted, orchestrator stays small)

* **New `app/browser/uivision/plan.py`** — pure planner, imports only `paths`/`launch`:
  `Target` (profile name/dir, url, title, that profile's session windows),
  `anonymous_session` (the faked flat-rows seam as one unnamed profile),
  `plan_targets` (sessions × pattern → one Target per matching tab, stable order),
  `selector_for` (`title=*<tab title>*`, falling back to `title=*<pattern>*`),
  `runs` (targets → `PlannedRun`: index/total, label, selector, profile argv prefix,
  its own savelog path), `profile_args` mapping, `clashes` (duplicate-title warning),
  `summarize` (the run-plan line).
* **New `app/browser/uivision/sequence.py`** — the executor split out of `runner.py`
  (502 → 323 lines): `Sequence` walks the `PlannedRun` list (foreground → launch →
  poll each), `rollup`/`rollup_reason` fold the per-run verdicts into one answer,
  and `RunResult` lives here (runner re-exports it, so every import path survives).
* **`tabs.py`** — `profile_sessions()` reads EVERY profile's store (stable dir order);
  `ini_entries` also extracts `Name=`; `profile_names()` maps dir → `-P` name;
  `tab_rows()`/`session_windows()` become unions over all profiles (windows carry a
  `profile` attribution, renumbered across profiles); `session_source()` still answers
  for the freshest (compat).
* **`launch.py`** — `profile_args(name, dir)` → `("-P", name)` / `("-profile", dir)` / `()`
  and `profile_argv(binary, url, args)` → `[binary, *args, url]`, same banned scan
  (`build_argv` itself is untouched and still returns exactly `[binary, url]`).
* **`paths.py`** — `log_file(config_dir, stamp, part=0)`: run 1 keeps `run-<stamp>.txt`,
  runs 2+ get `run-<stamp>-<n>.txt` so parallel verdicts never overwrite each other.
* **`runner.py`** — detect is profile-driven (per-profile tab counts, matches with
  profile attribution, the run-plan line, duplicate-title warnings) and hands the
  planned runs to `sequence.Sequence`. **A single run passes its verdict through
  unchanged** — all pre-existing single-run behaviour, log lines and pinned step
  sequences are preserved verbatim.

## Verdict roll-up (multi-run)

`stopped > blocked > error > timeout > ok`. All ok → `all N run(s) ok`; otherwise
`K/N run(s) ok — <first failing run's label>: <its message>`; a stop reports how many
runs completed; blocked names how many runs were not attempted. Each run's verdict is
also reported per run (`run i/N (profile “X” · tab “Y”) — kind: message`).

## Fallback (unchanged behaviour)

No store readable, or no tab matches, or the tabs seam is faked → exactly today's
single run: `[binary, url]`, `cmd_var3=title=*<pattern>*`, savelog `run-<stamp>.txt`.

## Measurements rejected (RULE 19 honesty)

* Splitting `_detect_tabs` into `part1/part2` — rejected; extraction is by concept
  (`plan.py` owns planning, `_Sequence` owns execution).
* `tab=N` relative offsets for per-tab addressing — rejected: depends on which window
  received the autorun tab, can click a wrong tab (blast radius beats honest E210).
* A `**kwargs` catch-all on `RunSpec` — rejected; config stays explicit (RULE 3),
  per-run values are computed, not configured.

## Gates

`tools/verify_quality.py --changed --allow-legacy` + pytest + coverage floor; new
functions ≤20 LOC aim / 30 fail, CC ≤10, nesting ≤4, params ≤4; every new path has a
test that fails if the code is deleted (RULE 8); I-63 amended in
`docs/current/SYSTEM_OF_RECORD.md` (RULE 17).
