# Research: Start new chat as new tab opens on wrong profile

## Logs provided (2026-09-28 23:04)
- Fetching Chrome tabs from http://127.0.0.1:9222 only
- Pool add anton.melnikov.90@gmail.com_0025 and mxxyjf52@jsontoexcel.net_0023 (2 tabs, same Chrome endpoint 9222, different Arena accounts)
- Run 17 images, 2 urls, parallel 2 pages
- Job icon-open-book.png -> mxxyjf52_0023 (tab 2FED923846AB)
- After job: New chat as new tab opening https://arena.ai/image/direct?model_a=max — mxxyjf52's old tab 2FED... closes after
- New tab AFDDEBF1F2C3 opened, connecting mxxyjf52
- Tab disconnected (x2), Tab connected, New chat verified, worker moves to new tab, old tab closed verified gone (same URL)
- Cooling 19:59

User says: still wrong profile, after closing tab it reopen new chat on another profile, should reopen with same profile it was closed.

## What "profile" could mean
1. **Chrome user-data-dir profile** (BrowserProfile in browsers.py, --user-data-dir, port 9222 vs 9223)
2. **Firefox profile** (profile_dir)
3. **Arena account profile** (email detected via owner_probe, alias {email}_{4digits})

Feature is Chrome-only (design D7), so Firefox excluded.

### Chrome profile hypothesis
- App currently has single Chrome registry entry (PROFILES = [chrome]), but supports multiple Chrome instances via different ports (cdp_port base + port_offset, or manual launch with different --user-data-dir and --remote-debugging-port)
- PagePool is single, but each PageInfo's ws_url contains host:port, and CDPClient per tab stores _host/_port from ws_endpoint parsing.
- Previous bug: _plan used ctx.client (bridge.cdp) or pool._host/_port (default 9222) for new tab endpoint, ignoring pooled client's actual endpoint. If old tab was on 9223, new tab opened on 9222 → wrong Chrome profile.
- Fix applied: _resolve_endpoint prefers pooled client. Should fix Chrome profile case.
- Latest log shows only 9222, so Chrome profile case not reproducing here, but could still be issue if pooled client endpoint not correctly used in some paths (e.g., batch_orchestrator uses bridge.cdp not pooled).

### Arena account profile hypothesis (more likely for this log)
- Pool has 2 tabs on same Chrome endpoint (9222) but different Arena accounts (anton vs mxxyjf52). How can same Chrome profile have 2 different Arena accounts?
  - Arena may store account in localStorage per tab, or use different browser contexts, or user logged into different accounts in different tabs via Arena's own account switcher.
  - When opening new tab via PUT /json/new, new tab shares same Chrome cookie jar and localStorage? Actually new tab from /json/new starts blank, navigates to URL, should inherit cookies from profile but not necessarily same Arena account if account is per-tab.
  - If new tab inherits default account (e.g., anton, the first tab's account, or no account), but old tab was mxxyjf52, then new tab would be wrong Arena profile.
  - AliasBook.adopt keeps old email label (mxxyjf52) but actual page account may be different (anton or none). Owner probe later will detect real account and update label via remember(), causing worker to appear as other profile.

### Evidence from code
- `page_pool.py:retarget_page` keeps old PageInfo (with old owner) and rekeys it, then `AliasBook.adopt` moves number+email to new tab id. So display label stays old account, but actual page may have different account.
- Owner probe runs periodically via `resolve_owners` and `assert_badges`, which will detect new tab's real account and call `book.remember(new_id, new_owner)`. If new tab's real account is anton, label will change from mxxyjf52 to anton, appearing as wrong profile.
- New tab URL is `https://arena.ai/image/direct?model_a=max` – does this URL preserve Arena account? It should, if cookies shared, but if account is per-tab, it may not.
- No code currently copies cookies/localStorage from old tab to new tab.

### What should happen (expected)
- New tab should be same Chrome profile (same host/port/user-data-dir) AND same Arena account as closed tab.
- To guarantee same Chrome profile: use pooled client's endpoint (fixed).
- To guarantee same Arena account: need to ensure new tab inherits same session, or explicitly log in same account, or copy storage.

### Possible fixes
1. **Chrome profile fix (already done but verify)**: Ensure _resolve_endpoint uses pooled client in all paths (batch_orchestrator, cooldown_service). Check FinishCtx creation: in batch_orchestrator._finish_and_follow, client=bridge.cdp, not pooled. Our fix uses pooled client from pool.get_clients, so should be correct. Need to verify in multi_page_dispatcher too.

2. **Arena account fix**: After opening new tab, need to verify owner probe matches old owner, and if not, try to restore session or log warning. Could store old owner email and compare with new tab's detected owner after prove. If mismatch, log error and maybe retry or keep old label but note mismatch.

3. **Alternative: navigate old tab instead of opening new tab when same URL?** Design D5 says same URL still closes old one, but maybe for same account case, navigating old tab to new chat URL would preserve account better than opening new tab.

4. **Copy session**: Use CDP to get cookies/localStorage from old tab before close and set in new tab.

5. **Control: setting to choose profile?** User says "it should has control of what profile is it should reopened with new tab". Could mean UI should allow choosing which Chrome profile to open new tab on. Currently no control, it just uses same endpoint as old tab. Maybe need to add profile selector in settings.

### Deeper investigation needed
- Check how Arena account is stored: cookies, localStorage, IndexedDB? Inspect owner_probe selectors.
- Check if new tab via /json/new shares same storage as old tab (should, same profile).
- Check logs for owner detection after handover: does new tab AFDDE... get owner probed? Not in provided log.
- Check if pool has tabs from multiple Chrome endpoints (9222 and 9223) and scan_targets only scans 9222, causing new tab to open on 9222 even when old tab was on 9223. Our fix should handle, but need to verify pooled client endpoint is indeed from old tab's ws_url, not from bridge.cdp.

### Immediate research steps
- Add detailed logging in new_tab.py: log old tab's endpoint (host,port, ws_url, owner) and new tab's endpoint and owner after prove.
- Add logging of pooled client host/port vs bridge.cdp host/port at _plan time.
- Check PagePool._pages entries for their ws_url ports to see if multi-port scenario exists.
- Inspect `ws_endpoint` parsing to ensure port correctly extracted.
- Look at `open_tab_sync` – does it open tab on correct browser when multiple Chrome instances? It uses host,port from endpoint, so if endpoint is 9223, it opens on 9223.

### Conclusion for next fix
- Keep pooled client endpoint fix (already done).
- Additionally, preserve Arena account: after opening new tab, compare old owner vs new owner probe, log mismatch, and keep old owner in AliasBook (don't overwrite via remember until verified).
- Add UI control? Maybe setting to choose Chrome profile (browser id) for new tab, but for now ensure same as closed tab.

This research doc should be followed by implementation that adds owner preservation and more logging.
