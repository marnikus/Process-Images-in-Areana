# Firefox account name & visual tab ID — research, design & delivery (2026-09-25)

> Task: replace Firefox `aka_0008` technical identifiers with real logged-in
> account name in URL List / Page Pool / worker views, plus a centered-top
> overlay `<visual number># <account>` matching Chrome.

## 1. Research first (understand → research/design → implement)

### 1.1 Firefox discovery chain (today)
```
uivision/tabs.py :: profile_sessions(profile_root)  — reads sessionstore.js / sessionstore.jsonlz4 / backups/recovery.js*
 ├─ selected_profiles() from firefox.ini / profiles.ini
 └─ tabs/{index,title,url,entry{url,title},closed,hidden}
       ↓
browser_tabs.py :: _firefox_rows(profiles)
 └─ filter: selected_profiles (if set) else display_active_only
 └─ pool_tabs.firefox_rows(profile, entries) → FirefoxPageInfo[]
       tab_id = f"{profile_dir}_tab{entry_index+1}"   # stable, profile-scoped
       label  = page label OR fallback "{profile_name} tab N"
       firefox_profile = profile_dir name (identity)
       firefox_display_name = profile name or dir   # BEFORE this task
       ↓
PagePool.add_page(info)
 └─ worker_no = next_global_visual_number (never reuses)
 └─ alias_no  = AliasBook.get_or_assign(worker_no, owner)  # owner == "" → aka_####
 └─ TabLabel snapshot stores display_name = AliasBook.alias_at(worker_no).display / fallback
```
Stable identity is `tab_id` (`{dir}_tabN`), never the visual number, title, URL or
overlay. Checked by `tests/test_pool_join_identity.py` and `tests/test_tab_alias_isolation.py`.

### 1.2 Where `aka_0008` comes from
* `AliasBook.format_alias(owner, alias_no)` → `aka_{no:04d}` when `owner` is
  empty after trimming, else `{local}@…` / cropped fallback.
* Firefox pages arrived with `owner == ""` because `firefox_owner.py` had no
  account probe (Chrome probe existed via `site_adapter.OWNER_EMAIL_SELECTORS` +
  `resolve_owners` + CDP `Runtime.evaluate`).
* The 8 in `0008` is the global alias counter (`_alias_next`), not tab index.
  Same account on two profiles → two workers with different `worker_no` (I-48,
  I-58 preserved).

### 1.3 URL List & Page Pool rendering (today)
* `app/ui/panels/page_pool.py :: leave_pool` → `render_worker_rows(pool.snapshot_rows())`
* `javascript/url-list/cells.js :: fillTabCell(state, el)` calls `TabLabel.of(state, key)`
  which reads `pool_snapshot/tab_label` (pool-owned truth, not a separate fetch).
* `javascript/page-pool/render.js :: _rowHtml(row)` prints `worker_no` pill +
  `TabLabel` badge (`email_####` / `aka_####` for Chrome, `aka_####` for Firefox
  before this task).
* Worker/debug views read the same `tab_label_of(tab_id)` / `tab_label_entries`.

### 1.4 Chrome visual-ID overlay (reused, not duplicated)
* `app/browser/worker_badge.py :: build_worker_badge_js(number, alias, attr)`:
  `#arena-worker-overlay{position:fixed;top:0;left:50%;transform:translateX(-50%);z-index:2147483647;pointer-events:none;…}`
  — centered top, never captures clicks, never alters layout, idempotent
  `querySelectorAll('[data-arena-worker]') → .remove()` before insert.
* `app/services/live/worker_badges.py :: assert_worker_badges()` + `_diff` + bounded
  precheck → `client.evaluate(javascript=...)` per visible Chrome tab.
* Reconciliation `reconcile/loop.py :: _join_and_sync` calls `resolve_owners` then
  `assert_worker_badges` **after** workers exist but **before** `_enforce_membership`.
  Chrome path was the only one asserting badges; Firefox had none.

### 1.5 Site evidence for Firefox account name
Saved HTML evidence: `<div class="font-heading min-w-0 flex-1 truncate text-left text-sm font-normal">mailreceiverpro@gmail.com</div>`
is **not** a stable single selector. Real DOM inspection shows it inside a
menu/account button where any of these is stabler:
* the user-info trigger itself (`[data-testid="user-menu"]`, `[aria-label*="account"]`,
  `[title*="mail"]`)
* the heading class above may be renamed — treat as **one** of several probes.

Hence `firefox_helpers.py :: ACCOUNT_EMAIL_SELECTORS = site_adapter.OWNER_EMAIL_SELECTORS + 5 evidence-backed fallbacks`
and `site_adapter` now carries the `font-heading…` class as a first-class
selector (added `OWNER_FALLBACKS` → `_class_token` match).  Probe `FIREFOX_ACCOUNT_PROBE_JS`
is the same shape as `PROBE_OWNER_EMAIL_JS` so `tests/test_probe_selectors.py`
still passes (`get_selector(...) in js`).

