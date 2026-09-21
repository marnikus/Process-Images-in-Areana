# Design — Stop / Cancel / Clear-time reset pipeline (2026-09-21)

User report (with a row screenshot): after **Cancel current** the URL row kept its
`▶ image` line, the tab stayed busy, the row's STATUS stayed `unchecked`, no
countdown appeared, and pressing **Stop** logged `Stop requested for job on …`
followed by **nothing** — "no visible state reset occurs".

Requested behaviour:

* **Stop** — reset the URL state, put the page back to a **new chat**, remove the
  waiting overlay, clear the `processing image` display, set the tab to
  **cooldown** and add the penalty time (default 5 min / user-configured).
* **Cancel current run** — the same pipeline for **every** affected URL, each
  parked in cooldown.
* **Clear time** — countdown to 0 with a visible confirmation, the row `ready`
  immediately and free for the next job.

## Research (what the code does today — measured, not guessed)

Repro `/tmp/diag/stop_clear.py` (real `PagePool` + the real `PagePoolMixin`
slot, a page left `BUSY` with `current_image` set, no live run):

```
STALE page: status=busy image='icon-lightbulb-gear.png' busy=True free=False
Stop  -> {"ok": true} | logs: ['⛔ Stop requested for job on E49D97CA543C']
after Stop: status=busy image='icon-lightbulb-gear.png' abort_flag=True
Clear -> {"ok": false, "error": "job still running on this tab — stop it first"}
after Clear: status=busy image='icon-lightbulb-gear.png' free=False
```

Repro `/tmp/diag/cancel_stuck.py` (a job cancelled mid-flight through the real
`run_claimed_image`):

```
AFTER CANCEL status=steady image=None cooling=False remaining=0 free=True
logs: [… '✅ Page aka_0001 STEADY ready (no cooldown after cancel)']
```

* **F-1 the busy flag is trusted as proof of a live job.** `request_tab_abort`,
  `tab_has_live_job` (`cooldown_service.py:122/163`) and `reset_stuck_page`
  (`panels/page_pool.py:50`) all decide on `page.current_image`. After a Cancel
  that field is stale, so **Stop answers `{"ok": true}` and sets an abort flag
  that no live job will ever read**, and **Clear time refuses with "job still
  running"**. The page stays `BUSY` with an image and `is_free()` is False
  forever (`page_status.is_free` needs STEADY) — the tab can never take work
  again. That is the reported dead end.
* **F-2 Cancel parks nothing.** `RunControlMixin.cancel_current`
  (`panels/run_control.py:265`) sets the flags, cancels the batch future and
  fails the processing images — it never touches the pool. When the job's own
  `finally` still runs, `_finish_cancelled` settles the page **steady with no
  pause at all** (`cooldown_service.py:789`) → "cooldown not set now and no time
  elapsing", and no penalty is recorded.
* **F-3 the wait overlay survives a cancel.** `wait_for_output` hides the
  overlay in `except Exception` (`single_job_runner.py:270`); `CancelledError`
  is not an `Exception`, so a cancelled task skips `_hide_overlay` and the
  "wait for finish generation" window stays on the page ("remove waiting win").
* **F-4 the STATUS cell cannot show working state.** `url-list/render.js`
  prints `u.status`, i.e. `UrlRow.status` — the CDP *validation* status
  (`UrlStatus.UNCHECKED = "unchecked"` is its default, `core/models.py:22`).
  Nothing in the row reflects the job cycle, so a successful reset would still
  read `unchecked`.
* **F-5 the Stop button is wired to the same stale field.** `jobLineForTab`
  returns `▶ name` only for `current_image` and `updateJobLines` disables
  `.url-stop-btn` when the line is empty — a busy tab with a lost image has no
  row feedback *and* no way to stop it.

## Decisions

