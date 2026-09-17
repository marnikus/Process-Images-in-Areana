# Job Cycle & Cooldown — Design (2026-09-16)

User spec: 01 post-generation reset (auto-click New Chat, wait full load before
ready), 02 minimum pause between jobs (user-set, e.g. 5 min), 03 per-tab
cooldown countdown (reset/edit anytime, independent sessions), 04 captcha
penalty (user-set extra, e.g. +15 min, stacks, per-tab).

New-chat element (user HTML): `li[data-sidebar="menu-item"] >
a[data-sidebar="menu-button"][href="/image/direct"] > span "New Chat"`.

## 1. Research — where things live today

| Concern | File | Finding |
|---|---|---|
| Tab pool | `app/browser/page_pool.py` (175 LOC, 15 methods = AT LIMIT) | steady/busy only; `add_page` CC 9, `wait_for_free_page` CC 8 — do not add branches |
| Tab state | `app/browser/page_status.py` (59 LOC, 3 methods) | room for cooldown fields + 3 small methods |
| Parallel dispatch | `app/services/multi_page_dispatcher.py` (338 LOC) | `run_one_image_on_page` LOC 23 CC 7; `_acquire_page` LOC 19 CC 8; finally marks steady |
| Single job blocks | `app/services/single_job_runner.py` (458 LOC) | `check_security` LOC 24 CC 6 detects captcha at job start |
| Single-page batch | `app/ui/bridge.py` `_do_run_batch` (legacy, ~1240 LOC) | captcha handled at CHECK_SECURITY + during generation; sequential loop |
| Selectors | `app/browser/site_adapter.py` (legacy) | no new-chat entry yet |
| Session config | `app/persistence/config_manager.py` (legacy) | watcher pattern: `watcher_*` keys — cooldown follows it |
| Pool UI | `app/ui/web/js/panels/page-pool.js` + `index.html` | 5 s poll, columns Tab/Title/URL/Status/Job/Action |

Latent bug (out of scope, not fixed here): `single_job_runner._mark_waiting/
_mark_busy` call `bridge._ensure_page_pool()` which does not exist on Bridge —
calls fail silently inside try/except, so pool WAITING status is never set.
New code uses `bridge._page_pool` directly via getattr.

Baseline: `pytest tests/` 95 passed. `verify_quality --changed --allow-legacy`
PASSED. radon: new code must stay CC ≤10 (fail) / ≤7 (prefer).

## 2. Design

New files (each one responsibility, RULE 18 file 150–300 / function 4–20):

- `app/core/cooldown.py` (~110 LOC leaf): pure primitives, no Qt/CDP —
  `CooldownConfig`, `clamp_seconds`, `config_from_dict/to_dict`,
  `remaining_seconds`, `is_cooling`, `cooldown_total`, `format_remaining`.
- `app/browser/new_chat.py` (~150 LOC): `ResetCtx`, `NEW_CHAT_CANDIDATES`,
  `build_page_loaded_js`, `build_composer_empty_js`, `reset_to_new_chat`.
  Clicks via shared visual runner (`find_and_click`, RULE 1), reports via
  engine (RULE 2). Selectors semantic-first (RULE 21): `a[href="/image/direct"]`
  + span text, structural `li[data-sidebar]` fallback, zero Tailwind classes.
- `app/services/cooldown_service.py` (~200 LOC): sync pool ops
  (`load_config`, `start_cooldown`, `add_captcha_penalty`, `reset_cooldown`,
  `edit_cooldown`, `refresh_expired`, `longest_remaining`,
  `cooldown_aware_timeout`, `remaining_for`) + async cycle
  (`FinishCtx`, `finish_page_after_job`, `wait_for_tab_ready`).

Edits (minimal, measured against gates):

- `page_status.py`: `PageStatus.COOLDOWN`; fields `cooldown_until`,
  `cooldown_total`, `captcha_count`, `pending_penalty`, `last_job_at`,
  `cooldown_reason`; methods `remaining_seconds/is_cooling/try_expire`;
  `to_dict` + raw keys (snapshot injects live `cooldown_remaining`).
- `page_pool.py`: NO new methods (15 = limit). One-line `p.try_expire()` in
  `get_free_page/acquire_free_page/get_counts`; `status_snapshot` + cooling
  count + remaining. CC stays ≤9 everywhere.
- `site_adapter.py`: `new_chat_button` entry (primary + 2 fallbacks, text
  condition "New Chat", lastVerified 2026-09-16).
- `config_manager.py`: `cooldown_enabled=True`, `cooldown_min_seconds=300`,
  `cooldown_captcha_penalty_seconds=900`.