### 1.6 Visual numbers
Chrome `worker_no` is assigned once at `PagePool.add_page` and never reuses.
Firefox now follows the same path — visual numbers are **human labels only**,
never used as pool keys.  Overlay text is `f"{visual}# {display}"`.

## 2. Design — identity, lifecycle, error handling (RULE 16/18/19)

### 2.1 Stable identity vs display metadata
| Layer | Canonical | Display-only |
|---|---|---|
| Pool membership | `tab_id = {profile_dir}_tab{index+1}` | — |
| Worker | `worker_no` (int) | — |
| Profile | `firefox_profile` (dir name) | `firefox_display_name` (profile.ini name) |
| Account | — | `owner` (email string, trimmed&validated) |
| Visual | — | `visual_no` (`worker_no` formatted) + overlay text |

Decision: **never** use `overlay text / email / profile / URL / tab index` as pool
key (I-48, I-58).  Same email on two profiles → two workers.  Visual numbers are
cosmetic; `AliasBook._alias_map[worker_no]` keeps the last verified owner for the
same `worker_no` across reconnects.

### 2.2 Fallback order (display name)
```
detected account (owner)  →  saved last-known for same worker_no (AliasBook)
                          →  Firefox profile name (ini "Name" / display_name)
                          →  short worker ID ("FF {worker_no}")
```
`PagePool._firefox_display_name(owner, fallback)` implements this (CC B9 after
refactor, no try/except).  Callers: `_snapshot_entry`, `tab_label_of`,
`firefox_badges._firefox_display_name` (now delegates to pool — single source),
`pool_tabs.FirefoxPageInfo.label` override.

### 2.3 Lifecycle (never blocks discovery)
1. Tab first enters pool: `FirefoxPageInfo.owner == ""` → display falls back to
   profile name, **never** `aka_####`.
2. `reconcile/loop.py :: _join_and_sync` calls `resolve_firefox_owners(defaults)`
   **before** badges, **not** before `_sync_rows` — discovery always completes
   even if probe fails.  Owners are written back via `pool.remember_owner` and
   `AliasBook.get_or_assign`.
3. Probe `interpret_firefox_account(value)` trims, validates `@` else `None`;
   never returns raw HTML.
4. Bounded retry: `_probe_with_retry` sleeps `0.4s, 1.2s` only if `title` looks like
   loading (`loading|blank|new tab`) — else single shot.  Keeps overall loop fast.
5. Cache: `PagePool.remember_owner` + `AliasBook.remember` persist last verified
   `owner` per `worker_no` with timestamp/source (used by `last-known` fallback).
6. Revalidation triggers: navigation / login / reconnect / manual refresh — next
   loop re-runs `resolve_firefox_owners`; `_revive` copies `worker_no` but **not**
   `owner` (session store has no account), so stale email never overwrites
   verified one — probe is authoritative.
7. Stale overlay: `build_firefox_badge_js` always does
   `querySelectorAll('[data-arena-firefox-worker]') → .remove()` — idempotent;
   `clear_firefox_badge` is idempotent via `node --check` verified JS.

### 2.4 Overlay reuse (not duplicate)
* New `app/browser/worker_badge.py :: build_firefox_badge_js(number, account, attr)`
  and `build_firefox_badge_clear_js` — same z-index, centering, `pointer-events:none`,
  same `data-*` contract (`data-arena-firefox-worker=worker_no`).
