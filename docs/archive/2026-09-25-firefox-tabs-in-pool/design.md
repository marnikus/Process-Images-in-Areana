# Firefox tabs in the pool and the URL list — design (2026-09-25)

**Status: implemented as I-64 (2026-09-26).** Sections 3–6 describe the code as shipped. Section 9 lists where it differs from the first plan.

Owner brief: "Firefox Tab → Pool & URL List Integration" (priority High). Firefox
tab search via Ui.Vision already worked, but as a separate one-shot system (the
framework test, I-63). Target: **one browser-agnostic pool and URL list**. Chrome
and Firefox tabs sit side by side, the dispatcher picks any steady tab, and the
execution layer handles the browser difference. Earlier rounds did not produce a
working end-to-end path, so every step below names its seam and test.

## 1. Decisions (owner answers, 2026-09-25)

| # | Question | Answer |
|---|---|---|
| 1 | What does a Firefox job do to the image? | Marks it **FAILED** with an honest reason. Macro ok: "Firefox macro finished OK — no output saved (image processing via Ui.Vision not implemented yet)". Otherwise the macro error / timeout / refusal. It costs one retry attempt (`max_attempts`). |
| 2 | Which profiles feed the pool? | Only the profiles **checked** in the Firefox window. None checked means no Firefox in the pool. The framework test keeps "empty = every open profile". |
| 3 | Owner label of a Firefox tab | The profile name, e.g. `#3 Profile1_0007` (no macro change). |
| 4 | Tab locator | **title + relative index** (`url=` is unsupported, E209). |

Standing owner rules for this work:
- Foreground only the target profile's window.
- User-defined delay between Firefox runs (default 3 s).
- No Firefox captcha detection yet.
- Never auto-remove user-typed URLs.

## 2. Verified Ui.Vision facts (A9T9/RPA master, `src/ext/bg.js`, `src/index.js`)

- `selectWindow title=G` runs `tabs.query({title: G})` over the profile's windows and takes `tabs[0]`. Firefox matches G with `MatchGlob`: an anchored full match where `*` is any run and `?` any one char.
- `selectWindow tab=K` resolves `tabs.get(firstPlay)` → `index + K` in that window. Any failure except "DOM failed to be ready" falls back as follows:
  - It takes the **last-focused normal window's active tab** plus K and sets `firstPlay` to that tab.
  - With K = 0 it selects that anchor itself.
  - Other locator types fail with E209.
- At invoke (`CS_INVOKE`), `firstPlay = toPlay`. Opening the autorun tab activates it while Ui.Vision is NORMAL, so `toPlay = firstPlay` = the **autostart tab**. Our page self-closes 500 ms after invoke, so after a pause `tab=K` always takes the fallback.
- A successful `selectWindow` activates the tab but does not focus its window. `bringBrowserToForeground` focuses the window of `toPlay`.
- `RUN_TEST_CASE` re-reads the macro with `getMacroStorage().read()` on every command-line run. In xfile mode that is the file on disk, so a **per-run macro file** works. It refuses while a macro is playing, so we allow one macro per machine at a time.
- In `executeScript*`, current versions JSON-stringify `${var}` while old versions pasted raw text. Parsing a packed `cmd_var` in JS is therefore version-dependent → **rejected**. All per-run values are baked into the file instead.

**Locator** (`browser/uivision/pool/locator.py`, pure, run per job):
1. Read the profile's session store fresh at job time.
2. E is the target tab.
3. Walk left from E in E's window to the nearest tab T whose exact-title glob first-matches T itself over the whole profile (window order, then strip order).
   - The emulation matches case-insensitively: a superset of Firefox's matches, so "T is first" holds in Firefox whichever case rule it uses.
