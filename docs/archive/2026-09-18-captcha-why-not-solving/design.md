# Captcha: "detected but solving was not done" — diagnosis + why-not-solving flag

Date: 2026-09-18 (round 3, continues `2026-09-18-captcha-visual-await/`).

## 1. Report (user screenshots)

- Job pause badge: `ON PAUSE [674502] Check Security Dialog`.
- Red overlay: `WAIT FOR USER. CAPTCHA — Solve captcha manually — watcher is
  waiting (drag me) — Waiting... 334s elapsed — Timeout: 300s (win setting) — 0s left`.
- User: "it shows some how detection but solving was not done."

## 2. Diagnosis

The detection path worked exactly as designed:

1. Gate predicate (v2, `captcha_js/visible.js`) fired on a **real on-screen
   challenge** → job paused at the `Check Security Dialog` checkpoint.
2. `handle_captcha` → detect probe confirmed visible → `🛡️ Captcha detected`
   log → `_manual_wait` → red overlay → polled until the 300 s timeout.

Why nothing was solved — auto-solve is strictly **opt-in** (RULE 20 amendment):

| State on the machine | What happens | Was it visible? |
|---|---|---|
| `2captcha.json` missing / enable OFF / no key (DEFAULT) | manual wait — the app NEVER solves; a human must solve in Chrome | ❌ overlay said only "Solve captcha manually" |
| enable ON + key, but probe found **no sitekey** (`solvable=False`) | **silent** fall-through to manual wait | ❌ no log at all |
| enable ON + key, 2Captcha attempt failed | warn log `2Captcha auto-solve failed (…)`, manual fallback | ❌ user sees overlay only, not the log |

`config/2captcha.json` is per-machine and gitignored (`.gitignore:14`), so its
state is not inspectable from this repo — but the default (OFF) plus the user's
history makes "auto-solve OFF → waited for a human who wasn't at Chrome →
300 s timeout" the most likely branch. Either way the **real defect is the
same UX gap**: the overlay — the only surface the user looks at — states WHAT
(waiting) but never WHY the app is not solving. That defeats the "visual
conformation" goal.

## 3. Design

**Overlay carries the reason.** `show_watcher_overlay` /
`build_watcher_overlay_js` gain a `sub: str = ""` parameter rendered as an
amber reason line under the caption (captcha kind). The parameter slot is
reclaimed from `elapsed_sec` — **provably dead**: all 6 call sites pass `0`
and the live tick recomputes elapsed from `Date.now()` every second. Param
count stays at 4 (RULE 16 hard gate); `service.py` (not in the size baseline)
stays inside RULE 18 ideals.

**`handle_captcha` computes the exact wait reason** (one per branch, no silent
paths):

| Branch | Overlay `sub` | Log |
|---|---|---|
| auto OFF (no svc / not enabled) | `auto-solve OFF — solve in Chrome (enable 2Captcha in the Captcha window)` | existing `🛡️ Captcha detected` + `🛡️ FLAG CAPTCHA_WAITING` |
| auto ON, `solvable=False` | `auto-solve: no sitekey in dialog` | NEW `⚠️ FLAG CAPTCHA_AUTO skipped — no sitekey in dialog — manual wait` (warn) |
| auto attempt failed | `auto-solve failed: {reason}` | existing warn `2Captcha auto-solve failed (…)` |
| auto solved | (no overlay) | `🤖 FLAG CAPTCHA_AUTO` + success path |

Structure: `handle_captcha` keeps decision flow (~19 LOC, RULE 18 ideal 4–20);
the attempt moves to `_try_auto(ctx, signal, svc)` (11 LOC, returns outcome
only when solved). `_manual_wait(ctx, signal, reason)` passes `sub=reason`.

Call-site updates (drop the dead `elapsed_sec=0`): `service.py`,
`single_job_runner.py:177`, `watcher.py:200,247`, `bridge.py:2926,2956`.

## 4. RULE 18 recheck (changed code)

- `service.py`: `handle_captcha` ~19 LOC, `_try_auto` 11, `_manual_wait` 21,
  3 params max — all within ideals; file ~235 LOC.
- `dom_highlight.py` `build_watcher_overlay_js`: +6 LOC net (legacy file, in
  size baseline → gate downgrades to [LEGACY] warn, anti-gaming unaffected).
- `cdp_arena.py` `show_watcher_overlay`: 10 LOC, 4 params — unchanged size.
- No new modules; no signature changes beyond the documented `elapsed_sec`→`sub` swap.

## 5. Verification (2026-09-18)

- pytest: **287 passed** (5.2 s) — overlay `sub` asserted per branch:
  OFF → `auto-solve OFF …`, no sitekey → `auto-solve: no sitekey in dialog`
  (+ new `⚠️ FLAG CAPTCHA_AUTO skipped` warn), solver failure →
  `auto-solve failed: …` (FakeCtrl now records overlay kwargs).
- node `npm run test:js`: **85/85 passed**.
- RULE 16 (`tools/verify_quality.py --changed --allow-legacy`): **0 code fails**
  for the changed set (dom_highlight/cdp_arena/bridge/etc. are in the size
  baseline → downgraded [LEGACY] warns; `service.py` — not in baseline — clean).
  Note: `origin/main` is currently a rebuilt unrelated history (single
  `fd24dc5 "upd"` commit, no merge base), so the gate ran in all-files mode;
  code fails are still correctly filtered (only the pre-existing
  coverage.json 29.3% threshold fails remain, documented in
  `2026-09-18-captcha-visual-await/design.md` §3).
- Generated overlay JS with `sub` syntax-checked via `node --check` ✓.

## 6. Answer to "solving was not done"

Auto-solve is **opt-in** (RULE 20 amendment): it only runs when the Captcha
window has enable = ON + a stored API key (`config/2captcha.json`,
per-machine, gitignored). Default is OFF → the app pauses and waits for a
human to solve in Chrome — which is exactly what the screenshots show
(300 s timeout, no solve). From now on the red overlay states this reason
visually (amber line), and every skip/failure of the auto path is logged.
