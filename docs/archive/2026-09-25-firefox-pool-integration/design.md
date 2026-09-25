# Design — Firefox Tab → Pool & URL List Integration (2026-09-25)

**Status:** implemented 2026-09-25 (owner brief: "Firefox Tab → Pool & URL List
Integration — Design Phase"; this doc is the researched/validated version the
code follows)
**Entry:** SYSTEM_OF_RECORD.md → I-63 family / line 402 lead
**Layer rule honoured:** services → browser only; ui-land wiring stays in
panels; `app/services` never imports `app.ui` or Qt.

## 0. Owner brief vs current code (reconciliation)

| Brief says | Current truth (2026-09-25) | Decision |
|---|---|---|
| "dispatcher picks the tab with fewest completed jobs" | I-28 load-balancing was **deleted** 2026-09-21 — `_pick_free` = pool insertion order, counter display-only | Keep insertion-order pick; Firefox joins the same order |
| "reconcile runs every 5 s" | interval is the user's `urlIntervalMs` (default 5000) | Firefox rides the SAME interval — one knob (RULE 10) |
| "tab ID = `{profileDirName}_tab{index}`" | discovery rows are `{url,title}` with no index | New mapper composes `{profile-dir-basename}_tab{N}` (N = 1-based flat session order) — deterministic from the session store ⇒ stable across rescans |
| "visual confirmation ID (1#, 2#, 3#) + logged-in user" | `AliasBook` already numbers every pooled tab (`alias_no` → `aka_1234` / `{email}_{4 digits}`); owner comes from the CDP probe | Firefox pages enter the SAME alias book. Owner probe has no CDP on Firefox ⇒ label shows `aka_NNNN` until a macro-based probe lands (stated limitation, RULE 4) |
| "Conn column = `cdp` / `uivision`" | Conn cell currently shows the Chrome tab-match chip; pool snapshot already carries `browser` per page | Firefox rows render `🦊 uivision ●`; Chrome rows keep their match chip **and** name `🌐 cdp ● …` — no new column, no new slot |
| "profile ID per pool entry" | `PageInfo` class is at its zero-tolerance LOC ratchet (100) | New `FirefoxPageInfo(PageInfo)` subclass (own class budget) carries `profile` + `profile_dir`; `to_dict` adds them to the snapshot wire |
| "one macro at a time per machine + user-defined 3 s delay" | `RunSpec.inter_run_delay_sec` exists but is BETWEEN runs of one sequence | Lane-level `asyncio.Lock` + the PRE-EXISTING `inter_run_delay_sec` key (0…30, default 3) — no new key, no new slot (frozen surface **141**) |

## 1. One listing seam (D1) — the planner never learns about browsers

`browser_tabs.reconcile_tabs` = `live_tab_rows()` (Chrome) **+**
`_firefox_rows(bridge)` (the panel-local helper; it reads the checked profile
list from `uv_cfg.load_config` — blank = every profile — and calls
`pool_tabs.firefox_rows`, which walks `uivision.tabs.profile_sessions` and
keeps only sessions surviving the `profiles.open_sessions` **lock probe**).
Each Firefox tab becomes a row object with
`id / url / title / ws_url = "firefox://{id}"` — exactly the attributes
`auto_connect` already reads (`_tab_key` prefers `.id`, pattern filter reads
`.url`, presence reads `t.id`).

Consequences (all zero-change):
* `plan_auto_connect` claims/adds rows keyed by the stable id;
* `matches_pattern` decides membership with the **one** global `url_pattern`
  (RULE 10 — the Firefox window's title `pattern` stays that window's own
  test-run filter, not a second reconcile control);
* `removable_rows` / miss hysteresis / manual sweep / checkbox→pool gate /
  orphan exit all operate on ids and run untouched;
* `_join_and_sync`'s live set includes Firefox ids ⇒ presence sync keeps
  Firefox pages alive and flags closed tabs (`tab_gone` after 2 misses ⇒ row
  removed ⇒ orphan exit ⇒ `leave_pool` — the existing I-58 chain cleans up).