4. K = E.index − T.index. The glob is the title with `"`, `\`, `$`, control chars and outer whitespace turned into `?` (one-char wildcard, still matches).
5. The macro, baked per run (storage=xfile only, `macro.py`):
   - `selectWindow title=G`
   - if K > 0: `bringBrowserToForeground`, `pause 1500`, `selectWindow tab=K`
   - an `executeScript` that throws unless `location.href` contains the pool URL pattern (case-insensitive), so a non-worker page is never clicked
   - the unchanged foreground → FIND_RECT → XClick → echo tail.
6. K = 0 never issues `tab=0`: with the autostart tab still open, that would select the autostart tab.
7. No anchor in E's window → a named refusal (`locator.refusal`).

## 3. Firefox tab identity

- id = `{profileDirName}_tab{N}` (e.g. `9THrgpBc.Profile1_tab6`). N is the 1-based flat position across the profile's windows at first sight.
- A pure identity book (`pool/identity.py`, `FoxTabBook`) re-matches every scan in this order:
  1. same URL + same position
  2. same URL, nearest old position (moved)
  3. same position, new URL (navigated)
  4. new id (the smallest free N ≥ position)
- Unmatched ids are kept for `GRACE_SCANS = 3` scans, so a session-store hiccup never renumbers.
- The book is seeded from the persisted URL rows (id + URL), so ids survive restarts.
- Browser and lane come from the id shape, in `core/tab_alias.py`:
  - `tab_browser`: Firefox when the id matches `^(.+)_tab([1-9][0-9]*)$`, else Chrome.
  - `conn_of` / `page_conn` give the lane; `firefox_tab_id` / `split_firefox_id` build and parse ids.
  - `UrlRow` keeps no browser field. A persisted `browser` key was removed on purpose earlier (`UrlRow.from_dict`).

## 4. Flow

1. **Discovery** (`browser/uivision/pool/scan.py`, `FoxScanner`):
   - Scans the checked AND open profiles (lock probe). `DocCache` decodes a session file only when its mtime/size changed.
   - A tab qualifies when it has a URL and matches the Firefox window's title/URL patterns (blank = any). The global URL pattern then decides rows, exactly as for Chrome.
   - A profile that fails to read keeps its last tabs for that pass.
   - `scan` / `locate` / `last_tab` share one thread lock (the reconcile pass and a job plan may overlap).
2. **Reconcile** (same loop, same funnel, RULE 10):
   - `ui/services/firefox_pool.merged_listing` asks both browsers. `compose` returns one `TabListing` (`services/live/sources.py`): the tabs, plus `held_rows`, `held_pages` and `answered` (Firefox answered).
   - No profile checked: Chrome's answer passes through unchanged. A silent source holds its rows and pages (no misses, no stale, kept by the manual sweep). An empty Chrome answer holds its rows only (the old Chrome rule). Both silent → `ScanUnavailable`.
   - The row half of a pass lives in `services/live/row_sync.py` (`sync_rows`), split from `reconcile.py` for size.
   - `plan.connect` carries `auto_connect.join_handle`: the ws URL for CDP, the tab id for uivision. `firefox_pool.join_any` routes by id shape.
   - A linked auto row whose tab navigated (the new URL still matches the pattern) follows the new URL, with one log line. Typed rows are exempt.
   - A typed row (`UrlRow.typed`, set by `add_url` / `edit_url`, appended last, RULE 13) is never auto-removed: when its tab goes, it is unlinked instead.
   - Pooled Firefox pages refresh their url/title from the listing.
   - A Firefox line follows the summary on change or on a manual pass: `🦊 Reconcile: +a firefox added, −r firefox removed, s firefox steady`.
3. **Pool join** (`firefox_pool.join_firefox`):
   - `fox_page_info` builds `PageInfo(browser="firefox", profile=label)` and hands it to `finish_pool_join(bridge, info, None, None)`: no client, badge or owner probe.
   - The alias is `{profile}_{NNNN}` (`format_alias(owner, no, hint=profile)`).
   - The lane is derived (`page_conn`), never stored. `PageInfo._identity_dict` adds `browser`, `conn`, `browser_mark` ("🦊 " for Firefox) and `profile` to the wire form.
4. **Dispatch**:
   - `supervisor._cdp_down` blocks a pass only when no Firefox page is checked.
   - `batch_orchestrator._try_parallel` always uses the feeder when a Firefox page exists.
   - `resolve_and_claim_tab` returns a Firefox tab as is.
   - `multi_page_dispatcher._run_image_job` picks the lane (`is_uivision_page`).
5. **Firefox job** (`services/uivision_job.py`; deps seam `UiVisionDeps` built by `firefox_pool.install`, called from `start_url_reconciler`):
   1. The machine gate `UiVisionGate`: a held flag plus a "free at" stamp = last finish + `inter_run_delay_sec`. Every holder runs on the one event loop, so no lock is needed. The framework test shares the gate (`firefox_auto._gated_run`).
   2. Plan, in a thread (`firefox_pool.plan_job`): a fresh `FoxScanner.locate` → `locator.locate` → anchor/K.
   3. Run (`pool/run.py`, `run_pool_job`): provision the per-run macro `{macro}_pool.json` (a unique `run_stamp`) → `PoolSequence` scoped foreground (the mapped window only, never raise-all) → launch with `-profile` → `poll_log`. Stop = the user's cancel or the tab's Stop.
   4. Verdict: `verdict_error` → the image is marked FAILED with that reason. The finish counts the job and arms the tab's cooldown. `ctrl=None` makes `_best_effort_reset` a no-op (a Firefox tab has no chat to reset).
6. **UI**:
   - URL list CONN (`js/panels/url-list/conn.js`, `UrlListConn`) shows `🌐 cdp` / `🦊 uivision`, with the live dot for the pooled state. A Firefox row never borrows a Chrome match.
   - The Tab cell shows `#n alias` for both browsers. The pool row is marked 🦊 (`browser_mark`).
   - JOBS is click-to-edit (`js/core/jobs-edit.js`, styled by `css/jobs-edit.css`). It calls the new slot `set_page_jobs` (frozen surface 142 → 143) in the new panel `ui/panels/pool_jobs.py`, which overwrites both the live counter and the store (`cooldown_store.set_job_count`). Without the overwrite, the store's max-merge would bring a lowered count back.
   - The Firefox window gains `faInterRunDelay` (Delay between runs, 0–30 s, default 3; before it, every save reset the delay to 3). `faPoolHint` explains that checked profiles feed the pool (xfile only).

