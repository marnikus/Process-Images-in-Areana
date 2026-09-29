# Fix: App close should clean pool tabs — F5 refresh and disconnect

## Requirement
User: "after the app closed it should clean it correct. restart all url pages with refreshing F% and disconnect it from APP."

Current closeEvent in MainWindow:
- saves geometry, session, presets, cooldowns
- flushes SashGrid persistence
- drops only main cdp_client socket (bridge.cdp), not per-tab pool clients
- does NOT reload pool tabs, does NOT clear badges/overlays

Result: tabs remain attached with worker badges, watcher overlays, busy state, and stay connected to app's CDP clients. On next session restore, they may be stale.

Expected:
- On app close, for each pooled URL page:
  - Clear worker badge (#n + label)
  - Hide watcher overlay (generation/captcha)
  - Reload page (F5 / Page.reload) to reset to clean new-chat state
  - Disconnect CDP client from APP (so tab no longer controlled)
- Then clear pool dicts

## Design

### 1. MainWindow._drop_browser_sockets() enhancement
Current: only disconnects self.cdp_client.

New:
- Get pool = self.bridge._page_pool if bridge exists
- For each tab_id in list(pool._pages.keys()):
  - Get client, controller = pool.get_clients(tab_id)
  - Try to schedule async tasks if loop running:
    - clear_badge(client, tab_id) — removes #n label from tab
    - hide_watcher_overlay via controller or client
    - reload_page via Page.reload or location.reload
    - disconnect client
  - If no running loop, best-effort sync cleanup: set _ws=None, _connected=False, cancel receive task
- After scheduling, clear pool dicts via reset_pool_dicts(pool) or pool._pages.clear() etc.
- Then disconnect main client as before

### 2. Bridge helper (optional)
Add method `Bridge._shutdown_pool_cleanup()` that does above, callable from MainWindow. But to keep MainWindow slim and avoid circular imports, implement directly in MainWindow._drop_browser_sockets with lazy imports and try/except.

### 3. Reload implementation
- Use `client.send("Page.reload")` async, fallback to `client.evaluate("window.location.reload(); true")`
- Timeout 2s per tab, best effort, never raises
- For sync path (no loop), skip reload (can't), just disconnect

### 4. Badge and overlay clear
- Badge: `clear_badge` from `app.services.live.worker_badges` (already used in leave_pool)
- Overlay: try `controller.hide_watcher_overlay()` or `client.send("Runtime.evaluate", {"expression": "document.getElementById('arena-watcher-overlay')?.remove(); true"})`

### 5. Quality (RULE 16/18)
- MainWindow file currently 203 LOC, ideal 150-300, so adding ~30 LOC is okay
- Keep _drop_browser_sockets ≤30 LOC, extract helpers:
  - _reload_and_disconnect_pool(pool, loop) → ≤20 LOC
  - _clear_tab_ui(client, controller, tab_id) → ≤15 LOC
- CC ≤10, nesting ≤4
- Tests: existing pool tests should still pass, no new functionality that breaks

### 6. Acceptance
- Close app with 2 pooled tabs (mxxy_0029, anton_0028) → both tabs reload (F5), badges removed, overlays hidden, disconnected
- Reopen app → Session restored, pool re-adds tabs as steady with no leftover badges/overlays
- No pending task warnings on close
