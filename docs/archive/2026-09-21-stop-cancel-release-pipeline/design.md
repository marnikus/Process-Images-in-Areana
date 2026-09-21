# Stop & Cancel must release the tab — one pipeline, three buttons

**Date:** 2026-09-21
**Report:** Stop/Cancel log a line and nothing happens — status stays as it was,
the URL row still shows the image, the Stop button stays active, no cooldown
starts and no time elapses. Clear Time gives no visible confirmation.

---

## 1. Root cause — the release work lived *inside* the thing being killed

Every post-job duty (new-chat reset, hide the waiting overlay, clear
`current_image`, settle the page, start the timer) lives in
`cooldown_service.finish_page_after_job`, called from the `finally` of the job
task in both runners. That is correct for a job that **ends**. It is the wrong
owner for a job that is **killed**, and the two buttons kill it in different
ways — both of which skip the release:

**Cancel** (`run_control.cancel_current`) calls `cancel_batch_future`, which
calls `Future.cancel()` on the batch coroutine. `fail_processing_images` then
fixes the *image* rows. Nothing fixes the *tab*: the pool page keeps
`current_image`, keeps its busy-ish status, gets no timer. The page is the
thing the URL row renders, which is exactly the "row still shows the image"
symptom.

A subtle detail decided the design. Cancelling the future does **not** prevent
the `finally` from awaiting — I verified this directly:

```
cancel() returned: True
ran: ['finally-entered', 'finally-await-completed']
```

So `finish_page_after_job` *is* entered on cancel. But it immediately hits
`_is_cancelled(bridge)` → `_finish_cancelled`, whose contract is "hygiene reset,
ready at once, **no pause**" — and inside it `_best_effort_reset` passes
`cancel_check=lambda: _is_cancelled(ctx.bridge)`, so `_wait_page_loaded`
returns `(False, "cancelled")` on its first line. The reset is a no-op by
construction, and by design there is no cooldown. That is the whole of item 3
and 4 in the report: cancel deliberately produced no timer and no penalty.

**Stop** (`page_pool.stop_tab_job`) only sets a flag: `request_tab_abort` adds
the tab to `pool._aborts` and returns. The flag is read by `_block_skip_reason`
between action blocks and by `await_processing`. If the job is parked in a long
await (generation wait, captcha wait) nothing polls it to completion, and if no
job is running `request_tab_abort` returns `False` → `"no live job on this
tab"`. Either way the tab is never released, which is why the button "remains
active but pressing it does nothing" and why **no follow-up log line** appears:
`⛔ Stop requested` is the last thing anyone writes.

**Conclusion.** Killing the runner cannot be the same thing as releasing the
tab, because the runner is what was killed. The release has to be a step the
*operator action* owns, not a step the dying task owns.

## 2. Design — one named pipeline, three callers

New leaf `app/services/tab_release.py` — the single owner of "put this tab back
to a usable resting state". One concept, so one file:

```
release_tab(ReleaseCtx) ->
    1. clear the abort flag            (the request is being honoured now)
    2. clear current_image             (the row stops showing the image)
    3. hide the waiting overlay        (ctrl.hide_watcher_overlay — existing mechanic)
    4. reset the page to a new chat    (reset_to_new_chat — existing mechanic,
                                        with cancel_check=None so it actually runs)
    5. arm the cooldown + penalty      (start_cooldown, base + penalty seconds)
    6. emit pool status                (the UI repaints)
```

Steps 3 and 4 are the "this mechanic already exists but is not used here" the
report names. The reason they did not run is step 4's `cancel_check`: the
release runs *because* the user cancelled, so it must not abort *on* cancel.
`ReleaseCtx` therefore carries no cancel hook at all — the type makes the bug
unrepresentable rather than relying on a caller passing `None`.

**Why a new file and not a `cooldown_service` function.** `cooldown_service.py`
is 866 lines — far past RULE 18's 150–300 ideal and the single biggest file in
`services/`. RULE 16.5 forbids growing a legacy offender. Release is also a
genuinely different responsibility: cooldown owns *timers*, release owns
*operator interruption*. Cohesion (RULE 18.3) says it belongs beside them, not
inside them.

**Penalty seconds.** The report asks for "default 5 min or user-configured".
That is exactly `cooldown_min_seconds` (`DEFAULT_MIN_SECONDS = 300`), already
the per-job pause and already user-configurable. RULE 10 (one control per
decision) forbids inventing a second "stop penalty" knob for the same idea, so
release arms `min_seconds` as the base and adds the operator penalty on top
through the existing `pending_penalty` path.

### Async, from a Qt slot

`release_tab` must await CDP. The slots are sync. `run_state.schedule_coro` is
the existing seam for exactly this (used by the pool join), so both slots
schedule and return immediately — the UI never blocks, and the log lines that
were missing now arrive as the pipeline progresses (RULE 2).

### Cancel = the same pipeline, every affected tab

`cancel_current` keeps `fail_processing_images` (image rows) and gains
`release_all_active_tabs` (tab rows) — the report's "cancelling should trigger
the same reset pipeline … reset all active URLs to cooldown". One loop over the
pooled tabs that hold a `current_image`, each through `release_tab`.