## 5. Files and metrics (lines / max CC, radon: before → after)

| File | Before | After | Change |
|---|---|---|---|
| `core/tab_alias.py` | 187 / 8 | 240 / 8 | `format_alias(hint=)`; id shape → browser / conn |
| `core/models.py` | 283 / 5 | 284 / 5 | `UrlRow.typed=False` appended |
| `browser/page_status.py` | 149 / 3 | 160 / 3 | `profile` field; `_identity_dict` wire keys |
| `browser/uivision/tabs.py` | 367 / 9 | 393 / 9 | `entries[index-1]`; `session_doc()` extracted |
| `browser/uivision/runner.py`, `sequence.py` | 497 / 9, 263 / 8 | same | `Recorder`, `macro_target`, `mapped_note` made public for reuse |
| `browser/uivision/pool/` (6 files) | new | 121 + 186 + 85 + 108 + 120 / ≤ 7 | identity, scan, locator, macro, run |
| `services/uivision_job.py` | new | 146 / 5 | gate + lane |
| `services/live/sources.py` | new | 122 / 8 | `TabListing`, held keys, URL follow, Firefox counts |
| `services/live/row_sync.py` | new | 150 / 9 | row half of a pass (split from reconcile) |
| `services/live/reconcile.py` | 375 / 10 | 296 / 8 | held keys, Firefox line; rows moved out |
| `services/live/url_policy.py` | 294 / 7 | 311 / 7 | typed rows unlink (ideal-size note) |
| `services/live/supervisor.py` | 181 / 8 | 185 / 8 | Firefox-aware "cdp down" |
| `services/auto_connect.py` | 302 / 9 | 311 / 9 | `join_handle` (ideal-size note) |
| `services/batch_orchestrator.py` | 437 / 7 | 441 / 7 | Firefox in parallel/claim |
| `services/multi_page_dispatcher.py` | 455 / 8 | 466 / 8 | lane pick |
| `services/cooldown_service.py` | 869 / 9 | 871 / 9 | no-ctrl reset skip |
| `persistence/cooldown_store.py` | 254 / 9 | 269 / 9 | `set_job_count` |
| `ui/services/firefox_pool.py` | new | 201 / 8 | listing, join, job plan, deps wiring |
| `ui/panels/pool_jobs.py` | new | 48 / 4 | `set_page_jobs` slot |
| `ui/panels/browser_tabs.py` | 644 / 7 | 647 / 7 | `live_deps` merges Firefox |
| `ui/panels/page_pool.py` | 316 / 7 | 320 / 7 | Firefox rejoin |
| `ui/panels/firefox_auto.py` | 250 / 7 | 265 / 7 | gated test run, delay field |
| `ui/panels/url_queue.py` | 275 / 6 | 282 / 6 | typed rows (`_apply_edit`) |
| `ui/services/arena_serialize.py`, `undo_entries.py` | 92 / 5, 407 / 7 | 104 / 5, 409 / 7 | `typed` round-trip |
| JS `url-list/conn.js`, `core/jobs-edit.js` | new | 37, 76 | CONN cell, JOBS edit |
| JS `cdp-render.js`, `page-pool/render.js`, `firefox-auto.js` | 120, 95, 254 | same | line-neutral hooks (JS ratchet) |

All new code (Python and JS) is within RULE 16:
- The worst new function has 18 LOC, CC 9, cognitive 12, nesting 3 and 4 params.
- The largest edited legacy function (`runner._wait_for_unmatched`, 25 LOC) changed only by a type rename.
- All 117 new functions are exercised by tests.

