# S6 — Python-owned URL reconciler + the interval setting (D-12R)

*Chain stage 6 of the staged chain per `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/`,
implemented 2026-09-21 on top of S5 (`1ca6428` + the S5 commit). Contract:
`tdd-interfaces.md` §S6 → SoR **I-50**.*

## What landed

- **`app/services/live/url_policy.py`** (new, 176 LOC) — pure URL-row policy:
  `RemovalSpec`/`Removal` dataclasses, `removable_rows(spec)` as a **predicate table**
  (no if/elif, RULE 19 step 2: `duplicate → invalid → pattern_mismatch → tab_gone`,
  busy-tab deferral via `spec.deferred`, RULE 15), `advance_misses` hysteresis
  (`MISS_THRESHOLD = 2`, reappearance resets), moved-panel delegations
  `dedupe_rows`/`add_rows` (from `url_queue._dedupe_state_rows`/`_add_missing_rows`,
  byte-for-byte behaviour — a 6-shape pair test equates them), URL-keyed checkbox
  memory `remember`/`restore_enabled` (bounded `MEMORY_MAX = 200`), `removal_lines`
  one line per row with the reason spelled out (RULE 2 vocabulary).
- **`app/services/live/reconcile.py`** (new, ~180 LOC) — the reconciler loop:
  `LiveDeps(fetch_tabs, join_tab, commit, log)` injected (services never import ui);
  `reconcile_once(bridge, deps, source)` = one pass: fetch → removal table →
  claim/add → join → presence (`sync_pool_presence`) → commit + `wake("urls")`,
  ALL removals by reason-labeled table, empty fetch keeps every row (safety),
  every pass attempt recorded (`last_pass_at`/`passes`); `Report(added, linked,
  removed, joined, revived, stale, deferred)`; `reconcile_loop` waits
  `live_bus(bridge).wait(interval_ms/1000)` between passes with interval read
  **every pass** (never cached, wake-able); one-loop guard `start_reconciler`.
