# Fix v4: Start new chat as new tab opens on wrong profile — full profile tracking

## Bug recurrence (2026-09-29)

After previous fixes (endpoint fix 46bcf31, same-context fix 4f9e036, profile count + owner rollback 34381d4), user still reports:

- Start with 1 tab per profile: mxxyjf52@jsontoexcel.net_0025 and anton.melnikov.90@gmail.com_0027, both on 127.0.0.1:9223, total 2 free 2
- After 1 run, first profile has 2 tabs same name ID (mxxy_0025 and mxxy_0027? or duplicate mxxy_0025) — total 2 free 2, second profile 0 tabs
- Logs show:
  ```
  [07:36:55] New chat as new tab: opening ... — anton_0027's old tab 8CEE... closes after — profile 127.0.0.1:9223 owner=anton tabs matching 'arena.ai/image' in profile: 2
  [07:36:55] New tab EA8C259730DF opened — connecting anton_0027
  [07:36:56] Owner mismatch: old anton vs new mxxy — keeping old, new tab may be wrong profile
  [07:36:56] New chat verified in new tab EA8C... 
  [07:36:56] anton_0027 now works in tab EA8C... — profile 127.0.0.1:9223 tabs matching 'arena.ai/image': 2 → 2
  [07:37:03] Old tab closed verified gone
  [07:38:01] New chat as new tab: opening ... — mxxy_0025's old tab D284... closes after — profile 127.0.0.1:9223 owner=mxxy tabs matching 'arena.ai/image' in profile: 2
  [07:38:04] New tab EF645DC2BDB0 opened — connecting mxxy_0025
  [07:41:44] URL removed ... tab closed
  [07:41:44] Pool add aka_0028 steady — total 3 free 1
  [07:41:44] Worker EF645DC2BDB0 left the pool — no URL row owns it
  ```

Root: both tabs on same host:port (9223) but different browserContextId (Firefox containers / Chrome incognito contexts) and different Arena owners. Counting only by host:port says 2 tabs per profile, but per-context it is 1 each. Opening new tab without preserving browserContextId lands in wrong context → wrong Arena account (mxxy vs anton). Old code only warned, kept wrong tab → profile imbalance 2+0.

## Desired behavior (user request)

- Remember full profile: (host, port, browserContextId, owner)
- Count tabs matching pattern per full profile, not just host:port
- Only close/reopen for same profile; if new tab context/owner mismatches, rollback (close new tab, keep old, in-place New Chat)
- Ensure count per profile stays balanced 2→2, not 1→2+0
- No duplicate same alias number

## Analysis of current code (34381d4)

- `_Move` already stores endpoint, old_owner, old_context, pattern, profile_count
- `_count_profile_tabs` counts by host:port only, ignores contextId and owner
- `_try_open_same_context` uses `open_tab_in_same_context` which gets contextId via `_context_of` and passes `browserContextId` to `Target.createTarget` — correct, but `_context_of` may return None for default context, causing fallback to default context (wrong)
- `_get_old_context_id` tries Target.getTargets for old_id, but may miss if client not on old_id
- Cookie copy: `_get_cookies_from_move` before open, `_set_cookies_to_move` after connect — but if same context, cookies already shared; if different context, copying after navigation is too late (page already loaded with wrong account). Need to set cookies BEFORE navigation or reload after set.
- `_check_owner_preserved` returns True when new_owner empty (probe not yet visible) → allows wrong profile to pass. Should retry with small delays, and only allow empty after retries.
- `_move_worker` logs 2→2 but per-context count may be wrong

## Design v4 — full profile handling

### 1. Profile definition

```python
@dataclass
class Profile:
    host: str
    port: int
    context_id: str  # '' = default
    owner: str       # '' = unknown
```

Profile key = (host, port, context_id). Owner is tracked separately but must match for handover success.

### 2. Counting per profile

Replace `_count_profile_tabs(pool, endpoint, pattern)` with:

```python
def _count_profile_tabs(pool, endpoint, context_id, pattern) -> int
```

Implementation: iterate pool._pages with lock, for each page get client, endpoint, and context_id via cached mapping or via trying to get context from client (sync version: we cannot async here, so we store context_id in _Move and count by endpoint + pattern + optionally owner if known). Simpler: count by endpoint + pattern, but also count by endpoint+context_id+pattern if context_id known.

For full accuracy, make counting async or make _plan async to get old_context before counting. Plan: _plan becomes async? But handover already async, _plan sync now. Change _plan to async that gets old_context via _get_old_context_id_sync? Better: make _count_profile_tabs take optional context_id and filter:

- If context_id is '' (default), count all tabs on endpoint matching pattern (old behavior)
- If context_id is known, count only tabs whose context matches old_context (need to get context for each pooled tab). To get context for each tab, we need to call _context_of for each client — async. So we need async version `_count_profile_tabs_async`.

Simplify: Keep sync count for logging, but add async count for verification: after move, verify new_count per full profile equals old count.

For minimal change and RULE 18, we will:

- Keep `_count_profile_tabs` sync counting by host:port+pattern (for backward compat logging)
- Add `_count_profile_tabs_by_context` that counts by host,port,context_id,pattern (requires async to get contextIds, but we can approximate by counting tabs whose owner matches old_owner and endpoint matches, plus pattern). Since owner is per-tab and already in PageInfo.owner, we can count by owner as proxy for context.