For RULE 18, every file above 300 lines carries an `# ideal-size` note. `url_policy.py` crossed 300 in this change; the others were already over. `ui/panels/` reaches 19 files, and its note names the flat packing contract. `index.html` has a note, and the JOBS style went to `css/jobs-edit.css`, so `arena.css` did not grow.

## 6. Tests and verification

- New Python tests (82): `tests/test_fox_{tab_kind,identity,scan,locator,macro,run,lane,reconcile,pool_ui,dispatch}.py`. New JS tests (10): `tests/js/test_fox_conn_jobs.mjs`.
- Edited tests: `test_bridge_slots.py` (slot + packing), `test_browser_config_slots.py`, `test_url_receivers.py`, `test_panel_browser_tabs.py`, `test_live_reconcile.py`, `tests/js/test_firefox_auto_panel.mjs`.

| Check | Before | After |
|---|---|---|
| pytest | 2242 passed, 13 skipped | 2324 passed, 13 skipped |
| JS (`npm run test:js`) | 384 pass | 394 pass, 4 skipped, 0 fail |
| coverage line / branch | 89.52 / 86.38 % | 90.00 / 86.99 % |
| `verify_quality.py --allow-legacy` | 0 fails, 3 legacy warns | 0 fails, the same 3 legacy warns |

`tests/test_verify_quality_tool.py` can fail under `-n 4` both before and after this change (its tests share probe files in the tree), so the count above runs it serially (7 passed, 7 skipped).

## 7. Rejected

- `selectWindow url=`: E209 (tried in the previous round, PR #5).
- `selectWindow tab=0`: it hits the autostart tab while that tab is still open.
- A relative scan anchored on the autostart tab: it self-closes after 500 ms, so it is racy.
- A macro-side tab loop (`while_v2` over `tab=i`): untestable here and slow (one DOM wait per tab).
- A packed `cmd_var3` parsed in `executeScript_Sandbox`: variable rendering differs by Ui.Vision version (raw vs JSON).
- `storage=browser` for pool jobs: an imported macro cannot change per run.
- A Firefox `browser` field persisted on `UrlRow`: it was removed on purpose before; it is derived from the id instead.
- A 16th `PagePool` method for Firefox joins: over the class cap; `add_page` already fits.
- A `FinishCtx.reset` field: `ctrl=None` already means "nothing to reset".
- An `asyncio.Lock` gate: on Python 3.11, `wait_for(lock.acquire())` can leak the lock on timeout. A flag plus a "free at" stamp on the one loop cannot.
- The JOBS slot on `PagePoolMixin`: no method headroom (RULE 16 ratchet). A panel file with 0 slots breaks the packing table, so the slot got its own panel.
- Claiming Firefox tabs only while the gate is idle: the pool pick cannot see the gate without a new cross-layer flag. Claim-then-wait is logged instead.
- Metric games: no `_part1/_part2` helpers and no lambda tables hiding branches.

## 8. Limits (documented, not hidden)

- Every Firefox job marks its image FAILED on purpose (decision 1) until image processing via Ui.Vision exists.
- No captcha detection for Firefox yet (owner decision).
- Pool runs need `storage=xfile`. `storage=browser` is refused by name.
- Session-store lag is ≤ 15 s (`browser.sessionstore.interval`). A tab opened or closed in Firefox shows up or goes on the next write.
- Old Ui.Vision builds had a multi-window bug in the `tab=` fallback (their own comment). The URL check still refuses a non-worker page.
- When several profiles share the active title, the OS window is ambiguous: nothing is raised and `bringBrowserToForeground` decides (unchanged rule from 2026-09-25).
- The reconcile `Report` counts a removed duplicate row twice. This predates I-64 and was left alone.

## 9. As built vs the first plan

- The id-shape helpers went into `core/tab_alias.py`; there is no `core/tab_kind.py`.
- The Firefox wiring lives in `ui/services/firefox_pool.py`, not `ui/panels/`. A panel file must carry slots.
- `TabListing` carries `held_rows` / `held_pages` / `answered` instead of `.down`, so an empty Chrome answer and a silent Firefox are told apart.
- The gate is a flag plus a stamp, not an asyncio lock (see section 7).
- There is no `FinishCtx.reset` and no `PageInfo.conn` property; the wire form derives `conn`.
- The row half of reconcile moved to `live/row_sync.py` (RULE 18).
- Added in the UI: the `faInterRunDelay` field, the `faPoolHint` note, and the `pool_jobs.py` panel.
