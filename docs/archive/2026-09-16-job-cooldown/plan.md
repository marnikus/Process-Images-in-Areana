# Job Cycle & Cooldown Logic — Plan

Date: 2026-09-16

## Requirements Summary

01 POST-GENERATION RESET — After each generation, webpage returns to a clean new chat — Auto-click "new chat" trigger after job completes — Wait until full page is loaded before marking tab as ready

02 MINIMUM PAUSE BETWEEN JOBS — User sets a minimum cooldown between generations (e.g. 5 min) - add this control element on the URL list win — Prevents spamming jobs every minute — Tab shows "ready" status only after cooldown expires than ready to receive new job only

03 COOLDOWN TIMER PER TAB — Each webpage link displays a countdown timer showing time until next run - add this display on the URL list win item — User can reset or edit the cooldown timer at any time - add this control element on the URL list win on each url item — Each tab operates independently as a separate session but still has one queue of images to process

04 CAPTCHA PENALTY — Each captcha detection adds extra time to the cooldown (e.g. +15 min on first captcha) on individual account webpage url — User configures the extra penalty duration per captcha event - add this control element on the URL list win — Repeated captchas stack additional cooldown time — Penalty is per-tab — does not affect other tabs

Provided new chat element: `<li data-sidebar="menu-item"><a data-sidebar="menu-button" href="/image/direct"><span>New Chat</span></a></li>`

## Research Findings

### Existing Codebase
- `app/browser/page_pool.py` PagePool with RLock, PageWaitOpts event-driven, status_snapshot; no cooldown fields, is_free = steady+connected only
- `page_status.py` PageStatus STEADY/BUSY/WAITING_GENERATION/WAITING_CAPTCHA/ERROR/DISCONNECTED, PageInfo is_free = steady+connected, no cooldown fields
- `site_adapter.py` SELECTORS dict (model_label, processing_spinner, add_files_button, file_input, prompt_textarea, send_button, output_region, output_image, security_dialog, recaptcha_iframe) — no new_chat
- `url-list.js` render table checkbox/url/status/conn-status/error/buttons Connect/Test/Edit/Remove, no cooldown UI
- `page-pool.js` shows total/steady/busy/badge parallel ready
- `multi_page_dispatcher.py` + `job_runner.py` round-robin no cooldown
- `cdp_arena.py` has JS_FIND_TEXTAREA, JS_INSERT_PROMPT, JS_CLICK_SEND, JS_PAGE_READY, JS_SECURITY_DIALOG, capture_baseline, attach_image, insert_prompt, but no new_chat click
- `core/models.py` UrlRow id/url/enabled/last_status/last_checked/error, no cooldown_seconds/cooldown_until/captcha_penalty
- `watcher.py` detects captcha/generation, shows overlay, pauses jobs, but does not apply penalty
- `bridge.py` large (4233 LOC 144 methods legacy) hosts PagePool, WatcherService, bg loop

### Target Site (arena.ai/image)
- SSR shell only via fetch_page — no message HTML, confirms need for live CDP inspection
- New Chat button: semantic selector `a[href="/image/direct"]` with span "New Chat", inside `li[data-sidebar="menu-item"]`
- Stable selectors: use href attribute (semantic, not generated IDs), visible text "New Chat", data-sidebar attributes
- Risks: sidebar may be collapsed, button may be hidden; need fallback to `li[data-sidebar="menu-item"] a[href="/image/direct"]`, `a[data-sidebar="menu-button"][href="/image/direct"]`
- Fallbacks: scan all `li[data-sidebar="menu-item"] a` for text contains "New Chat"

