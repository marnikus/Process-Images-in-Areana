# Fix 2026-09-16 — Cooldown Timers Persist Across App Restart

User requirement: closing and reopening the app must not pause timers —
real time counts, the countdown continues from wall-clock on reopen.

## Implementation

- `app/persistence/cooldown_store.py` (new, tested): `config/cooldowns.json`
  with atomic writes (same-layer `_atomic_write` reuse). Entries keyed by
  tab_id (stable while Chrome runs); URL exact/prefix fallback covers
  Chrome restarts too. `cooldown_until` is epoch-based; expiry checked
  against `time.time()` on load/restore. Expired-idle entries pruned;
  pending-penalty entries kept; pool-absent live entries merged (never
  erased by an empty pool); capped at 25.
- `cooldown_service.restore_cooldown_entry` (tested): re-applies an entry
  onto a steady page; ignores expired, refuses busy, never shortens a live
  timer, restores pending/captcha as max (idempotent).
- Bridge: `_persist_cooldowns` autosaves on every pool-status publish
  (finish/slots/registration) + 5s UI-poll safety net + captcha-penalty
  sites. `_restore_cooldown` runs at all three registration points
  (ensure/connect/pool-connect), consumes the applied entry, and logs the
  remaining time. "Clear pool" also wipes the file (explicit fresh start).
- Layering kept: services never import persistence (restore takes a plain
  entry dict); store works on pool snapshots (no browser imports).

Known residual: a captcha penalty stacked <5s before a hard close could be
lost (parallel-runner path has no bridge hook; the 5s poll net covers the
rest). Accepted: worst case is one lenient cycle, never a stuck tab.

`pytest 145 passed`, `verify_quality --changed --allow-legacy` 0 fails.
