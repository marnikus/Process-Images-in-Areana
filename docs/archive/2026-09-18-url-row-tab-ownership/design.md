# URL row ↔ tab ownership — research + fix design (2026-09-18)

User reports (verbatim intent):

1. **"5 links detected but only 4 tabs open — one is extra and it's a bug."**
   The URL List shows more rows ("links") than there are real Chrome tabs.
2. **"Only one link was selected but 2 links were used even though I checked
   only one to use for the job."**
   The URL-row checkbox (enabled = "use for job") is not honoured: jobs ran on
   tabs the user did not check.

Both bugs share one root cause family: **the row ↔ tab binding invariant is
broken from two sides** — runs move rows between tabs, and dispatch ignores
which tabs the checked rows own.

---

## 1. Evidence

`config/app_state.json` (the user's own persisted state) holds **6 URL rows
bound to only 4 distinct tab ids**:

| row id | tab_id | note |
|---|---|---|
| url_2c2ff2d7 | 154FBF46… | dup owner |
| url_dd693211 | 154FBF46… | dup owner (extra) |
| url_550177d7 | 67450251… | dup owner |
| url_b2b9b265 | 67450251… | dup owner (extra) |
| url_8e48bb78 | 59FA0C0D… | ok |
| url_25cb19c3 | F7F8CD13… | ok |

All six rows have the identical URL. 4 tabs → 6 rows = exactly the "one is
extra" symptom (the user's session showed 5 rows / 4 tabs; it grows over time).
Nothing ever shrinks it: pruning (`prunable_row_ids`) only removes rows whose
tab **vanished**, and these tabs are all live.

## 2. Root causes

### RC-A — runs steal row bindings → the next scan adds a phantom row

* `Bridge._do_run_batch` assigns URLs **round-robin**
  (`urls[url_idx % len(urls)]`) and then `url_row.link_tab(primary_tab_id)`
  re-binds that row to whatever tab the job happens to run on.
  `primary_tab_id` moves between images (`_select_run_tab` →
  `resolve_primary_tab` picks the best ready tab when one cools down).
* `multi_page_dispatcher._pick_enabled_url` always picks the **first** enabled
  row and `link_tab(ctx.tab_id)` flips that single row between all parallel
  tabs.

Effect: tab T loses its owning row (the row now points at the tab that ran
last). The next auto-connect scan (every 15 s) sees live tab T with **no**
owning row and no unlinked row with the same URL →
`plan_auto_connect` emits `add` → `_apply_auto_plan` creates a **new**
`enabled=True` row for T. Row count now exceeds tab count, permanently.
Repeats on every cooldown-driven tab move.

### RC-B — dispatch ignores the checkbox

* Auto-connect pool-joins **every** tab matching `url_pattern`; that part is
  correct (status/timers UI needs it).
* But `dispatch_parallel` acquires *any* free pool page
  (`PagePool.wait_for_free_page`), and single-mode `resolve_primary_tab`
  heals to *any* ready pool tab. Neither consults which tabs are owned by
  **enabled** rows. So with 1 row checked and 4 tabs pooled, jobs still run on
  2+ tabs — "2 links used".
* Aggravator from RC-A: phantom rows are created `enabled=True`, so the set of
  "usable links" silently grows back after the user unchecks rows.

### RC-C — no repair path

Once duplicates exist, no code collapses them (prune is dead-tab-only), so the
broken state in `app_state.json` persists across restarts.

## 3. Design

### Invariant (new, recorded as I-33 in SYSTEM_OF_RECORD)

> **One live tab ↔ at most one URL row.** Auto-connect is the sole creator of
> tab-bound rows; runs never re-bind a row to a foreign tab. **A tab may run
> jobs only if an *enabled* (checked) row owns it.** The checkbox is the
> "use for job" switch for both single and parallel paths.

### Changes

1. **`app/services/auto_connect.py`** (pure, testable; stays 150–300 lines):
   * `dedupe_linked_rows(rows)` → `(kept, dropped_ids)`: collapse rows sharing
     a `tab_id` (keep first enabled, else first). One-time repair of RC-C,
     run by the scan before planning.
   * Run-time selection helpers (rows → tabs direction, same ownership
     concept): `enabled_tab_ids(urls)`, `row_for_tab(urls, tab_id)`,
     `pick_url_for_tab(urls, tab_id)` (owner else first enabled, never
     re-links), `counts_in(pool, allowed)` (parallel gate over allowed tabs),
     `claim_unlinked_from_pool(urls, pages)` (rescue: link enabled unlinked
     rows to a matching **unowned** pool page at run start; score ≥ 300 =
     exact/prefix only, never host-level, so a row can never be bound to the
     wrong chat tab).
2. **`app/services/cooldown_service.py`**:
   `resolve_primary_tab(pool, tab_id, allowed=None)` — candidates restricted
   to allowed tab ids; returns `""` when nothing allowed is usable (caller
   aborts with a clear message instead of running on an unchecked tab).
   `allowed=None` keeps the old behaviour for existing callers/tests.
3. **`app/services/multi_page_dispatcher.py`**:
   * `DispatchCtx.allowed` (derived inside `dispatch_parallel` from `urls` —
     signature unchanged, ≤ 4 params kept).
   * Page acquisition filtered to allowed tabs via
     `_acquire_free_in(pool, allowed, job_id)` under `pool._lock`
     (same external-lock pattern as `sync_pool_presence` /
     `register_job_done` — PagePool keeps its 15-method cap untouched).
   * `prepare_image_for_job(..., tab_id)` assigns the row that **owns** the
     acquired tab; the foreign `link_tab` call is deleted.
4. **`app/ui/bridge.py`** (hotspot: no new methods, no LOC growth — edits are
   net-neutral replacements inside existing functions):
   * `start_run`: refuse early when no checked row owns a live tab (after the
     rescue claim), with an actionable message.
   * `_do_run_batch`: compute `allowed = enabled_tab_ids(urls)` up front;
     initial + per-image `_select_run_tab(primary, allowed)`; parallel gate
     uses `counts_in(pool, allowed)`; per-image URL assignment becomes
     `pick_url_for_tab(urls, primary_tab_id)` (round-robin + `link_tab`
     deleted — net fewer lines).
   * `_do_auto_connect_scan` / `_apply_auto_plan`: repair duplicates before
     planning (logged), and defense-in-depth: never `add` a row for a tab some
     row already owns.

### Rejected alternatives

* **Filter at PagePool (`wait_for_free_page(allowed=…)`)** — signature already
  at the 4-param hard limit; PagePool is at its 15-method cap (RULE 16.1,
  SYSTEM_OF_RECORD row 21 note). External-lock acquire in the dispatcher is
  the established pattern.
* **Stop pool-joining non-checked tabs** — would hide their cooldown/status
  from the UI and break presence sync; gating dispatch achieves the user's
  intent without losing observability.
* **Auto-added rows default `enabled=False`** — contradicts the documented
  "scan adds rows for tabs matching pattern" behaviour (SYSTEM_OF_RECORD row
  11) and would silently stop working tabs; the checkbox is the opt-out and
  now actually gates runs.
* **Delete run-time `link_tab` entirely and re-link by URL match at display
  time** — the row→tab bind is persisted identity used by Stop/job-line and
  popup; ownership must stay explicit.

## 4. Test plan (tests first, RULE 8)

* `dedupe_linked_rows`: keeps first enabled per tab, drops extras, unlinked
  untouched, empty/garbage tolerant.
* selection helpers: enabled_tab_ids skips empty ids; row_for_tab exact owner;
  pick_url_for_tab owner beats first-enabled, falls back without re-linking;
  counts_in counts only allowed; claim_unlinked_from_pool binds only
  exact/prefix match to unowned pages, never steals, never host-matches.
* `resolve_primary_tab(…, allowed)`: keeps allowed free tab, moves from
  non-allowed, `""` when allowed set has nothing usable, legacy `None`
  behaviour unchanged (equivalence gate: existing suite green).
* dispatcher `_acquire_free_in`: picks lowest-jobs allowed page, marks busy,
  never touches non-allowed pages, `None` when only non-allowed are free.
* Equivalence gate: full existing suite (372 tests) stays green.

## 5. Migration of the broken persisted state

No manual step: the first auto-connect scan after startup repairs the 6-row
state to 4 rows (one per tab, enabled flags preserved, dropped ids logged).
