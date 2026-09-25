# Firefox tabs in the pool & URL list — unified worker design

Date: 2026-09-25 | Status: implemented in this change | Owner input: the
"Firefox Tab → Pool & URL List Integration" design brief (pasted in the task,
dated 2025-09-25 there — same day as this archive, year typo), priority High,
prerequisite "Firefox tab search via Ui.Vision is working" (I-63).

Goes with: `docs/current/SYSTEM_OF_RECORD.md` (rows 19/21 + **I-64**),
`docs/current/AGENT_RULES.md` (RULE 16/18/19 gates applied here).

---

## 1. The gap (owner's §1, current state)

Chrome tabs flow through one pipeline: CDP `/json/list` → `browser_tabs.
live_tab_rows` → `live.reconcile` (rows + pool, every `url_reconcile_interval_ms`)
→ checkbox gate → dispatcher picks a free checked page → CDP action blocks →
per-tab cooldown. Firefox tabs are discovered (`uivision/tabs.py` reads every
open profile's session store) and can run the Ui.Vision framework test, but
they never enter the pool or the URL list: no status, no cooldown, no job
count, no dispatch. Chrome and Firefox cannot share one queue.

## 2. Target (owner's §2, unchanged)

Both browsers' tabs in the SAME pool and URL list; the dispatcher treats a
steady tab identically regardless of browser; per-tab identity, cooldown,
jobs, checkbox membership, reconcile add/remove all follow the one existing
Chrome mechanic.

## 3. Decisions (this round's D-notes, local numbering)

* **D-1 — one fetch, one eligibility rule.** Firefox tabs ride the *same*
  `fetch_tabs` seam the reconciler already has: `browser_tabs.reconcile_tabs`
  returns Chrome `TabInfo`s **plus** discovery rows shaped the same
  (`id/title/url/ws_url=""`, `browser="firefox"`). Pattern filtering stays in
  `auto_connect.plan_auto_connect` with the one `url_pattern` (RULE 10) — no
  second filter, no second planner. `browser_tabs.firefox_rows(bridge)` is the
  single discovery seam: `bridge._firefox_rows` override (tests) → module
  `DISCOVERY_ENABLED` kill switch (conftest) → real
  `uivision.discovery.discover` in an executor (file reads never block the
  loop).
* **D-2 — stable tab identity.** `tab_id = "{profileDirBase}_tab{n}"`
  (e.g. `9THrgpBc.Profile1_tab6`), `n` = 0-based index of the tab in the
  profile's flattened session order. Same store, same id, every rescan
  (owner's §2.2). `discovery.is_tab_id` recognises the shape — CDP target ids
  are hex and never end `_tab<digits>` — which is how one pass tells the two
  browsers' keys apart without a per-row flag.
* **D-3 — a dead browser is a wait, per browser.** The existing rule "a
  failed fetch is a wait, not a removal" (ScanUnavailable) is kept for the
  all-down case. New: when Chrome does not answer **but Firefox did**, the
  pass proceeds for Firefox while Chrome-linked rows are *protected* — no miss
  advance, kept through the manual Reparse sweep (`_protected_keys`, fed by
  `bridge._chrome_scan_down` which `reconcile_tabs` sets fresh each pass).
  Symmetrically, pooled Chrome pages are merely flagged stale (not deleted)
  and revive when the endpoint returns. Firefox-only setups (Chrome scan
  disabled → no notes → no failure) work with no special case.
* **D-4 — connection method is derived, never stored.** `page_status.
  conn_of(browser)`: `chrome→cdp`, `firefox→uivision`. The pool snapshot emits
  `conn` + the new `PageInfo.profile` (profile dir — the stable handle the
  configs already use). The URL list renders 🌐 cdp / 🦊 uivision from it
  (owner's §2.3). One field (`browser`), one rule, no drift.
* **D-5 — pool join through a second seam, checkbox-gated.** Chrome joins by
  ws (`LiveDeps.join_tab`); Firefox joins through the new
  `LiveDeps.join_entry(tab)` → `page_pool.join_discovered_page` (adds
  `PageInfo`, restores persisted cooldown/jobs, emits the snapshot, announces
  with the readable label). A pass joins only pattern-matching tabs whose row
  exists and is checked; `_enforce_membership` (unchanged) still owns the
  exit half for both browsers. Already-pooled Firefox pages get their
  url/title refreshed from the session store each pass (navigations follow,
  owner's §3.4 "update URLs if tab navigated"; the ROW's url is not rewritten
  — same principle as Chrome rows).
* **D-6 — config lives in services.** The `firefox_auto` config helpers
  (defaults/clamps/validate/load/paths/build_spec) move from
  `ui/panels/firefox_auto.py` to `services/firefox_config.py` so the job
  runner can build a `RunSpec` without importing `app.ui` (panels → services
  only). The panel re-exports every name — slots, tests and the frozen
  141-slot surface are untouched.
* **D-7 — execution: one Ui.Vision macro run per dispatched job**
  (owner's §4.2). `services/firefox_job.run_macro_job(bridge, pool, tab_id)`:
  1. **machine-serialised** — one macro at a time per machine (module-agnostic
     `asyncio.Lock` cached on the bridge) with the configured
     `firefox_auto.inter_run_delay_sec` gap between runs (default 3 s, owner's
     §4.3) — the gap wait is stop-aware (RULE 7);
  2. re-resolve the tab by its pool id through `discovery.find_target` (closed
     tab ⇒ honest failure, never a launch at the wrong tab);
  3. **provision** the macro + autorun page (`runner.provision`, the one
     builder the framework test also uses);
  4. **foreground** the ONE profile's window via the session-windows mapping
     (`Sequence._foreground`; ambiguous titles raise nothing — 2026-09-25
     rule), **launch** `[binary, -profile <dir>, url]`, **wait** for the
     savelog, **parse** the verdict — all through the existing
     `plan.runs` / `Sequence` executor with seams (stop = run cancel or the
     row's Stop flag, sleep, popen);
  5. tab locator = the **pool entry's URL** as the guarded `url=*…*` attempt
     in the macro file + the tab's own title as the hard `selectWindow`
     fallback (owner's §4.2 "use the URL pattern from pool entry, not
     auto-constructed title").
  Verdict mapping (kinds frozen, RULE 4): `ok → success`;
  `error/timeout/blocked/stopped → failed` with the kind in the message.
* **D-8 — one job lifecycle.** Firefox jobs reuse
  `prepare_image_for_job` (correlation id, `job_started`, attempt counting),
  `_handle_result` / `finish_image` (image status, `job_finished`, job
  history), and `cooldown_service.finish_page_after_job` — with `ctrl=None`,
  which now means *skip the CDP New-Chat reset* (no warn line; the guard
  skips only that work — RULE 9). Cooldown, Jobs column, rate-limit notes,
  Stop/abort are therefore identical for both browsers. Honest success text:
  the message is `Ui.Vision macro ok`, never `Saved <path>` — this path
  downloads nothing through the app (RULE 4/15: the macro owns the page work;
  output collection for Firefox is future work, named in SoR).
* **D-9 — routing at the two dispatch lanes.** Parallel:
  `multi_page_dispatcher.run_claimed_image` branches on `page.browser`
  (clientless Firefox page is a normal claim, not "no controller"). Sequential:
  `batch_orchestrator._execute_image` branches the same way, `_finish_primary_tab`
  passes `ctrl=None` for a Firefox tab, `_move_to_tab` claims a Firefox target
  without a CDP reconnect, and `live.supervisor.plan_pass` no longer blocks the
  whole pass on `cdp down` when a checked free Firefox tab can work
  (`_firefox_ready`). The pick rule is the existing one for both browsers
  (first free checked page in pool order — the owner brief's "fewest jobs"
  load balancing is the retired I-28 concept; job counts stay display-only).
* **D-10 — out of scope, deliberately** (owner's §4.3): no captcha detection
  on Firefox (no client ⇒ the Watcher never scans it — RULE 20 unchanged), no
  CDP badges/owner probes (clientless). Visual identity is the shared one:
  pool `worker_no` + `{email|aka}_{4 digits}` alias from the persisted
  `AliasBook`, with the profile dir in the row's tooltip (owner's §2.2
  "(1#, 2#, 3#) + name"). Recheck (owner's §3.1) = the same reconcile pass.

## 4. Shape of the change

| Layer | File | What |
|---|---|---|
| browser | `uivision/discovery.py` (new) | `FirefoxTab`, `tab_id_for/is_tab_id/tab_index_of`, `discover(seams)`, `find_target` |
| browser | `page_status.py` | `PageInfo.profile`, `conn_of`/`is_firefox` |
| browser | `page_pool.py` | `discovered_page_info`, snapshot `conn` |
| browser | `uivision/runner.py` | `_provision→provision`, `_Recorder→Recorder` (public for the job runner) |
| services | `firefox_config.py` (new) | moved `firefox_auto` config helpers (D-6) |
| services | `firefox_job.py` (new) | `run_macro_job` — lock + gap + resolve + Sequence (D-7) |
| services | `live/reconcile.py` | `LiveDeps.join_entry`, `_join_firefox`, `_refresh_firefox`, `_protected_keys`, ff counters + log line |
| services | `multi_page_dispatcher.py` | `PageJobCtx.browser`, routing, `done_msg`, `ctrl=None` finish |
| services | `batch_orchestrator.py` | sequential branch, ff move/finish (D-9) |
| services | `live/supervisor.py` | `plan_pass`: `cdp down` vs `_firefox_ready` |
| services | `cooldown_service.py` | reset skipped when `ctrl is None` |
| ui | `panels/browser_tabs.py` | merged `reconcile_tabs`, `firefox_rows` seam, `join_entry` wiring |
| ui | `panels/page_pool.py` | `join_discovered_page`, rejoin routes Firefox |
| ui | `panels/firefox_auto.py` | delegates to `services/firefox_config` |
| ui-js | `url-list/conn.js` (new — the frozen files have zero headroom), `url-list/cells.js`, `url-list.js`, `cdp/cdp-render.js` | 🦊/🌐 Tab icon, `fillConnCell` (conn method on pool snapshot), `data-connlocked` repaint guard |

## 5. Measurements (RULE 16.6 — before → after)

Before (radon cc -s, grade B or worse): `reconcile._remove_rows` 10,
`_sweep_rows` 9, `_enforce_membership` 8; `multi_page_dispatcher._acquire_free_in` 8;
`supervisor.plan_pass` 8; `cooldown_service.resolve_primary_tab` 9; runner worst 9.
Targets: every **new/edited** function ≤ CC 10 (fail line), ≤ 20 LOC preferred,
≤ 4 params, new files 150–300 LOC. The touched legacy offenders are not grown
(§16.5): `_sweep_rows` grows by one set-union term (measured CC stays 9),
`plan_pass` grows by one `and` term (CC 8 → 9, still ≤10), `run_claimed_image`
routes before its existing bodies (measured CC ≤ 6).

Rejected, on RULE 19/§16.2 grounds:

* splitting `_join_firefox`/`_refresh_firefox` into micro-helpers that only
  re-host their loops (metric gaming) — each keeps one named responsibility;
* a per-row `browser` column on `UrlRow` (second source of truth for what the
  pool already knows; `from_dict` still drops the legacy key);
* giving Firefox fake CDP clients so every existing path "just works" —
  inventing a socket the transport cannot speak would make `assert_badges` /
  `resolve_owners` / the Watcher report phantom successes (RULE 4).

## 6. Test plan (RULE 8 — real logic, fake boundaries)

* `tests/test_uivision_discovery.py` — id grammar + stability, open-profile
  lock filter, selected-profile filter, windows carried, `find_target`.
* `tests/test_firefox_reconcile.py` — service lane: Firefox row added +
  `join_entry` called (checked only), closed tab ⇒ miss ⇒ removal with
  reason, url/title refresh, `_chrome_scan_down` protection (rows survive a
  Chrome outage while Firefox rows still age out), ff summary line (events
  log once, quiet passes never repeat it).
* `tests/test_firefox_pool_seams.py` — ui lane: merged `reconcile_tabs`
  (ScanUnavailable only when BOTH are down), `join_discovered_page`,
  instant rejoin routes Firefox, `firefox_rows` seam precedence.
* `tests/test_firefox_job.py` — lock serialises two jobs + gap delay, target
  resolution (closed / titleless ⇒ named failure), verdict mapping, stop
  during the gap and during the poll, provision writes the pool-entry URL into
  the macro.
* `tests/test_firefox_lane.py` — parallel + sequential routing, image
  completed on ok / failed on error, cooldown + jobs counted, no New-chat
  reset warn, `plan_pass` proceeds with CDP down when Firefox is ready.
* `tests/js/test_url_list_conn_cell.mjs` — 🦊/uivision vs 🌐/cdp cells +
  profile tooltip; added to `npm run test:js`.
* Existing suites pin the untouched Chrome behaviour; `conftest` neutralises
  real discovery so no test reads the machine's Firefox.

## 7. Owner-brief cross-check (deviations, all intentional)

1. **"Job dispatcher picks the tab with fewest completed jobs (load balancing)"**
   — describes pre-2026-09-21 Chrome; the counter is display-only today
   (I-28 retired). Both browsers now share the *current* rule (first free
   checked page in pool order) rather than resurrecting a retired concept.
2. **URL-list `CONN` column** previously showed a Chrome-tab match score; per
   this brief it now shows the connection method (`cdp`/`uivision`) for a
   pooled row, and falls back to the old match display for unlinked rows.
3. **Row url on navigation** — the brief's §3.4 "update URLs" is implemented
   for the pool entry (execution identity); the URL *row* keeps its url, which
   is the Chrome principle (a real navigation away from the pattern removes
   the row through the existing `pattern_mismatch` rule only if the row's own
   url no longer matches).
4. **Job outcome** — the brief stops at "parse savelog (ok / error)"; ok marks
   the image completed (the macro owns the page work), error marks it failed
   with the verdict; nothing is downloaded by the app on this path (future
   work, named in SoR).
