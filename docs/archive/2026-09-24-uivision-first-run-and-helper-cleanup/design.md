# Design — first run reaches every RUNNING profile once; helper tabs clean up

Date: 2026-09-24 · Owner bug report: *"First run always fails — opens the Ui.Vision
Autostart Page on the same profile multiple times, runs the macro on that profile
repeatedly (as many times as it opened autostart pages), other profiles are never
reached. Second and later runs work. Fix: helper tabs must open as tabs (never new
windows), run as silently as possible, and all helper tabs (autostart page, Ui.Vision
panel) must close when the macro finishes."*

## Root causes

1. **Phantom targets from closed profiles.** `tabs.profile_sessions()` reads every
   profile's session store from disk — including profiles that are NOT running.
   A closed profile's `recovery.jsonlz4` still lists its last-open tabs, so the plan
   targeted browsers that did not exist. On the owner's Windows machine those
   handoff launches piled the autorun page into the first (running) profile, that
   profile's macro re-ran per stray launch, and the closed profiles were never
   reached. The second run "worked" only because run 1 had meanwhile started every
   profile.
2. **The autorun page re-dispatched the macro event every 1000 ms** (vendored
   `setInterval(dispatch, 1000)`, cleared only on `kantuInvokeSuccess`). During a
   cold first start — extension attaching, `MAX_TRY` reloads — several dispatches
   landed, so the macro executed multiple times: the over-clicked tab.
3. **Blocking alerts** (`Error #203` / `#204`) left the autostart tab open behind a
   modal, and the tab never cleaned itself up.

## The fix

* **Running-profile gate.** `tabs.is_profile_running(dir)` reads the profile lock:
  Windows `parent.lock` is *held open* (share-locked) while the instance lives — a
  stale file opens fine; POSIX `lock` is a symlink to `ip:pid` and the pid must
  answer. Sessions carry `running`, and `plan.split_running(targets, sessions)`
  splits ready targets from stale ones. The runner plans only ready targets and
  warns per skipped stale target (`profile “X” is NOT running — start it to include
  its tabs`). Every planned run now hands the autorun URL to a LIVE instance, so it
  opens as a **tab in that profile's existing window** — never a new window — and
  the first run behaves exactly like the owner's working second run.
* **Single dispatch.** The page dispatches `kantuSaveAndRunMacro` exactly once,
  gated by `data-kantu` — that attribute is set by the extension's own content
  script, so its listener is provably live; the 1 s re-dispatch interval is deleted.
  No more duplicate executions.
* **Self-cleaning helpers.** On `kantuInvokeSuccess` the autostart tab closes
  itself (`window.open('', '_self'); window.close()` — the classic script-opened
  mark), with a 120 s failsafe close. The blocking alerts become an in-page banner
  + `document.title` + delayed self-close (8 s): the reason stays visible, no modal
  waits for a human, no helper tab survives. `closeRPA=1` (already in every launch
  URL) closes the extension's RPA panel when the macro ends.
* **Silence, honestly bounded (RULE 4).** The extension's documented command-line
  API is page-based — a fully silent run does not exist without a debugger (banned).
  The helper tab flashes for the run's duration and closes itself; the panel is
  closed by `closeRPA=1`. That is the closest to silent within the owner's critical
  rules.

## Files

* `tabs.py` — `is_profile_running` (+ `_windows_lock_held`, `_posix_lock_alive`),
  `profile_sessions()` rows gain `running`; docstring notes the gate.
* `plan.py` — `split_running(targets, sessions)` (pure; `running is False` marks a
  closed profile, absent key = faked seam = included).
* `runner.py` — detect reports the running split (`firefox profiles scanned: M`
  ` — running: N (names)`; `scanned: 0 (is Firefox installed?)` when no dirs),
  warns per skipped stale target, and the no-match and blocked messages say
  "running profile".
* `autorun.py` — `PAGE_HTML` rework (single dispatch, self-close, banner); the
  interop docstring records the delta from the vendored page.

## Tests (RED-first)

`plan.split_running`; `tabs.is_profile_running` (held / stale / missing lock on
both OS shapes via the monkeypatchable helpers); runner (a closed profile's
matching tabs are skipped with a warning, one launch to the running profile; all
matches closed → blocked naming it); autorun (single dispatch, no `setInterval`,
`kantuInvokeSuccess` → self-close, banner instead of `alert`).
