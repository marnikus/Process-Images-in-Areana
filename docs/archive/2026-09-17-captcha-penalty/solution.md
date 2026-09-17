# Captcha penalty never lands on the finished cooldown — research + solution

Date: 2026-09-17 · Branch: `arena/01a0a9cf-process-images-in-areana` · Status: **research done, fix proposed, awaiting user answers**

User report: *"if the captcha was detected, it should immediately add extra cooldown
time from user preset x m/captcha. Now if job finish i still see classic 5 min only
but no extra time added."*

Process ordered by user: 1) deep research → 2) solution doc (this file) → 3) fix.
RULE 16.6 §2 satisfied by this doc; RULE 8/16/18 gates apply to step 3.

## 1. Proven-correct chain (ruled OUT as the cause)

Every link below was verified with file:line evidence on the current branch.
The record → persist → finish → display pipeline is correct and unit-tested.

| # | Link | Evidence |
|---|------|----------|
| 1 | Win inputs (minutes) → seconds payload | `app/ui/web/js/panels/url-list.js:423` sends `min_seconds: minM*60`, `captcha_penalty_seconds: penM*60` — no unit bug |
| 2 | Config stored, default 900 | `app/ui/bridge.py` `set_cooldown_config` (~L2201) via `clamp_seconds(v, 900)`; `app/core/cooldown.py:27-37` clamps 0..86400, bad type → default |
| 3 | Recording sites (all 3) call `add_captcha_penalty` + persist | `bridge.py:2684-2691` (CHECK_SECURITY solved), `bridge.py:2916-2923` (gen-wait solved), `app/services/single_job_runner.py:127-138` (dispatcher job-start) |
| 4 | `add_captcha_penalty` stacks or extends live timer | `app/services/cooldown_service.py:295-310`: cooling → `until/total += extra`, else `pending_penalty += extra`, `captcha_count += 1`; `-1` unknown tab |
| 5 | Finish applies `base + pending`, consumes pending | `_finish_normal` (`cooldown_service.py:588-610`) → `start_cooldown(pool, tab, cfg.min_seconds, …)` → `cooldown_total` (`cooldown.py:76-80`); pending zeroed only after use (L283); `_reason_for` (L565-576) yields `job done +captcha xN` when pending>0 |
| 6 | No automatic mid-run wipe of pending | All `pending_penalty` writes: L211/214 restore **max-merge**, L283 consume-after-apply, L302/307 add, L317/344 **manual** reset slots (`bridge.py:2219-2227`, `2250-2255`) — no auto caller |
| 7 | No post-finish overwrite of the total | All `cooldown_total` writes: settle-0 (cancelled paths), start (L288), live-extend (L362), restart-restore never-shortens (L232), manual reset (L341) |
| 8 | UI would show extras if present | `_fillCoolCell` renders `+{pending} pending` and `🛡xN` badge |
| 9 | Behaviour locked by tests | `tests/test_cooldown_service.py:88-142` (stacking, per-tab isolation, application at finish) |
| 10 | User already has this code | `git log -S add_captcha_penalty -- app/ui/bridge.py` → only the base merge: single-path recording predates this session (not a stale-build issue) |

Net: **if the app records a captcha, the finished cooldown MUST show base+extra —
proven by code + tests. The user sees base only ⇒ in their run, nothing was recorded.**

## 2. Root cause — ranked candidates

Recording happens at exactly 3 points (single: job-start check + generation-wait
cycle tops; dispatcher: job-start check). Everything else is a gap.

### RC-A (most likely): captcha solved OUTSIDE the recording windows

- Single path: no captcha check during attach / prompt / submit / observe /
  download phases, none *within* a generation-wait cycle (checks sit only on the
  2 cycle tops, `bridge.py:2880`), none after the last check.
- Dispatcher path: `wait_for_output` (`single_job_runner.py:183`) has **no**
  captcha watch at all — mid-generation captcha is invisible to the penalty logic.
- The user solves captchas manually (RULE 20 — correct behaviour): captcha pops
  up, they solve it on screen, the job succeeds — but the app never saw a
  visible→gone edge inside a recording window, so `pending_penalty` stays 0 and
  the finish shows the classic 5 min. "Detected" = seen by the user, not the app.

### RC-B: recording attempted but failed (needs user's log to confirm)