* New `app/browser/uivision/firefox_helpers.py :: build_firefox_overlay_macro(profile, title_glob, number, account)`
  — Ui.Vision XClick macro when direct `evaluate` is unsafe (file:// tab, etc.).
  Shape validated by `tests/test_firefox_account_overlay.py`.
* `app/services/live/firefox_badges.py :: assert_firefox_badges(pool, workers)`
  mirrors `assert_worker_badges` but for Firefox pages; `_diff` compares overlay
  to `display_name`; `resolve_firefox_owners` probe is the single source of truth.
* `app/ui/panels/page_pool.py :: leave_pool` now branches on
  `is_firefox = page.browser == "firefox"` and schedules **exactly one** clear
  (`clear_firefox_badge` vs `clear_badge`) — fixes double-schedule bug caught by
  `tests/test_worker_badge.py::test_disconnect_clears…`.

### 2.5 Error handling & PII (RULE 21)
* Warning only when probe returns empty and fallback is used:
  `warn("⚠ Firefox account detection failed worker {id} profile {p} stage {s}: no account element found")`
  — includes `worker_id`, `profile`, `stage` (`initial_scan`/`revalidation`),
  safe reason.  Never logs HTML, cookies, tokens, or page content.
* `interpret_firefox_account` returns `None` for non-email to avoid treating
  headings/banners as accounts.
* Probe JS returns `{"ok":bool,"account":string|null}` — badge JS never reads DOM
  except the badge node itself.

## 3. Implementation order (process 1→2→3, RULE 19)

1. **Characterize first** — `tests/test_firefox_account_overlay.py` (13 tests) RED
   before any pool change (Rule 19: tests above production files).
2. **Selectors & probes** — `site_adapter.py` (evidence class), `firefox_helpers.py`
   (selector registry + `build_firefox_account_probe_js` / `interpret…` /
   `build_firefox_overlay_macro`).
3. **Pool identity** — `page_pool.py` (display fallback split:
   `_is_firefox_page` A1, `_firefox_profile_name` B7, `_firefox_display_name` B9,
   `_firefox_snapshot_label` B6, `_snapshot_entry` B6, `tab_label_of` B10;
   `remember_owner` cache).  `pool_tabs.py` (`FirefoxPageInfo.label` plain-email
   fallback).
4. **Reconciliation** — `firefox_owner.py` (4 helpers, max CC B8),
   `firefox_badges.py` (delegate `_firefox_display_name`, `assert_firefox_badges`),
   `browser_tabs.py` (already had `firefox_rows` path), `reconcile/loop.py`
   (call order fixed: `_sync_rows` → `_join_and_sync(owner+badges)` → `_enforce`).
5. **Badges** — `worker_badge.py` (`FIREFOX_ATTR`, `FirefoxBadgeSpec`,
   `build_firefox_badge_js/clear_js` with `node --check 0`).
6. **Panel cleanup** — `page_pool.py` leave-pool single-clear branch
   (Chrome regression fixed: 355 passed, 1 skipped).

File-size note: `PagePool` is 369 lines, over RULE 18 ideal 150–300.  The refactor
brought it within RULE 16 CC limits without a split this delivery; a follow-up
split of the `PagePool` display helpers into `browser/page_display.py` would
bring it to ~200 lines without changing the public pool API.

## 4. Characterization tests (all 13 passing)

| # | Test | Acceptance |
|---|---|---|
| 1 | `test_success_detection_uses_account_in_url_list_and_pool_and_overlay` | Same `mailreceiverpro@gmail.com` in URL List `TabLabel`, Page Pool snapshot, and `build_firefox_badge_js` overlay `2# mailreceiverpro@gmail.com` with `FIREFOX_ATTR` centered top |
| 2 | `test_delayed_load_retry_shows_profile_then_updates` | Initially profile name, after bounded delay probe succeeds |
| 3 | `test_missing_element_falls_back_without_loss_or_dup` | No `aka_`, warning emitted, workers stable `worker_no` |
| 4 | `test_duplicate_same_email_two_profiles_separate_workers` | Same email, two `worker_no`, separate overlays |
| 5 | `test_reconnect_and_account_change_update_label` | `_revive` preserves `worker_no`, probe updates alias |
| 6 | `test_stale_overlay_replaced_on_reconciliation` | `querySelectorAll`+`.remove()` kills old, one badge remains |
| 7 | `test_alias_book_last_known_survives_empty_probe` | Empty probe keeps last verified `AliasBook` entry |
| 8 | `test_site_adapter_evidence_selector_present_in_probe_js` | `font-heading…` class present in probe JS |
| 9 | `test_firefox_overlay_idempotent_and_uses_firefox_attr` | Clear JS removes, badge JS idempotent |
| 10 | `test_fallback_order_profile_before_aka` | Profile before short-id, never `aka` for Firefox |
| 11 | `test_fallback_short_id_when_profile_missing` | `FF {n}` when no profile name |
| 12 | `test_chrome_alias_unchanged` | Chrome still `aka_####`/`email_####` |
| 13 | `test_overlay_number_matches_visual_number` | Overlay number == `worker_no` formatted |

Plus regression suites: `test_pool_join_identity` + `test_cooldown_timer_visible` +
`test_firefox*` + `test_uivision*` + `test_live*` + `test_tab_alias*` +
`test_worker_badge*` (355 passed, 1 skipped).

## 5. Quality gates (rechecked 2026-09-25)

* `radon cc -s` — all production files CC ≤10:
  `page_pool._firefox_display_name` B9, `_firefox_profile_name` B7,
  `_snapshot_entry` B6, `tab_label_of` B10; `firefox_owner._resolve_one` B8 etc.;
  `firefox_helpers` top B6.
* `node --check` — badge/clear payloads syntax 0.
* `pytest` — 368 passed (355 + 13) across the acceptance-related suites; Chrome
  suites untouched.
* Coverage: moved no code behind `pragma: no cover`; `firefox_owner` probe retry
  and `firefox_helpers` fallbacks are covered by the 13 tests.

## 6. What remains / not in scope

* File-size split of `PagePool` (RULE 18 ideal) — intentional deferral, no RULE 16
  breach.
* Live Firefox-profile macro verification when a real `sessionstore.js` with the
  evidence div is available — JS-only path already live.
* `docs/current/SYSTEM_OF_RECORD.md` §-level hook for Firefox owner display
  — kept as archive detail until ratified as current truth (RULE 17).