- **`app/services/live/debug_view.py`** (new, ~45 LOC) — the cadence object:
  `CONFIG_KEY`, `clamp_interval_ms` (500..60_000, garbage → 5000 — the ONLY clamp
  owner; reads are unclamped), `interval_ms(bridge)` (getter-presence defensiveness
  so a minimal fake bridge can't crash `emit_arena_state`), `cadence(bridge)` =
  `{url_interval_ms, last_pass_at, passes}`.
- **Config/session**: `DEFAULT_SESSION["url_reconcile_interval_ms"] = 5000`.
- **`app_settings.apply_url_interval(bridge, data)`** — writes the clamped value,
  logs one line, `live_bus(bridge).wake("interval")`; called from `save_settings`
  (no new slot, D-20).
- **`layout_state.emit_arena_state`** — publishes `prog["live"] = cadence(bridge)`
  (the control's only read path — there is no getter slot).
- **`browser_tabs.live_deps(bridge)`** — the UI-side wiring onto the real bridge
  (`fetch_tabs` over the cdp client, `join_tab` = `do_connect_page_pool`,
  `commit` = save+emit WITHOUT undo, `log` late-bound lambda); `do_auto_connect_scan`
  rewritten as a guard wrapper over `reconcile_once` (manual still always answers);
  `start_url_reconciler(bridge)`; prune block deleted (`plan_auto_sync`,
  `apply_auto_plan`, `report_auto_plan`, `prune_auto_rows`, `claim_auto_rows`,
  `plan_has_changes`, `auto_prune_allowed`, `auto_scan_pass`, `join_new_tabs`) —
  the passive idle-only prune is superseded by the removal table (D-4/round-1 §5.1).
- **`main_window._build_ui`** — boot-starts the reconciler (+1 line).
- **JS**: `panels/url-list/interval.js` (new, 70 LOC) — `UrlInterval` control
  (init/clamp/applyValue/load/save/_bindLive; `Boot.bindOnceById` dedupe;
  only ever reads the pushed `progress_updated.live` payload, never round-trips);
  `index.html` cooldown bar gains 🔁-interval input + Save; `arena-app._PANEL_INITS`
  gains `UrlInterval`; **`cdp.js` loses the 15 s `setInterval`** (the Python
  reconciler is the single periodic writer, RULE 10); the 4 s boot kick and the
  500 ms `ensurePrimary` tick stay.
- **`package.json`** — `test:js` lists `test_url_interval_control.mjs`.

## Tests (RED → GREEN)

- New `tests/test_url_policy.py` (12) — RED at `ModuleNotFoundError`; the removal
  reason matrix, busy-tab deferral with a REAL `PagePool` (`current_image` via
  `cooldown_service.set_tab_image`), never-linked rows kept, hysteresis cadence,
  pair-tests against the moved panel helpers, bounded memory, vocabulary lines,
  source-lock "table not chain".
- New `tests/test_live_reconcile.py` (13) — RED at collection; real rows through
  injected fakes (`FakeDeps` — real `Report` semantics, no test doubles at the seam:
  the seam IS `LiveDeps`): empty-fetch safety incl. raising fetch, add+claim+join
  with `wake("urls")`, removal hysteresis ×2, runs identically in idle/running/paused,
  commit without undo (bridge has NO undo_service at all), remembered checkbox
  survives close→reopen by URL, interval-per-pass spy + wake cadence with a REAL
  `LiveBus`, surviving loop crash with loud warn + manual pass recorded,
  `cdp.js` source-lock ("the 15 s timer is gone", exactly one `setInterval` left).
- New `tests/test_url_interval_setting.py` (11) — RED at collection; config
  default 5000, clamp matrix (1→500, 60001→60000, "abc"/None→5000, 2500→2500),
  persist-only-when-key-present through a REAL `ConfigManager`, the value is
  published in `progress_updated.live.url_interval_ms` (via a REAL bridge +
  harness recorders), `wake("interval")` recorded by the same bus the loop waits
  on, `cadence` shape, source-lock "no new `@Slot`".
- New `tests/js/test_url_interval_control.mjs` (7) — RED at ENOENT; harness-A
  module sandbox: publishes itself, load without bridge call, bind-once init,
  clamp on save (99999 → 60000 → `save_settings` payload), garbage → 5000,
  live-push wiring through `progress_updated.connect`, frozen url-list file
  baselines for THIS repo (62/48/166/38/105/137 — recorded from the actual files,
  the plan's earlier snapshot numbers were off-by-one).
- Adapted `tests/test_panel_browser_tabs.py`: the three auto-connect cases are
  rewritten for the new seam — `live_deps` wiring test (fetch/join/commit/log
  late-bound; commit == save+emit, no undo), `do_auto_connect_scan` manual/auto
  vocabulary through a monkeypatched `reconcile_once` (the seam, fresh bound per
  call), end-to-end scan against a REAL cdp_stub_server + real `PagePool` (row
  added, only pattern-matching tab joined, second scan quiet, busy-guard +
  boom paths).

## Adaptations vs the plan (documented deltas)

1. **`remember`/`restore_enabled` are URL-keyed**, not row-id-keyed — rows die and
   re-add when a tab closes/reopens; the URL is the identity that survives
   (found when the close→reopen test flipped a fresh row's checkbox back on).
2. **`_commit_and_log` derives `changed` from the `Report`** (5 → 4 params) — the
   report IS the change set; recomputed inside, never passed twice.
3. **`main_window` start folded to one physical line** (class-LOC ratchet pinned
   at 123) instead of a separate comment+statement pair.
4. **`auto_prune_allowed`/`-prune` deleted entirely** (not made compatible) — the
   removal table has a wider, reason-labelled mandate; old idle-gated semantics
   would have left a dead half-concept. Where tests asserted the old gating,
   they now assert the new one.
5. **`interval_ms` tolerates a config without `get_state`** — `emit_arena_state`
   must never refuse to publish `live` just because a fake bridge is minimal.
6. **Frozen-file baselines recorded from the repo as-is** (off-by-one vs the
   plan snapshot — asserted actual, not re-recorded).

## Gate numbers

- `bash tools/stage_gate.sh --js` — **all 5 lanes green**: quality ratchet
  **0 fails** (with the reconcile split: `_commit_and_log` ≤ 4 params,
  `reconcile_once` ≤ 30 LOC / CC ≤ 10; `main_window` class LOC at baseline);
  frozen seams **88 passed, 1 skipped** (134 slots exact, window table, cooldown
  4-arg wait untouched); suite **1745 passed, 11 skipped** (S6 adds 39 tests);
  characterization goldens **14/14 identical**; JS lane **247 passed / 0 failed**
  (+7 new).
- Sizes: `url_policy.py` 176, `reconcile.py` ~180, `debug_view.py` ~45,
  `interval.js` 70 — all inside RULE 18 ideal-size (and below the plan's budgets).
- Frozen JS lanes re-measured: `arena-app.js` unchanged metric set apart from
  the appended panel name, `cdp.js` shrinks (one dead line out); frozen url-list
  files byte-stable by the D-24a line-count guard.

## Rules ledger

- RULE 16: quality ratchet zero fails through the TDD loop; `--record-baseline`
  never invoked.
- RULE 18: every new file well inside 150–300 (services) / ≤70 LOC JS; removals
  (`browser_tabs.py` 544 → 469) go in the RULE 18.2 direction.
- RULE 8: tests keep real seams — real `PagePool`, real cdp_stub_server, real
  `ConfigManager`, real `LiveBus` cadence; positive controls next to every
  zero-activity assertion (a sibling pass that MUST add/removes).
- Frozen seams untouched: Σ slots = 134; `wait_captcha_cleared` 4-arg;
  `PagePool.add_page` CC at limit; window table agreement §0.2 intact
  (`urlCooldownBar` ids only appended, no id reshuffles).