- `Captcha penalty skipped: …` (exception), `…(x-1)` (page missing from pool),
  or **silent** skip when pool/tab is falsy (bridge guard + `single_job_runner`
  early-return log nothing). Fix must remove the silent paths regardless.

### RC-C: preset penalty is 0 (needs user to confirm preset)

- Then base-only is correct behaviour, no bug. The win screenshot earlier showed
  15 — re-confirm the live preset values.

### RC-D: watcher-handled captcha (only if user enabled the watcher)

- `app/services/watcher.py:190-194` detects captcha and waits, but never calls
  `add_captcha_penalty`. Watcher default is OFF (`bridge.py:144`
  `watcher_enabled` default `False`). Needs user to confirm watcher state.

## 3. Recommended fix (covers all gaps, one choke point)

- **F1 — one choke point:** new `note_captcha_event(pool, tab_id, penalty_seconds,
  bridge, source)` in `app/services/cooldown_service.py`: calls
  `add_captcha_penalty`, asks bridge to persist, logs one uniform line **with the
  upcoming total**. All 3 existing sites + all new sites call it. Small function
  (RULE 18: 4–20 lines; helper splits if needed).
- **F2 — edge-triggered accounting:** count one penalty per solved event
  (visible→gone edge), never per poll. Dedupes overlapping detectors
  (job loop + watcher both seeing the same captcha = 1 penalty, keyed on the
  tab + a solve-epoch marker).
- **F3 — continuous detection in waits:** add the captcha predicate to the
  existing poll iterations of the single-path generation wait and dispatcher
  `wait_for_output` (same 2 s cadence, ideally batched into the same CDP/JS
  round-trip; no new timers). Rising edge → existing captcha overlay UX;
  falling edge → `note_captcha_event` once.
- **F4 — phase-boundary checks (cheap gap cover):** after submit and before
  download, single + dispatcher: if dialog visible → run the standard
  wait-for-solve + record flow (reuses F1, no per-poll cost).
- **F5 — watcher (if enabled):** on `waiting_captcha → clear` transition record
  once via F1 (needs a pool getter on the watcher; small wiring).
- **F6 — observability (makes any recurrence self-diagnosing):**
  - record log: `🛡️ Captcha penalty +15m (x1, source=gen-wait) — next cooldown ≥ 20:00`.
  - finish log: `⏳ Page … cooling 20:00 = base 05:00 + captcha 15:00 x1`.
  - Today's `_log_finish` (`cooldown_service.py:578-585`) prints remaining only —
    extend with total + reason (reason string already exists via `_reason_for`).
- **F7 — no silent skips:** pool/tab-missing and `-1` paths log `warn` with tab id.

Explicitly NOT changing: stacking math, consume-after-apply, manual resets,
restore max-merge, watcher default OFF, RULE 20 (user still solves; we only count).

## 4. Test plan (RULE 8 — failing-first, then green)

1. `note_captcha_event`: visible→gone counts 1; gone→gone counts 0; same solve
   seen twice counts 1; unknown tab → False + warn (no raise).
2. Single path: captcha appear+solve *inside* a gen-wait cycle → pending set;
   finish total = base + penalty; finish log contains the breakdown.
3. Dispatcher: captcha mid-`wait_for_output` → penalty recorded; finish applies.
4. Watcher (enabled in test): solved transition records exactly once.
5. Phase-boundary: captcha visible right after submit → wait + record path taken.
6. Existing suite stays green (`tests/test_cooldown_service.py:88-142` guards
   stacking/application); coverage ≥80% on touched files (RULE 16).

## 5. Quality gates for the fix (RULE 16/18/19 recheck at end)

- radon CC ≤ 10, cognitive ≤ 15, nesting ≤ 4, params ≤ 4, LOC ≤ 30/150 per
  function/file-delta; new helper 4–20 lines; no new module over 15 files.
- `pytest` green; manual 1-image run with a mid-cycle captcha shows
  `🛡️ … x1` + finished `20:00 = base 05:00 + captcha 15:00 x1`.
- SOR row update in the same change (RULE 17).

## 6. Needed from the user (pins the exact gap, fix covers all regardless)

1. Log excerpt around the captcha minute (do lines `⚠ Security verification /
   Captcha detected` and `🛡️ Captcha penalty` appear? or `Captcha penalty skipped`?).