Better: Use owner as profile discriminator: same host:port but different owner = different profile. So count per (host,port,owner) matching pattern.

Implement:

```python
def _count_profile_tabs(pool, endpoint, pattern, owner="") -> int:
    # if owner provided, count only tabs with same owner (profile = host,port,owner)
    # else count all on endpoint
```

But user explicitly says profile = (host,port,contextId,owner). So we need both.

Final design:

- `_Move` fields: endpoint, old_context, old_owner, pattern, profile_count, profile_count_by_owner
- `_get_pattern` reads url_pattern
- `_matches_pattern`
- `_endpoint_from_client`
- `_resolve_endpoint`
- `_count_profile_tabs(pool, endpoint, pattern)` → total matching pattern on endpoint
- `_count_profile_tabs_by_owner(pool, endpoint, pattern, owner)` → count matching pattern AND owner (or context)
- `_plan` (now async? keep sync for endpoint/owner, but old_context fetched later in _try_open_same_context)
- `_get_old_context_id` async, already exists, improved to try all clients
- `_try_open_same_context` — ensure it gets old_context before open, passes browserContextId, verifies new context matches old
- Cookie handling: If context differs, we need to copy cookies AND localStorage. But if we open in same context, cookies already shared, no need. So we will:
  - Capture old cookies BEFORE opening (already done)
  - After opening same-context tab, set cookies (best effort) AND reload page via `Page.reload` or `Runtime.evaluate("location.reload()")` then wait for ready again
  - Or, better: open blank tab in same context, set cookies, THEN navigate to url via `Page.navigate`. That ensures cookies present before navigation.

Implement new flow:

```
async def _open_and_prove:
    old_cookies = await _get_cookies_from_move
    # Try same-context open with blank first
    new_tab, err = await _try_open_same_context_blank (open about:blank in same context)
    if new_tab:
        await _set_cookies_to_move
        await _navigate_to_url (Page.navigate to move.url)
    else:
        fallback open_tab_sync at url
    connect_all
    prove
```

But to keep change small and RULE 18, we will keep existing open with url, but after setting cookies, reload:

```python
if old_cookies:
    await _set_cookies_to_move
    try:
        await client.send("Page.reload")
        await asyncio.sleep(0.5)
    except: pass
```

- Owner check: Make `_check_owner_preserved` retry up to 3 times with 0.5s delay, and only allow empty after retries. If mismatch, return False → rollback.

- Rollback: Ensure alias not adopted, pool not changed, new tab closed, clients reconnected to old_ws, log "wrong profile, rollback"

- Logging: Log full profile: host:port context=... owner=... tabs matching pattern in profile: X (total) and Y per owner

- File size: current 540 LOC, need to keep helpers ≤20 LOC, file ideally 150-300 but we are already over; we must not increase too much. Extract helpers with clear names.

### 3. Quality gates (RULE 16/18)

- Function LOC ≤30 fail, prefer ≤20
- New helpers: _count_profile_tabs_by_owner, _reload_tab, _navigate_tab, _get_cookies, _set_cookies, _cookie_params, _set_one_cookie, _pick_client, _verify_context, _try_open_same_context, _get_old_context_id, _check_owner_preserved, _read_owner, etc. Each ≤20 LOC
- CC ≤10, cognitive ≤15, nesting ≤4
- Tests: existing test_new_tab_handover 23 tests, plus new test for profile counting and owner rollback
- Coverage: overall line ≥80% (baseline 89.34), branch ≥75% (86.37) — must not drop

### 4. Implementation steps

1. Update _Move dataclass with profile_count_by_owner
2. Add _count_profile_tabs_by_owner(pool, endpoint, pattern, owner) sync, ≤15 LOC
3. Update _plan to compute both counts
4. Update _get_old_context_id to be more robust (try all clients, try Target.getTargets, return '' if default)
5. Update _try_open_same_context to store old_context, verify new context
6. Add _reload_after_cookie(client) helper
7. Update _open_and_prove to reload after cookie set
8. Update _check_owner_preserved to retry 3 times, 0.5s delay, return False on mismatch
9. Update _move_worker logging to include per-owner count and context
10. Update tests: add test_owner_mismatch_rollback, test_context_preserved
11. Run quality gate: `python tools/verify_quality.py --changed --base origin/main --allow-legacy`
12. Run pytest: `pytest tests/test_new_tab_handover.py -q`
13. Record baseline if needed

### 5. Risks

- Cookie copy may fail for httpOnly, secure — best effort, rollback will catch owner mismatch
- ContextId may be None for default context — treat '' as default, still profile-correct if both old and new are default
- Reload after cookie set may cause new chat verification to need re-wait — handle by calling wait_new_chat_ready after reload

### 6. Ideal sizes justification

- new_tab.py currently 540 LOC, over ideal 300 but under fail? File LOC fail not defined, but ideal is 150-300. We are over because feature grew. We will not increase file size drastically; new helpers replace inline code, keeping file ~550 LOC. Reason: single responsibility handover with profile handling requires tracking host,port,context,owner,pattern,count — splitting into separate module would exceed RULE 18 module cohesion. Keep as is with ideal-size comment if needed.

## Acceptance

- No duplicate alias after handover
- Profile counts 2→2 per endpoint and per owner/context
- Owner mismatch triggers rollback, not wrong label
- Quality gate PASSED, 36 tests green