### Quality Gates (RULE 16/18/19)
- Current: 95 tests green, PagePool 176 LOC, Bridge 4266 LOC legacy
- Target: file 150-300 LOC ideal, func 4-20 LOC ideal, LOC≤30 fail, CC≤10 fail, nesting≤4, params≤4, methods≤15, class LOC≤150
- New pure module `app/core/cooldown.py` ~210 LOC ideal, funcs 4-20 lines, CC≤10
- Refactor PagePool into core (≤150 LOC, 14 methods) + cooldown manager (≤150 LOC) + wrapper (≤150 LOC, ≤15 methods)
- JobCycleService: split into small helpers ≤30 LOC, CC≤10, params≤4 using dataclass ctx
- MultiPageDispatcher: split _find_url_row_for_tab, _run_job_with_cycle with CycleRunCtx dataclass
- SingleJobRunner check_security: split into _is_captcha_visible, _log_captcha, _show_overlay, _apply_penalty, _hide_overlay

## Design

### Data Model
- UrlRow: add cooldown_seconds int default 300, cooldown_until Optional[str], captcha_penalty_seconds int default 900, captcha_count int default 0, last_completed_at Optional[str], total_cooldown_penalties int default 0
- PageInfo: add cooldown_until, cooldown_seconds, captcha_penalty_seconds, captcha_count, last_completed_at, new status COOLDOWN, methods is_in_cooldown(), remaining_cooldown(), is_free() checks cooldown
- AppSettings: add cooldown dict {min_cooldown_seconds 300, captcha_penalty_seconds 900, post_generation_reset True, reset_timeout_sec 15, countdown_update_ms 1000}

### Pure Logic Module `app/core/cooldown.py`
- now_epoch(), now_iso(), parse_iso_to_epoch(), epoch_to_iso()
- calculate_cooldown_until(last_completed_epoch, cooldown_seconds, now) -> epoch
- is_in_cooldown(cooldown_until_epoch, now) -> bool
- remaining_seconds(cooldown_until_epoch, now) -> int
- format_remaining(remaining_sec) -> str "5s", "5m 23s", "1h 5m", "ready"
- apply_captcha_penalty(current_until_epoch, penalty_seconds, now) -> new_until (stacks)
- should_allow_job(status, cooldown_until_epoch, is_connected, now) -> bool
- cooldown_info(cooldown_until_iso, now) -> dict {in_cooldown, remaining_sec, remaining_str, until_iso, until_epoch}
- calculate_next_cooldown_iso, next_ready_after_penalty

### PagePool Cooldown Handling
- `page_pool_core.py`: original steady/busy tracking, no cooldown, 14 methods, ≤150 LOC
- `page_pool_cooldown.py`: pure functions set_cooldown, reset_cooldown, apply_penalty, is_in_cooldown, remaining, check_cooldowns, mark_steady_with_cooldown — each ≤30 LOC, CC≤10
- `page_pool.py`: inherits from core, overrides mark_steady to check cooldown, adds set_cooldown, reset_cooldown, apply_captcha_penalty, is_in_cooldown, get_cooldown_remaining, check_cooldowns — 9 methods, ≤150 LOC

### Post-Generation Reset
- Add selector `new_chat_button` to site_adapter: primary `a[href="/image/direct"]`, fallbacks `li[data-sidebar="menu-item"] a[href="/image/direct"]`, `a[data-sidebar="menu-button"][href="/image/direct"]`, text search
- CDPArenaController: JS_CLICK_NEW_CHAT with semantic selectors, visible check, text contains "New Chat"
- Methods: click_new_chat() highlights then clicks, reset_to_new_chat(timeout_sec) clicks then waits is_page_ready loop up to timeout
- Integration: after job completes in multi_page_dispatcher.run_one_image_on_page, call job_cycle_service.handle_job_completed_cycle which does reset + set cooldown + emit states

### Cooldown Timer Per Tab
- PagePool.is_free() now checks is_in_cooldown() -> not free if in cooldown
- PagePool.check_cooldowns() moves COOLDOWN -> STEADY when expired, called in get_counts, status_snapshot, and before acquiring free page
- Bridge: _arena_to_js includes cooldown fields + cooldown_info calc, new slots set_url_cooldown, reset_url_cooldown, set_url_captcha_penalty, get_url_cooldown_status, set_global_cooldown, get_global_cooldown, reset_all_cooldowns
- UI url-list.js: render cooldown timer column, countdown ticker setInterval 1s updating remaining, edit cooldown (prompt), edit penalty (prompt), reset button, global controls min cooldown + penalty + post-gen reset checkbox + apply to all + reset all