2. Live preset values (base minutes + m/captcha) at the time of the run.
3. Watcher enabled? (default OFF — confirm unchanged.)
4. Run shape: 1 image / 1 URL on the primary tab? (confirms single-path gap RC-A.)

## 7. Round 2 (2026-09-17, after user answers) — recorded-but-lost

User answers: **(1) BOTH lines appeared (detection + 🛡️ penalty)**, (2) preset
5 base + 15/captcha, (3) watcher OFF, (4) single 1-image/1-URL run.

This demotes RC-A (unrecorded gap) for THIS incident: the 🛡️ line proves
`add_captcha_penalty` was CALLED — yet the finish showed base only. The pending
was therefore either never stored (call returned -1) or stored-then-lost.
Further static verification (all clean):

- No double finish: `bridge.py:1835` is the `_finish_primary_tab` DEF,
  `bridge.py:3592` its only single-path call — `start_cooldown` runs once.
- `_settle_steady` (`cooldown_service.py:65-74`, read in full) does not touch
  pending; `refresh_expired`/`try_expire` act on COOLDOWN pages only, no
  pending touch (`page_status.py:69-83`); `mark_busy/mark_steady` clean.
- Gates chain the same id: select (2408) → ensure (2413) → wait (2414).
- No alias writers: `pending_penalty` touched only in `cooldown_service.py`
  (add/consume/restore-max/manual-reset), `page_status.py` (field), store.
- Pool clear/remove are manual `@Slot`s (`bridge.py:2139/2178`); a mid-run
  clear would yield NO cooldown ("unknown tab"), not 5:00 — ruled out.

### Ranked runtime explanations for "🛡️ logged + finish 5:00"

- **R1 — the 🛡️ line lied (x was -1).** Bridge logs 🛡️ UNCONDITIONALLY
  (`bridge.py:2687-2688`, `2919-2920`) with no `>= 0` guard — on page-missing
  it prints `🛡️ Captcha penalty +15m (x-1) — stacks onto next cooldown` while
  storing NOTHING (confirmed defect, fix regardless; dispatcher
  `single_job_runner.py:137` already guards `count >= 0`).
- **R2 — mid-run ♻️ reset ate the pending.** `reset_cooldown` (L317) zeroes
  pending unconditionally; a reset click during the long captcha wait →
  pending 900→0 → finish 5:00. Fits perfectly. Pending>0 exists only mid-job
  (or as crash residue), so reset should not own it — see F8.