`_finish_cancelled`'s "no cooldown after cancel" contract is now wrong — it was
written when cancel left nothing behind to cool. It stays for the in-task path
but the release pipeline is what the operator sees, and the two must agree:
release arms the timer, so `_finish_cancelled` running afterwards must not
clear it. It calls `_settle_pool_steady` → `mark_steady`, which I verified
leaves a live timer alone (`_settle_steady` only steadies a non-cooling page).

### Clear Time — visible confirmation

`reset_page_cooldown` already resets the timer correctly; the gap is purely
feedback (item 5). The slot returns the new state so the JS can flash the cell:
`actions.resetCooldown` adds a `cool-cleared` class for one tick, and the cell
renders `00:00` + `ready` immediately instead of waiting for the next poll.

## 3. Rules check (RULE 16 / 18 / 19)

* **New file** `tab_release.py` — target ≤ 150 lines, one responsibility.
* **Every new function ≤ 20 LOC**, ≤ 3 params (`ReleaseCtx` is the parameter
  object, RULE 19 step 4), nesting ≤ 2, CC well under 10 — the pipeline is a
  straight sequence of named steps, each individually failure-tolerant so one
  dead CDP call cannot strand the tab (RULE 4: report, do not swallow silently).
* **RULE 7** — release honours stop; it is the thing that *makes* stop real.
* **RULE 2** — every step reports; the reported symptom was silence.
* **RULE 16.5** — `cooldown_service.py` (866) and `run_control.py` (274) must
  not grow meaningfully; release logic lands in the new leaf, the slots gain a
  call each.
* **RULE 8** — tests drive the real pipeline against a fake pool/CDP and would
  fail if the feature were deleted.

## 4. Verification

Baseline before the change: pytest 1,963 · JS 328 · gate 0 fails.
Targets: same suites green, new tests for each reported symptom, quality gate
clean on every touched file.

---

## 5. What was built (as landed)

`app/services/tab_release.py` (272 lines, one responsibility) —
`release_tab` / `release_tabs` / `release_active_tabs` plus the two Qt-slot
seams `start_tab_release` / `start_release_active_tabs` and the
`tab_needs_release` predicate.

Wiring, one call each:

| Caller | Was | Now |
|---|---|---|
| `page_pool.stop_tab_job` | set an abort flag, log, return | `page_pool.stop_and_release` — flag **+** release pipeline |
| `run_control.cancel_current` | cancel future + fail images | …**+** `start_release_active_tabs` (every working tab) |
| `page-pool/actions.resetCooldown` | log only | **+** `flashCleared` → `00:00` and a green `.cool-cleared` flash |

### Two decisions the tests forced

1. **An idle tab is not releasable.** The first draft released any tab the
   Stop button named. The pre-existing
   `test_pool_stop_tab_job` failed, and it was right: a resting worker has
   nothing to stop and must not be handed a penalty it never earned (RULE 4 —
   empty is not broken). Hence `tab_needs_release` (live image *or* busy-like
   status), and the slot still answers `no live job on this tab`.

2. **The cancel sweep snapshots its working set synchronously.** The killed
   task clears `current_image` in its own `finally`; deciding the list inside
   the scheduled coroutine raced that cleanup and released nothing. The list is
   taken in the slot, the coroutine only acts on it —
   `test_cancel_sweep_snapshots_the_working_set_before_scheduling` reproduces
   the race and fails on the old ordering.

## 6. Verification (RULE 16.7 checklist)

| Gate | Before | After |
|---|---|---|
| pytest (`not e2e and not slow`) | 1,963 | **1,999 passed**, 4 skipped |
| `npm run test:js` | 328 | **334** (330 pass, 4 skip) |
| `verify_quality.py` (touched files) | — | **0 fails** |
| Coverage line / branch | 88.38 / 84.93 | **88.39 / 84.96** (no file regressed) |
| `tab_release.py` coverage | — | **100% line**, 1 partial branch |
| jscpd clones | 27 | **27** (no new duplication) |
| `js_metrics` violations | 0 LOC / 0 nest / 1 CC | **identical** |
| vulture (new) | — | **0** |

* No new function >30 LOC (largest new: 19), no class >150, no >4 params
  (largest new: 3), radon max CC **6** on the new module (fail line 10).
* RULE 18 ideals met: every new function inside 4–20 lines;
  `tab_release.py` 272 lines sits in the 150–300 band; `services/` stays at 16
  files (18.3 band is 5–15 per directory — it was already 15, and the one-file
  growth is the cohesive home for this responsibility rather than growing the
  866-line `cooldown_service.py`, which RULE 16.5 forbids).
* RULE 19 order was followed when the gate flagged `page_pool.py`: the class
  grew 139→147 and a slot grew past the file's function max, so the body moved
  to a module-level `stop_and_release` (+ `_do_stop_and_release` for the
  try/except shell) — the file's own stated design is "thin slots delegate to
  module funcs". No `foo_part1` split, no metric gaming.
