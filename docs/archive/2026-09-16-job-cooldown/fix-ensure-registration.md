# Fix 2026-09-16 — Batch Self-Registers Primary Tab (cooldown never started)

User report: after the first job, no 5-min countdown appeared and the next
job ran immediately.

## Root causes (two compounding defects)

1. **Finish no-op on unregistered tab.** `finish_page_after_job` needs the tab
   in the pool, but single-tab batches could run with the primary tab missing
   (connect path that skips registration, pool cleared, tab-id drift). The
   unknown-tab path only warned — jobs ran back-to-back with no pause.
2. **Pool pages registered with empty URL.** Registration read
   `cdp._current_title/_current_url`, which are never assigned anywhere
   (verified: zero writes). URL-row matching skips empty URLs, so even a
   cooling tab could never show its countdown on the URL List win.

## Fix

- `cooldown_service.ensure_pool_page(pool, info)` (tested, 3 new tests):
  register-if-missing, else fill empty title/url only (never clobbers).
- `Bridge._ensure_pool_page(tab_id)` called in the single-page gate before
  every image (covers first job + mid-batch pool clears); short-circuits when
  the page already has title + url (no extra CDP traffic).
- `Bridge._resolve_tab_info(tab_id, ws_url)`: live title/url from
  `fetch_tabs()` matched by tab id / ws_url; used by `_ensure_pool_page`,
  `_do_connect_tab` and `_do_connect_page_pool` registrations.
- Result: first job finishes → New Chat reset → 5:00 countdown with
  `cooldown` status on pool + URL row → next job waits for expiry.

`pytest 129 passed`, `verify_quality --changed --allow-legacy` 0 fails.
