# Fix 2026-09-16 — Cooldown Isolation Per Tab (no cross-tab timers)

User spec: cooldown + captcha penalty are strictly per page/tab. After one
job, only the tab that ran it may cool; an idle tab must stay ready.

## Root causes (matching layers, not writers)

All cooldown writers were already single-target (verified by enumeration:
`start_cooldown`, `_apply_restored_cooldown`, `add_captcha_penalty` each
take one tab id; dispatcher finishes per-task tabs; single loop uses the
primary tab only). The leak was in MATCHING, found in two places:

1. **URL rows re-rendered one tab on all rows** (`url-list.js`): unclaimed
   rows fell back to first-match over ALL pages, so with tab A cooling and
   tab B's URL missing/weak, both rows showed A's timer + badge.
   Fix: strict fallback — with 2+ pooled tabs an unclaimed row may only take
   an UNCLAIMED page with exact/prefix URL match, else "—" (no tab). Single
   pooled tab keeps shared display (it genuinely serves all rows in
   single-tab rotation mode).
2. **Restart restore could hand A's entry to B** (`cooldown_store`): the URL
   prefix fallback fired when B registered after A's job with bare/shifted
   URLs. Fix: consume by exact tab id, else exact normalized URL only
   (case/trailing-slash tolerant, query kept). Cost: a bare-URL entry loses
   cross-Chrome-restart restore (lenient miss, never a wrong-tab timer).

Verified: node harness (bug case row1 → null, normal 1:1 unchanged),
`pytest 146 passed`, quality gate 0 fails.