### Captcha Penalty
- Each captcha detection adds extra time to cooldown per tab, stacks
- single_job_runner.check_security: after detecting captcha, calls handle_captcha_detected_cycle via JobCycleCtx
- watcher.py: when captcha detected, calls _apply_captcha_penalty_for_current_tab which finds tab_id via cdp client _current_tab_id, finds matching UrlRow, applies penalty via job_cycle_service
- Penalty per-tab only, does not affect other tabs
- User configures penalty duration per captcha event via URL list win controls

### Job Cycle Flow
1. Acquire free page (is_free checks cooldown)
2. Run job blocks (baseline, security check with penalty, attach, prompt, submit, wait, download, save)
3. After job completed (success or fail), trigger reset_to_new_chat (click New Chat, wait page ready)
4. Set cooldown_until = now + cooldown_seconds (from UrlRow or global)
5. Mark page as COOLDOWN, not STEADY, emit pool status
6. Tab shows countdown timer, ready only after cooldown expires (check_cooldowns moves to STEADY)
7. If captcha detected during job or watcher, apply penalty: new_until = max(now, current_until) + penalty_seconds, increment captcha_count, set COOLDOWN

## Implementation Steps

1. Create app/core/cooldown.py pure logic
2. Extend UrlRow + AppSettings + AppState.from_dict safe handling
3. Extend PageInfo with cooldown fields, COOLDOWN status, is_in_cooldown, remaining_cooldown, is_free checks cooldown
4. Refactor PagePool into core + cooldown manager + wrapper to meet RULE 16
5. Add new_chat_button selector to site_adapter
6. Add click_new_chat + reset_to_new_chat to CDPArenaController
7. Create job_cycle_service.py with JobCycleCtx dataclass, small helpers, handle_job_completed_cycle, handle_captcha_detected_cycle
8. Update multi_page_dispatcher to check cooldowns, use CycleRunCtx, call job_cycle_service after job
9. Update single_job_runner check_security to split helpers and apply penalty
10. Update watcher to apply penalty per tab
11. Update bridge _arena_to_js + new slots for cooldown management
12. Update url-list.js with countdown timer, edit/reset controls, global controls
13. Update page-pool.js to show cooldown status
14. Update index.html to add global cooldown controls UI
15. Add unit tests test_cooldown, test_page_pool_cooldown
16. Run pytest 107 green, verify_quality --changed --allow-legacy PASSED
17. Push

## Rejected Gaming

- No foo_part1, no helper that just splits code without responsibility
- No anti-gaming: no suppressing radon via comments, no fake complexity reduction
- No bypassing captcha, only pause + USER_ACTION_REQUIRED
- No generated IDs, blob URLs, session URLs, long utility classes — use semantic selectors
- No DB, persist via JSON as before

## Risks & Mitigations

- New Chat button may be hidden if sidebar collapsed -> fallback scan all li[data-sidebar] for text "New Chat", also try reload as fallback
- Page ready after New Chat may take time -> wait loop up to reset_timeout_sec (user configurable 15s), log warning if not ready but still mark as clicked
- Cooldown timer drift -> use epoch seconds, update ticker every 1s in JS, server calculates remaining via ISO parsing
- Captcha penalty stacking may grow large -> cap at 86400s (24h) in bridge slots, but allow stacking beyond via multiple detections
- Multi-tab pool may have dedicated clients -> cooldown per tab independent, uses tab_id matching via url substring

## Verification

- pytest -q 107 passed
- verify_quality --changed --allow-legacy PASSED (0 fails)
- Manual UI: URL list win shows cooldown column with countdown, edit/reset buttons, global controls
- Page Pool win shows cooldown status with remaining seconds and captcha count
- After job completes, New Chat clicked, page waits ready, cooldown set, tab not free until expires
- Captcha detection adds penalty, stacks, per-tab only