**Failure semantics (RULE 4):** Chrome's answer-check runs BEFORE the Firefox
merge — if the endpoint did not answer, the pass raises `ScanUnavailable` and
*nothing* ages out (a failed fetch is a wait, not a removal). A Firefox
discovery exception propagates the same way; Firefox returning `[]` is an
answer (profiles closed) and lets Firefox rows age out honestly.

## 2. Join by sentinel (D3)

`plan_auto_connect` puts `ws_url` strings in `plan.connect`. Firefox rows
carry the sentinel `firefox://{id}`; `live_deps.join_tab` routes to the ONE
join entry `browser_tabs.route_join_tab` (also used by
`page_pool._rejoin_one`, so every joiner shares the seam):

```
firefox://…  → _join_firefox(bridge, ws)      # ui-land, re-reads the session once
else         → do_connect_page_pool(bridge, ws)  # unchanged Chrome path
```

`_join_firefox` → `pool_tabs.find_tab(id)` (fresh disk read ⇒ title/url/
profile never stale) → `pool.add_page(pool_tabs.page_for(tab))` →
`_emit_pool_status()` + the `🦊 Pool add <label> steady — uivision` log; a
tab that vanished warns and returns (never raises — the reconciler's next
pass owns removal). No
`register_client` — `get_clients` returns `(None, None)`; every existing
consumer already tolerates that (`resolve_owners`, `assert_badges`,
`leave_pool` skip clients; `cooldown_service._best_effort_reset` returns
`(False, "no CDP controller — Firefox lane (New-chat reset not applicable)")`
instead of a fake reset failure). `page_pool._live_sockets` also lists through
`reconcile_tabs`, so the panel sees Chrome + Firefox rows (D1) in one pass.

## 3. Planning gates become pool-aware (D4) — three small edits