- **R3 — two runs conflated** (🛡️+20:00 in an earlier run; complaint about a
  later no-captcha run's 5:00). Possible; log excerpt decides.
- **R4 — 🛡️ said +0m** (penalty read as 0 at record time). Log text decides.

### Fix additions (round 2)

- **F7 (hardened)** — guard the 🛡️ log on `>= 0`; on `-1`/missing pool-tab log
  `warn` (`Captcha penalty NOT recorded — unknown tab …`), never 🛡️, never silent.
- **F8 (new)** — `reset_cooldown` no longer zeroes `pending_penalty` /
  `captcha_count`: pending is job-cycle state owned by add/finish; reset clears
  only the live timer. Kills the R2 class entirely. Failing-first test: record
  (BUSY page) → reset → finish ⇒ total still base+penalty.
- **F9 (new)** — test the REAL shape: record on a BUSY page (today's tests use
  fresh STEADY pages, which is why the suite is green while the incident
  happened). All record/apply tests run against BUSY + COOLING + STEADY pages.

### Decisive follow-ups for the user

1. Exact 🛡️ line text (was it `(x1)` or `(x-1)`? `+15m` or `+0m`?) — R1 vs R4.
2. Any ♻️ / pool / clear clicks during that run (even idle clicking)? — R2.
3. Paste the detection → penalty → cooling log segment if still visible — R3.

## 8. Round 3 (2026-09-17) — remote forensics + impossibility proof

User answers round 2: 🛡️ line was **(x1) +15m** (recorded!), no mid-run clicks,
log gone. Plus sandbox/git findings:

- Recording is NOT in base `eee5ced` — the whole penalty feature is session work;
  record + consume were born in ONE commit `c29506e` (2026-09-16). **Every build
  showing 🛡️ also applies pending at finish — no skew window.** Remote branch
  `origin/arena/01a0a9cf` @ `72658b1` ("upd", on top of `2aabb70`) has the
  correct consume side, identical to local.
- Cancel path (`_finish_cancelled`, `cooldown_service.py:555-562`) settles with
  NO pause — user saw 5:00, so their finish took the normal path.
- Row matching is greedy 1:1 best-score + strict isolation (`url-list.js:292-345`),
  robust unless the job tab's LIVE pool URL diverges from the configured row URL.

### Single-run impossibility proof

In any single run on any build with recording: 🛡️(x1,+15m) ⟹ `pending=900` on
the job tab ⟹ normal finish reads it ⟹ total = 300+900 = 1200. No wipe ( §1.6),
no double finish (§7: `bridge.py:1835` is the def, `3592` the only call), no
overwrite (§1.7), same tab id (§7 gates), same pool object. **The 5:00 the user
saw was therefore NOT this job tab's finish total.** Remaining hypotheses:

- **T-B (display-side, refined): row showed another tab's 5:00.** Needs ≥2 pooled
  tabs + a recent no-captcha run cooling 5:00 on tab Y + job tab X's live URL
  diverging from the row URL (redirect/params) so greedy claims Y for the row
  while X's real 20:00 sits unclaimed (visible only in the pool panel).
  Decisive test: did the POOL panel show any tab cooling 20:00?
- **R3: two runs conflated** (🛡️+20:00 happened in an earlier run). Log is gone;
  build-hash log line (added `f551e34`) + repro with new logging decides.
- **D: the 5 min was read in the preset win** (always shows base 5 by config),
  not the live row/pool timer.

### Real defects to fix regardless (all confirmed in code)

F7 guarded 🛡️ log (lies on -1 today), silent pool/tab skips, F8 reset eats
mid-job pending, F6 finish log hides total+reason, F9 record-on-BUSY untested.
If T-B confirms: F10 bind each URL row to the tab id that ran it (sticky
`rowTabId` set at `_start_tab_image`, matched first in `assignPoolPages`).

### Git hygiene note (do before any push)

Sandbox HEAD is stale (`eee5ced`); all session work sits in 30 modified + 21
untracked paths; remote `72658b1` is AHEAD and 70 files differ (~22k lines).
Reconcile (fetch + diff + rebase/re-commit) before pushing anything.

## 9. Implemented fix (2026-09-17)

Root cause confirmed by elimination + user answers (🛡️(x1,+15m) logged, no
clicks, 5:00 seen in the URL row): the record→apply chain is airtight, so the
row showed ANOTHER tab's 5:00 — greedy URL matching ties across same-site tabs
and the first twin in snapshot order wins (§8 T-B). Implemented:

- **F1 choke point** `note_captcha_event(pool, tab_id, bridge, source)` —
  reads the preset, records, logs 🛡️ (or warn, never silent/lying), persists,
  emits. All 5 record sites call it (2 bridge sites slimmed to 1 line each).
- **F10 sticky row→tab binding** — run binds `UrlRow.tab_id` (single:
  `bridge.py` image-top; dispatcher: `_run_image_job`); `assignPoolPages`
  claims the bound tab first, greedy only for unbound/vanished;
  `matchPoolPage` fallback honors it. The row always shows its own tab's timer.
- **F4 phase-boundary checks** — single: submit + download boundaries via new
  `Bridge._settle_boundary_captcha` + tested `wait_captcha_cleared` service;
  dispatcher: `check_security` after submit + at download start.
- **F6 observability** — finish logs `cooling 20:00 (total 20:00 = base 05:00
  + captcha 15:00 x1)`; record logs pending/live-extension; legacy line kept
  when no captcha.
- **F7/F8 correctness** — 🛡️ only on success (`count >= 0`), warn otherwise;
  `reset_cooldown` preserves job-cycle pending (reset clears the live timer).
- **F9 tests** — record on BUSY/COOLING/unknown pages, waiter solved/stop/
  timeout/error, finish breakdown, boundaries, binding, never-breaks-job.

Deferred with rationale: per-poll captcha hook inside generation waits
(extra CDP round-trip per poll — perf-sensitive; boundaries + existing sites
cover the realistic shapes), watcher-side recording (watcher is
single-controller, cannot attribute a tab; default OFF), solve-dedup across
overlapping detectors (only matters with watcher ON).

Verification: pytest 220 passed (198 baseline + 22 new), node 40 passed;
radon all new/changed A/B (CC ≤ 9); coverage `cooldown_service` 80%,
`models` 82%; RULE 18 recheck §10 of `summary.md`.