* **D-1 one owner: `app/services/tab_reset.py`.** "Put a tab back into a known
  state" is one cohesive responsibility that three triggers share (Stop, Cancel,
  Clear time) and it needs the pool, the clock, the page reset and the log — it
  does not belong in the already ~870-line `cooldown_service.py` (RULE 18). The
  module imports `browser.new_chat` / `core.cooldown` / `run_state.schedule_coro`
  and down-imports nothing from panels.
* **D-2 liveness is decided by the run, not by a leftover field.**
  `_live_run(bridge)` = `batch_active(bridge)` (the tracked batch future is
  alive, I-45). A busy-looking page **during** a live run is a job → Stop means
  "abort cooperatively" (`request_tab_abort`, unchanged, the job's own finish
  parks it). A busy-looking page with **no live run** is **stale** → the reset
  pipeline repairs it. The rule is written once and used by both Stop and
  Clear time.
* **D-3 Stop = abort **or** repair, never a lie.**
  `stop_request(bridge, tab_id)`:
  * live run + live job → `{"ok": True, "mode": "abort"}`, the existing abort
    flag; the finish path already resets the page and starts the configured
    pause, so the row gets its countdown.
  * no live run + busy/stale page → **park**: `{"ok": True, "mode": "reset"}` and
    one bounded async task (`schedule_coro`, the same seam joins use) that
    hides the overlay, resets the page to a new chat (best effort), clears
    `current_image` / `current_job_id` / `busy_since`, arms the pause and
    logs/emits/persists.
  * a free, really-idle tab → `{"ok": False, "error": "no live job on this tab"}`
    (unchanged wording): nothing to stop, and no penalty is invented.
* **D-4 Cancel = the same park for every affected tab.** `cancel_request(bridge)`
  is called from `cancel_current` next to the existing future cancel: it
  schedules `cancel_run_reset(bridge)`, which waits for the run to unwind
  (bounded, `UNWIND_WAIT_SEC = 5 s`), aborts survivors, then parks every pooled
  page that has a live job or a busy-like status — with **one line per tab and
  one summary** (`⛔ Cancel: 2 tab(s) parked in cooldown (05:00 each)`), then one
  emit + persist. Tabs that were already steady keep whatever timer they had
  (`_arm_timer` is monotone — a live countdown is never shortened).