- `single_job_runner.py`: `_apply_captcha_penalty(ctx)` helper + 1 call in
  `check_security` after solve (check_security 24→25 LOC, CC unchanged).
- `multi_page_dispatcher.py`: finally → `finish_page_after_job` (reset, then
  cooldown or steady; cancel skips cooldown); `_acquire_page` + `_get_free_page`
  use `cooldown_aware_timeout` (600 → max(600, longest+60)).
- `bridge.py` (legacy, thin slots ≤20 LOC each): `get_cooldown_config`,
  `set_cooldown_config`, `reset_page_cooldown`, `set_page_cooldown`;
  `get_page_pool_status` refreshes expired first; arena preset save/load carry
  cooldown keys; `_do_run_batch` single path: cooldown gate before each image,
  finish (reset+cooldown) after each image, captcha penalty at both solve
  points. Reset failure never blocks: log + cool anyway (baseline + JOB-ID
  verification handle a dirty page).

Semantics:

- Cooldown starts after EVERY finished job (success or failure); cancel skips
  it (user-initiated stop, next start is deliberate). `total = base + pending
  captcha penalty`; countdown `until = now + total`.
- Captcha: `captcha_count += 1` per detection; cooling tab extends `until +=
  penalty` immediately, otherwise accumulates `pending_penalty` applied at next
  `start_cooldown`. Per-tab counters — tab B unaffected (tested).
- `reset_cooldown` on a BUSY/WAITING tab clears pending penalty only, never
  frees a running job. `edit_cooldown` refuses BUSY/WAITING; on STEADY with
  seconds > 0 it parks the tab (reason "manual"); 0 = ready now.
- Ready = STEADY. `is_free()` unchanged (STEADY + connected); expiry flips
  COOLDOWN→STEADY inside locked reads, the 5 s UI poll, and wait loops
  (RULE 7 cancel/pause honoured in `wait_for_tab_ready`).
- Unknown tab in ops → False/-1 (RULE 4 empty vs broken, fail-open with warn
  so a missing pool entry never deadlocks a batch).

UI (`index.html`, `page-pool.js`, `settings.js` — not Python-gated):

- Pool table: new Cooldown column (`MM:SS / MM:SS`, `🛡xN`, pending `+MM:SS`),
  status colour orange for cooldown, per-row Reset/Edit (Edit via shared
  `Dialog.promptName`, minutes) + existing disconnect; header adds Cooling
  count; 1 s local tick updates countdown text between 5 s truth polls.
- Settings: Job Cycle & Cooldown section (enabled, min minutes default 5,
  captcha minutes default 15) via `get/set_cooldown_config` (seconds on wire).

## 3. Decisions & rejected alternatives

- Reset as automatic post-job step, NOT an Action Block: spec says auto-click
  after every job; a toggleable block risks dirty-page reuse. Uses visual
  runner so RED/ORANGE confirmations still show.
- Pool ops as service functions, not `PagePool` methods: class already at 15
  methods (fail >15). Same for `try_expire` living on `PageInfo` (3→6
  methods) instead of a pool helper — single source, no duplication.
- Session keys (watcher pattern), not `AppSettings`: avoids growing
  preset/state schema; still storable via arena preset doc keys.
- Dishonest reductions rejected: no `foo_part1` splits (dispatcher file
  338→~350, runner 458→~470 stay over the 150–300 *preference* — documented
  here instead of fake-split); no `**kwargs` to dodge params (FinishCtx/
  ResetCtx dataclasses instead); no lambda dispatch; expiry lives in one
  method (`try_expire`), not copied per call site.

## 4. Test plan (RULE 8, tests first)

- `tests/test_cooldown.py`: config clamp/round-trip, remaining/ready edges,
  total math, format `MM:SS`/`H:MM:SS` (~12 unit tests, <10 ms).
- `tests/test_cooldown_service.py`: real `PagePool`, fake bridge (
  SimpleNamespace): cooling blocks acquire, expiry frees, reset/edit rules,
  penalty stacking + per-tab independence, dynamic timeout, wait cancel/fast
  paths, finish normal/cancelled/disabled with monkeypatched reset (~14 tests).
- `tests/test_new_chat.py`: candidates/JS builders, click fallback order via
  monkeypatched `find_and_click`, loaded-wait success/timeout/cancel with
  scripted fake ctrl/client (~8 tests).
- Existing suite must stay green (95 passed); new snapshots keys are additive.

## 5. Docs updated in same change (RULE 17)

- `docs/current/SYSTEM_OF_RECORD.md`: behaviour row 21, invariants
  I-24..I-27, storage keys, pool UI, history pointer here.
- `docs/current/DOM_SELECTORS.md`: section L (new-chat + page-loaded).
- `docs/README.md`: archive entry.
- No new rule; no renumbering.