1. `supervisor.plan_pass`: the `cdp down` reason additionally requires
   **no checked page free right now** — a free Firefox page means there is
   work to hand out even with Chrome down. New helpers `_allowed_free`
   (module-level, ≤8 LOC, via `auto_connect.counts_in`) and `_cdp_stalls`
   (`_cdp_down and not _allowed_free`); the gate stays
   `elif _cdp_stalls(bridge, plan.allowed):` so `plan_pass`'s line count
   AND its cyclomatic complexity do not move (an inline `and` grew the
   file's `max_cc` 8→9 in the first attempt — helper, not expression).
2. `batch_orchestrator._move_to_tab`: a wanted primary whose page is
   `browser == "firefox"` is claimed in place as the FIRST step (log line
   names it; no CDP move exists). Helper `_claim_no_cdp` keeps `_move_to_tab`
   at 16 LOC (floor 17) and lets a non-Firefox primary fall through to the
   socket reconnect unchanged.
3. `batch_orchestrator._try_parallel`: the feeder is entered when
   `if _has_firefox(ctx) or (total >= 2 and free >= 1)` — any checked page
   is Firefox **or** — the feeder's
   own wait (`_acquire_page`, bus wake, bounded timeout) is exactly the right
   semantics for a single busy Firefox tab, and the sequential lane (primary
   CDP connection) never receives a Firefox primary (no-Firefox-checked ⇒
   plan claims only Chrome pages).

## 4. Execution lane (D5, D6) — one macro = one job

`multi_page_dispatcher.run_claimed_image` branches at the top and keeps
every function under the file's 20-LOC floor by splitting three ways:

```python
if getattr(free_page, "browser", "") == "firefox":
    await _run_firefox_claimed(ctx, img, free_page); return
```

* `_run_firefox_claimed` (17 LOC) — the bookkeeping twin of the Chrome path:
  `_emit_status_safe` + `_log_assign` + `_start_tab_image`, then
  `_firefox_and_record`, and the shared `finally` (`_clear_tab_image` +
  `_finish_page_safely(FinishCtx(ctrl=None, client=None))`).
* `_firefox_and_record` (prepare → `job_started` → prompt-not-injected log →
  verdict → `_handle_result` → `maybe_note_rate_limit`) — identical
  bookkeeping to Chrome, so JOBS/COOLDOWN/finish code is ONE copy.
* `_firefox_verdict(job) -> (failed, err)` — page gone ⇒ named failure;
  `CancelledError` re-raises; crash ⇒ `Ui.Vision blocked: <e>`; `ok` ⇒
  `(False, "")`; any other savelog kind ⇒ `Ui.Vision {kind}: {message}`.

The record step then calls the new **`app/services/firefox_lane.py`**:

```
run_firefox_macro(bridge, page) -> (kind, message)
  spec/target  ← firefox_auto config + the page's profile + the ROW's own url pattern
  PlannedRun   ← plan.runs([target], Patterns(title="", url=url_pattern), …)[0]
  selector     ← plan.selector_for → title=… fallback (NEVER foreground-constructed,
                 the guarded `selectWindow url=*…*` first — bug-#2 contract reused)
  async with _MACRO_LOCK:            # one Ui.Vision macro at a time per machine
      wait out inter_run_delay_sec since the last macro  # owner's 3 s default
      Sequence(spec, seams).execute([run])          # provision → foreground only
                                                     # the target profile's window →
                                                     # launch (remoting forwards into
                                                     # the RUNNING instance) → poll savelog
```

`seams.stop` = `bridge._cancel_requested` (RULE 7), report lines stream to
`bridge._log` (RULE 2).

**Verdict mapping (RULE 4 — no pretend):**

| savelog kind | image | message |
|---|---|---|
| `ok` | completed | `🦊 Ui.Vision macro ok — <tab label>` (no "Saved …" — the macro lane does not write output files) |
| `error` / `timeout` / `stopped` / `corrupt` / `blocked` | failed | `Ui.Vision <kind>: <savelog text>` |

The prompt template is **recorded** (correlation id, history) but not
injected — one honest info line per job says so. When a future arena macro
performs the generation steps, the same lane completes images with outputs;
this contract does not change.

Finish is the SHARED path: `_finish_page_safely(FinishCtx(ctrl=None,
client=None))` ⇒ `register_job_done` (JOBS column), configured per-tab
cooldown (COOLDOWN column), pool emit, bus wake. Captcha detection on
Firefox: none (design says later); `captcha_count` simply stays 0.

## 5. UI (D8)

* **Tab cell** (`url-list/cells.js::fillTabCell`): `🦊` / `🌐` prefix
  inline in the existing `innerHTML` line — no new helper, file stays at
  (actually one line under) its recorded 92/13. Not-pooled rows keep the
  dash (never a phantom browser); a legacy page without `browser` degrades
  to `🌐`.
* **Conn cell** (`cdp/cdp-render.js::_connCellHtml(u, store)` — signature
  widened, no new function): a row whose bound/matched pool page is Firefox
  renders `🦊 uivision ●`; Chrome keeps the match chip and names
  `🌐 cdp ● <kind> (<score>)`; the fn+call-site line budget is exact, so
  the file stays at its recorded 121/17.
  Row HTML (`render.js`) is untouched — its size is frozen.
* Pool snapshot already ships `browser` (`_snapshot_entry`) — no wire change.
* `page_pool` panel keeps its own display as-is (browser rides the snapshot).

## 6. Config (D9)

**As-built: no new key.** The gap is the pre-existing
`firefox_auto.inter_run_delay_sec` (default 3, `INTER_RUN_DELAY_RANGE`
0…30) — validation/clamping moved with the rest of the config surface to
`app/browser/uivision/config.py` (RULE 10.3: the dispatch lane needs
`load_config`/`build_spec` and `app.services` may not import `app.ui`; the
panel re-exports every name so `fa.validate_config` stays the window's API).
The key rides the **existing** `save_firefox_auto_config` /
`get_firefox_auto_config` slots ⇒ slot surface stays frozen at 141.
UI field: `faDelay` in the Firefox window (index.html `Delay between jobs
(s)`, 0–30) wired through the existing one-table FIELDS/NUMBERS maps in
`firefox-auto.js` — an in-place line edit, no new line, no new function.

## 7. Files (as built)

| File | Change |
|---|---|
| `app/browser/uivision/pool_tabs.py` | **NEW** — `FirefoxTab`/`FirefoxPageInfo` (dataclasses), stable `{dir}_tab{N}` ids, `firefox_rows` (lock-probed open sessions), `find_tab`, `page_for`, sentinel helpers |
| `app/browser/uivision/config.py` | **NEW** — `CONFIG_KEY`…`build_spec` extracted from the panel (services cannot import ui); `firefox_auto.py` re-exports the 21 names |
| `app/services/firefox_lane.py` | **NEW** — macro lock + gap (`_gap_seconds` reads `inter_run_delay_sec`, 0…30) + `run_firefox_macro` (services → browser only) |
| `app/browser/uivision/runner.py` | public `provision()` face of `_provision` (lane writes the same macro + page) |
| `app/ui/panels/browser_tabs.py` | `_firefox_rows`, `route_join_tab`, `_join_firefox`, reconcile merge (`rows + _firefox_rows`), `live_deps.join_tab` → `route_join_tab` |
| `app/ui/panels/page_pool.py` | `_rejoin_one` → `route_join_tab` (lazy import), `_live_sockets` → `reconcile_tabs` (Chrome + Firefox rows) |
| `app/services/live/supervisor.py` | `_allowed_free` + `_cdp_stalls`; gate is call-only (cc flat) |
| `app/services/batch_orchestrator.py` | `_claim_no_cdp` (first step of `_move_to_tab`), `_has_firefox`, feeder condition edit |
| `app/services/multi_page_dispatcher.py` | top branch + `_run_firefox_claimed` / `_firefox_and_record` / `_firefox_verdict` + `_handle_result` honest done-message |
| `app/services/cooldown_service.py` | None-ctrl reset guard (log honesty) |
| `app/ui/panels/firefox_auto.py` | re-exports the config surface (137 LOC, shrank) |
| `app/ui/web/js/panels/url-list/cells.js` | browser icon inline in Tab cell (0 new funcs) |
| `app/ui/web/js/panels/cdp/cdp-render.js` | `_connCellHtml(u, store)` folds the uivision branch (file 121/17 unchanged) |
| `app/ui/web/index.html` + `js/panels/firefox-auto.js` | `faDelay` → `inter_run_delay_sec` (in-place table edit) |
| `tools/quality_baseline.json` | `captcha.js` `file_lines` 193→195 — task-7's committed `_call` guard (+2) recorded here; the JS lane had been silently skipped that day (no merge-base with `origin/main`) |
| tests (5 new py + `tests/js/test_url_list_firefox.mjs`) | RED first: pool_tabs, reconcile, lane, dispatch, plan gates, JS url-list; `test_tab_label_views` badge assertion + `package.json` `test:js` list updated |

## 8. Ratchet strategy (zero-tolerance, RULE 16)

Every edited file keeps its **file-level maxima** unchanged: new helpers are
module-level and ≤ the file's current `max_func_loc` (supervisor 21,
batch_orchestrator 17, dispatcher 20, browser_tabs 20, cooldown 22,
firefox_auto 23 — the file SHRANK via the extraction, cells.js 18,
cdp-render 17); the compound gate condition lives in `_cdp_stalls` so
`plan_pass`'s cc does not move; `PageInfo`/`ResultCtx` classes are
untouched (subclass instead of edit); the JS lane ratchets `file_lines` +
`func_count`, so both JS edits were shaped to ZERO growth (inline ternary /
signature widen) and `captcha.js`'s committed +2 is recorded in the baseline
with the reason in the commit; a final `verify_quality.py --js --allow-legacy`
reports **0 fails**.

## 9. Out of scope (explicit)

* captcha detection on Firefox (design: "will be added later");
* owner/email probe on Firefox → label is `aka_NNNN` until a macro probe;
* prompt/attach/generation inside the macro (future arena macro — same lane);
* editing the JOBS counter by hand (parity: Chrome's is not editable either);
* parallel macros on one machine (serialized by contract).