* **D-5 Clear time is a state reset, not a promise.** `clear_time(pool, bridge,
  tab_id)` clears the live timer **and** the debt, and repairs a stale busy page
  so the row really is ready; when a live job runs it clears only the timer and
  answers `{"ok": True, "busy": True}` (the job finishes first — killing a job
  is Stop's job, RULE 15). It always reports `was` (the seconds it removed) and
  `job_cleared`.
* **D-6 park seconds = the configured pause.** `stop_cancel_seconds(bridge)`
  reads the existing cooldown config: `cooldown_min_seconds` (default
  `DEFAULT_MIN_SECONDS` = 300 s = **5 min**, RULE "default 5 min or
  user-configured"), and `0` when `cooldown_enabled` is off — the same knob and
  the same rule as a normal job end (`_finish_normal`), so "penalty time" and
  "the pause after a job" can never drift apart.
* **D-7 the row shows the working state.** The STATUS cell is filled from the
  pooled page the row owns, in the same per-row fill pass that already fills
  Tab / Cooldown / Jobs: `processing` (busy / waiting_generation /
  waiting_captcha), `cooldown` (timer > 0), `ready` (pooled and free); a row that
  owns no pooled tab keeps its validation status (`unchecked`, …) so URL
  validation feedback is not lost, and the CONN column / ⊘ icon are untouched.
  The job cell and Stop button follow the same predicate, so a busy tab with a
  lost image shows `⏳ busy` and can still be stopped. Clear time flashes the
  cool cell green for ~1.2 s (the user's "change color on sec or similar").

## Rejected alternatives (dishonest reductions, RULE 16.6)

* Clear the stale fields inside `request_tab_abort` and call it a fix — the flag
  would be set *and* the page repaired, so the live-job case would lose its
  cooperative abort. Liveness (D-2) has to be decided by the run.
* Make Stop always `force_reset_page` — it would yank a tab out from under a
  running job (a second writer of page state, RULE 15).
* Park the tabs synchronously inside the slots — the new-chat reset is async and
  bounded (≤15 s); a websocket-thread slot must not block (the join slot already
  schedules through the same seam).
* Give Cancel its own "reset steady, no cooldown" path (today's
  `_finish_cancelled`) — the owner asked for the *same* pipeline and an explicit
  penalty; two behaviours for one user action is what produced this report.
* Set `UrlRow.status` to `ready`/`cooldown` in Python — that field is the CDP
  validation status (`url_policy.INVALID_STATUSES` rules on it) and writing job
  state into it would silently change row-removal behaviour; the working state
  is derived in the view from the pool snapshot it already receives (no new
  state, no new slot).
* Add a "stop penalty" setting next to the pause — a second knob for the same
  meaning ("cooldown after a job"); the pause is already the user-configured
  value the report names.
* Hide the overlay only in `single_job_runner` — a cancelled task never reaches
  that code; the park path (which runs *after* the cancel, on its own task) is
  the one place that always runs.

## Files

| File | Change |
|---|---|
| `app/services/tab_reset.py` (new, **362 lines as landed** — the 288-line plan plus the `# ideal-size` header, the docstrings that carry the *why* and the `_clear_line` / `_park_line` wording helpers; RULE 18: one cohesive pipeline, with the reason stated at the top of the file, the same shape as `cooldown_service.py` (866) and `run_state.py` (422) — a split would duplicate the park, its field reset and its three log lines) | `stop_request`, `cancel_request`, `cancel_run_reset`, `park_tab`, `clear_time`, `stop_cancel_seconds`, `_live_run`, `_needs_reset`, `_park_stale`, `_abort_live`, `_forget_job`, `_arm_pause` |
| `app/ui/panels/page_pool.py` | `stop_tab_job` → `tab_reset.stop_request`; `reset_page_cooldown` → `tab_reset.clear_time` (richer, honest reply); **`reset_stuck_page` deleted** — its `current_image ⇒ job alive` gate *was* F-1, and `clear_time` repairs what it refused |
| `app/ui/panels/run_control.py` | `cancel_current` → `tab_reset.cancel_request` (schedules the sweep, never on the websocket thread) |
| `app/services/cooldown_service.py` | untouched: `reset_cooldown` / `force_reset_page` / `start_cooldown` stay the primitives `clear_time` / `park_tab` compose |
| `js/panels/url-list/reset.js` (new, **144 lines as landed** — the 105-line plan plus `rowStatus` / `_pageOf` / `_rowOf` / `_parse`, which the measured RED tests (stale pill kept from the store, the row found without an element) demanded) | the working state (`stateLabel`, `fillStatusCell`, `rowStatus`, `jobLine`) **and** the two actions (`stopJob`, `clearTime`, `flashCleared`, `coolAction`) — state and the resets that produce it are one story, and the frozen files have no headroom |
| `js/panels/url-list/actions.js` | 166 → 149 lines: `stopJob` / `coolAction` delegate to the new module (the log wording moved with them) |
| `js/panels/url-list.js` | 137 → 136 lines, func count 37 unchanged (the JS ratchet fails on *either* growing): one inlined `fillStatusCell` call in the existing per-row pass + the `jobLineForTab` question routed to `reset.js`; `_cells`/`render.js`/`cells.js` untouched |
| `js/panels/page-pool/actions.js` | pool-table ♻️ reads the same richer reply (`_clearMsg`) |
| `index.html` | script tag for `reset.js` (before `actions.js`) |
| `css/arena.css` | `url-status-processing/-cooldown/-ready` + `.url-cool-cleared` (the visible confirmation) |
| `package.json` | `test:js` gains `tests/js/test_reset_actions.mjs` |
| tests | `tests/test_tab_reset.py` (21), `tests/test_tab_reset_seam.py` (9), `tests/js/test_reset_actions.mjs` (24); two existing tests re-pointed: `test_panel_browser_tabs.py::test_reset_stuck_page_paths` → `test_clear_time_paths` (its refusal *was* the bug) and `test_tab_label_views.mjs` (the label check follows the log lines to `reset.js`, the no-hand-slicing rule now covers both files) |

## Outcome (landed 2026-09-21, `arena/01a0c40f-…`)

Measured on the real seams after the change:

* the reported dead end (`/tmp/diag/stop_clear.py`, stale BUSY page, no live run):
  `Stop -> {"ok": true, "mode": "reset", "seconds": 300}` → 1.5 s later the page is
  `COOLDOWN`, `current_image` is `None`, 298 s counting down
  (`♻️ Tab marnikus@gmail.com_3045 reset — cooling 04:59`); `Clear -> {"ok": true,
  "was": 0, "busy": false, "job_cleared": true}` with the page `STEADY` and free.
* the row follows in the same pass the pool snapshot arrives: pill `processing` +
  `▶ pic.png` + Stop enabled while a job runs, `cooldown` + live clock + empty job
  line + Stop disabled after the park, `ready` after Clear time, and back to the
  CDP validation status once the row owns no pooled tab again.
* gates: pytest **1,966 passed / 4 skipped / 0 fail**, JS **333 pass / 4 skipped /
  0 fail**, coverage **88.14 % line / 84.85 % branch** (floors 86.36 / 82.33),
  changed-file lanes **0 fails** (Python + JS); the whole-repo lane's single fail
  (`captcha.js max_cc 12 > 10`) is byte-identical on the untouched base tree.

* RULE 18 recheck on the landed sizes (the user's "recheck at the end if code fit"): every new function is
  5–13 LOC / CC 1–4, the two new modules sit at stated-reason sizes (362 lines Python, 144 lines JS) and the
  round **shrank** two frozen files it had to touch (`url-list/actions.js` 166 → 149, `url-list.js` 137 → 136
  with its 37-function count unchanged — the ratchet rejects growth in either). The first shape was rejected by
  the gates, not by taste: `_clear_under_job(bridge, pool, tab_id, label, was)` had 5 params, and the
  `_fillStatusCell` delegate pushed the facade to 38 functions.

## Tests first (RED at `71970e1`)

Python — `tests/test_tab_reset.py`: Stop with a live run + live job is an abort
and touches no timer; Stop on a stale busy page (no live run) schedules the park
and the page ends cooling with the configured seconds, its image cleared and the
overlay hidden; Stop on a free idle tab still refuses; `stop_cancel_seconds`
follows the config (default 300, 0 when disabled, 0 when `min_seconds=0`);
`cancel_run_reset` parks every affected tab (busy, waiting_captcha, stale) and
**never** shortens a live timer, leaves a steady tab alone, clears the abort
flag and logs the label; `clear_time` on a cooling page → ready + `was`, on a
stale busy page → ready **and** the page is free again, with a live run → timer
cleared but `busy: True` and the image kept; the park is bounded when the client
raises.

`tests/test_tab_reset_seam.py` (the seam the user's report crossed): the real
`PagePoolMixin.stop_tab_job` / `reset_page_cooldown` slots on a real `PagePool`
with a fake bridge and the real `schedule_coro` (spied, like the S1/L-1 join
tests) — Stop on a stale tab schedules the park on that seam and replies
honestly; Clear time returns the richer payload and the row's pool snapshot is
`steady`/free afterwards; the real `RunControlMixin.cancel_current` schedules
the cancel sweep and still cancels the batch future.

JS — `tests/js/test_reset_actions.mjs`: `stateLabel` / `fillStatusCell`
(processing / cooldown / ready / validation fallback), the job cell for a busy
page without an image, Stop's reply wording for abort / reset / refusal, Clear
time's flash + honest wording when the tab is busy, and a guard that no log line
in the touched files slices a tab id by hand.
