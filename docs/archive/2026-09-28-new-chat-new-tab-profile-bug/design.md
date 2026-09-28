# Fix: Start new chat as new tab opens on wrong profile

## Bug
Feature "Start new chat as new tab (close the job's tab, continue in a fresh one)" works incorrect. After closing the tab it reopens new chat on another profile. It should have control of what profile it should be reopened with new tab - the same it was closed.

Screenshot: checkbox "Start new chat as new tab (close the job's tab, continue in a fresh one)"

## Root cause analysis
- `app/services/new_tab.py` handover:
  - `_plan()` builds `_Move` with endpoint from `ctx.client._host/_port or pool._host/_port`
  - `ctx.client` in `batch_orchestrator._finish_and_follow` is `bridge.cdp` (global client), not the job's dedicated client. `bridge.cdp` may be connected to any tab (primary, last used), often on default profile/port.
  - `pool._host/_port` is single tagging from `bridge_context._pool_endpoint` (cdp_host/cdp_port base), not per-tab. Pool can contain tabs from multiple Chrome endpoints (each tab's `ws_url` carries its own host:port, client created with that endpoint in `page_pool.ws_endpoint`).
  - Result: when job finishes on tab A (profile A, port 9223), endpoint used to open new tab is from `bridge.cdp` (maybe port 9222, profile B) → new tab opens on wrong browser profile. Old tab closes, new tab lives on other profile, breaking worker identity and confusing user.

- Existing test `test_new_tab_handover.py` uses FakeClient with fixed host/port 9333 and mocked `open_tab_sync` that ignores host/port, so bug not caught.

## Desired behavior
- New tab must open on **same browser endpoint (host, port, profile)** as the closed tab.
- If job's tab has dedicated pooled client, use its endpoint.
- Fallback chain: pooled client → job client → pool default → 127.0.0.1:9222
- Preserve existing rollback, verification, reconciler hold logic.

## Decisions
- D1: Endpoint resolution prefers pooled client (`pool.get_clients(tab_id)[0]`) because it was created from `ws_endpoint` parsing the tab's own `ws_url`, thus carries correct host/port/profile.
- D2: Keep `_Move.endpoint` as tuple, but compute via helper `_resolve_endpoint(ctx, pooled_client)` to isolate decision and keep CC low.
- D3: No new PagePool per-profile needed; existing per-tab client already encodes profile via host/port. Changing pool structure would exceed RULE 18 file size and require larger refactor.
- D4: Add regression test `test_handover_uses_pooled_client_endpoint_not_bridge_client` that sets bridge.cdp on different port than pooled client and asserts `open_tab_sync` called with pooled client's endpoint.
- D5: Keep function LOC ≤20, CC ≤7, file ≤300 per RULE 18/16.

## Code shape (RULE 16/18 budget)
- `app/services/new_tab.py`:
  - new helper `_endpoint_from_client(client)` → Optional[tuple]
  - new helper `_resolve_endpoint(ctx, pooled_client)` → tuple, tries pooled, then ctx.client, then pool._host/_port, then default
  - `_plan()` uses `_resolve_endpoint`
  - LOC: existing file 249 lines → ~270 lines, still <300; new helpers ≤12 lines each, CC ≤3
- `tests/test_new_tab_handover.py`:
  - add test for endpoint correctness, keep existing tests green

## Tests first (RULE 8)
- New test will fail before fix: mock open to capture host/port, set pooled client port 9334, bridge.cdp port 9222, assert open called with 9334 not 9222.
- Existing 12 handover tests must stay green.

## Risks
- If pooled client missing, fallback to old behavior (job client or pool) – still works for single-profile case.
- No change to close verification, worker move, alias adopt.

## Ideal sizes justification
- new_tab.py currently 249 lines, adding 2 helpers + endpoint logic → ~270, still within 150-300 ideal, primary responsibility unchanged (handover).
- Helpers named by domain concept (endpoint resolution), not foo_part1, per RULE 16 anti-gaming.
