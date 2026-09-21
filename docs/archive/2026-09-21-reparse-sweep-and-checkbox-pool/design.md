# Design — Reparse fresh sweep + checkbox owns pool membership (2026-09-21)

Feature request, two parts. Baseline radon numbers recorded per RULE 16.6;
all new/edited functions land within RULE 18 ideals (≤20 LOC, CC ≤10).

1. **Reparse button** — user report: "currently re-parses every 500 ms".
   The cadence is already the ONE key `url_reconcile_interval_ms`
   (default 5000, clamped 500…60000 by `debug_view.clamp_interval_ms`,
   S6/D-12R). Two gaps against the request:
   * **D-1 the knob is only in the URL window bar** → add the parameter to
     the main **Settings panel**. Not a second decision (RULE 10): the same
     one key, written through the same `save_settings` slot →
     `apply_url_interval` (one clamp owner), read back from the same pushed
     `progress_updated.live.url_interval_ms`. It is a second *view* of one
     setting — the established pattern (cooldown minutes already render in
     both the URL bar and the Settings panel and save through the one
     `set_cooldown_config` funnel).
   * **D-2 Reparse must rebuild the list fresh** ("remove all existing URLs
     first, then re-fetch fresh list"). Implemented inside the reconciler so
     the ordering guarantee survives: **fetch first, sweep second** — a
     failed or empty fetch never removes (I-50 kept). A manual pass sweeps
     every URL row whose tab has no live job, remembering each row's
     checkbox (`url_policy.remember`), then the normal pass re-adds rows for
     every open matching tab, restoring the remembered checkbox
     (`restore_enabled`). Rows whose tab is busy keep their identity (same
     id, assignments intact) — the I-50 deferral invariant is stronger than
     the fresh-list wish, never removed mid-job (RULE 15). Never-linked
     typed rows are swept too: Reparse means "the list is what is open now"
     (explicit request; the old keep-forever rule D-4 yields on the
     *manual* source only).
2. **URL checkbox = pool membership** — checked: the row's tab is a worker
   in "Live Worker & Queue Debug"; unchecked: it is excluded from the active
   worker pool. Today the checkbox only gates dispatch (`enabled_tab_ids`);
   the tab stays pooled and still shows "idle · ready" as a worker.
   * **D-3 one decision** — `url_policy.pool_exits(rows, pool)`: pooled tabs
     owned by an *unchecked* row must leave the pool; a tab under a live job
     is deferred (same busy gate as removal, RULE 15). Tabs without any row
     are not the checkbox's business (manual "Add Selected Tab to Pool"
     keeps working).
   * **D-4 two enforcers, one rule** (the "one eligibility rule,
     re-exported never copied" shape):
     * `toggle_url` — instant exit on uncheck, through the existing
       ui-land leave mechanic `page_pool.leave_pool` (badge cleared, page
       removed), then `_emit_pool_status` so Live Debug loses the worker
       line immediately. Busy → one `⏸` line, reconciler enforces later.
     * the reconciler pass — enforcement every pass (catches undo restores,
       preset loads, config edits): `LiveDeps` grows `leave_tab`
       (wired to `leave_pool`), after presence sync unchecked rows' tabs
       leave, logged `🚪`.
   * **D-5 no auto-rejoin while unchecked** — `plan_auto_connect` no longer
     queues `connect` for a tab whose owning row dict says
     `enabled=False` (missing key = legacy = allowed, matching
     `UrlRow.enabled`'s True default). Re-checking a row re-joins its tab on
     the next pass (≤ one interval), assigning the next worker number
     (I-55 numbering is join order) and restoring the wall-clock cooldown
     from the persisted store (`restore_page_state` — no cooldown bypass).

## Rejected alternatives (dishonest reductions, RULE 16.6)

* Sweeping *before* the fetch — a Chrome hiccup would wipe the list with
  nothing to rebuild from (breaks I-50 "a failed fetch never removes").
* Sweeping busy rows too — unassigns images out from under a live job.
* Presentation-only fix for D-3 (hide unchecked workers in JS) — the tab
  would still be pooled, cooled, badged and counted; "excluded from the
  pool" would be a lie on the Page Pool table.
* A new `set_url_interval` slot — duplicates `save_settings`' key (RULE 10).

## Sizes (radon, before)

`reconcile.py`: `_sync_rows` CC 4 / 11 LOC; `_pass` CC 1 / 7 LOC;
`url_queue.toggle_url` CC 2 / 6 LOC; `plan_auto_connect` CC 7 / 21 LOC.
After: each touched function stays within a +2 delta, new functions ≤ 15
LOC, CC ≤ 6, nesting ≤ 3 (measured again after implementation, RULE 16 §16.6
step 4).

## Tests (RULE 8 — real logic, fakes only behind the seams)

* `tests/test_live_reconcile.py` grows: manual sweep rebuilds the list with
  fresh ids + remembered checkbox; busy row survives with identity; failed
  fetch never sweeps; auto source never sweeps; membership leave fires
  through `LiveDeps.leave_tab` and busy rows defer.
* `tests/test_reparse_pool_gate.py` (new): `pool_exits` decision table;
  `plan_auto_connect` rejoin gate; `toggle_url` instant exit on a real
  `Bridge` + real `PagePool`.
* `tests/js/test_url_interval_control.mjs` grows: the Settings-mirror input
  follows the pushed payload; `SettingsPanel` payload carries the key only
  when its input parses.
