# Fix 2026-09-16 — Silent Cooldown-Restore Miss (persistence "not fixed")

Symptom: close app with a cooling tab, reopen within 5 min → tab shows
ready, and the log has NO `Restored cooldown` / `Cooldown restore
skipped` / `cooling` lines. Reporter could not provide file content.

## Evidence timeline (committed `config/cooldowns.json`)

- `33c8884` 14:20: file WITH a real entry (`cooldown_until`,
  `cooldown_total: 300`, `reason: "job done"`, ~3m45s left). Saving a
  genuine wall-clock timer works; epoch math matches commit time.
- `e0d9dd2` 14:34 (14 min later): `{"entries": {}}`. Timer had expired
  by then → expiry cleanup, CORRECT, not a wipe bug.

## Mechanism audit (all verified in code, all working)

| Step | Evidence | Verdict |
|---|---|---|
| Save triggers | 5s UI poll + every pool emit + captcha + app close | ✅ entry is in the file at close |
| Save format | absolute epoch `cooldown_until` via `to_dict` | ✅ real time counts |
| Restore calls | all 3 pool-add paths call `_restore_page_state` | ✅ restore runs per join |
| Wipe paths | only manual Clear + correct expiry-drop; merge keeps pool-absent ids | ✅ nothing auto-wipes a live timer |
| Status clobber | `add_page`/`ensure_pool_page` preserve status | ✅ restored state survives re-add |
| Clocks/paths | epoch math consistent; state dir stable (URL list works) | ✅ cleared |

## Key discovery: two columns, two meanings

The URL list has STATUS (`UrlStatus.ready` = link validated, cooldown
independent) and COOLDOWN (`✅ ready` = pool page steady / `—` = NO pool
page matched). A `—` means restore never ran for that row — no join, no
tab, no restore — which is also silent. "Shows ready" is ambiguous
without saying which column.

## Cause ranking (all silent by design — that is the bug)

1. Elapsed > remaining: timer genuinely expired → correctly ready, no log.
2. Tab/URL drift: Chrome restarted without the same tabs, or the model
   param changed → tab_id miss + URL miss → silent, no log.
3. No pool join yet at check time (Chrome closed, scan pending) → row
   shows `—`, restore never runs, no log.

Matching stays strict on purpose (host-only fallback was rejected for
isolation — one tab's timer must never render on another row). The fix
makes the silence LOUD instead of weakening the match.

## Solution (implemented)

- Store `describe_cooldown_file(path)`: one extra read returning
  `{exists, raw, live, dropped}` — no behavior change.
- Bridge `_log_restore_miss`: file-level notes once per process (no
  file / empty / expired-while-closed with count); tab-level WARN per
  join when live entries exist but none match this tab (wanted
  id+URL vs saved summary).
- Bridge `_persist_cooldowns`: edge-triggered failure WARN (silent
  while healthy — it runs every 5s) + recovery note.
- Refactor (RULE 19, no behavior change): `_restore_page_state`
  27→~18 lines via `_apply_restored_entry` + `_pooled_ids` reuse.

## Corrected retest protocol

1. Same Chrome, same two tabs (no model switching), note MM:SS left.
2. Close app, wait (SHORTER than remaining!), reopen.
3. Wait until the pool shows both pages (join first — restore rides it).
4. Read the COOLDOWN column (not STATUS) + the log:
   - `⏳ Restored cooldown for …` → fix confirmed.
   - `⚠ Cooldown restore missed …` → quote it back (shows wanted vs saved).
   - `already expired while app was closed` → test waited too long.
