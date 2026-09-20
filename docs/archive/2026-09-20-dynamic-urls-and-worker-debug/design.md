# Design — Dynamic URLs & Worker Debug Panel (round 2, PLAN ONLY)

**Written:** 2026-09-20 · **Branch:** `arena/01a0bc3b-process-images-in-areana` · **Base:** `6bbaf8b`
**Status:** plan. **No production code was changed by this document.**
**Base plan:** `docs/archive/2026-09-20-live-processing-and-watcher-scope/` (round 1, D-1…D-10,
`app/services/live/` + `app/services/captcha/policy.py`). Round 2 **amends D-1, D-6 and D-9** and
adds two features; nothing in round 1 is retracted otherwise.
**Revision 2 (same day, owner instruction):** the single wave is replaced by a **staged chain S1…S10**
(§9) — separable features, most important first, least important last, each integrating into the next.
Revision 1 (single wave "W1") is preserved in git at `a5f69ee`; D-12 became **D-12R** and **D-24** was
added as a consequence of staging. Nothing else in the design changed.
**Evidence:** `evidence.md` in this folder (every claim below carries a `file:line`; §8 = the dependency
facts that fix the stage order).
**Budget:** `quality-budget.md` in this folder (RULE 16 / RULE 18 numbers, per-file headroom, tests).

---

## 0. How to read this plan (a chain of separable stages)

Round 1 was sequenced S0…S5; the first revision of this round collapsed both rounds into one wave.
The owner's latest instruction reverses that: **split the work into separable features, most important
first and least important last, implemented one by one and integrated in a chain.** That is §9
(**S1…S10**, plus the S0 bootstrap prerequisite). Round 1's features are **absorbed into the same
chain** — they were never implemented, and four of the ten stages are round-1 work; there is one plan,
not two.

"Important" is measured **architecturally**, in this order of precedence (D-24):

1. a defect that silently breaks other work outranks any feature (L-1, L-5);
2. a predicate / funnel that later stages read outranks the stages that read it (`captcha/policy`,
   `live/feed` + `commit_queue`);
3. a stage that changes what the app *does* outranks a stage that only changes what it *shows*;
4. pure observability is last — the debug window reads S1…S8 and adds no pipeline behaviour.

Each stage is separately committable, separately gate-green, updates its own `docs/current/` rows in
the same commit (RULE 17), and is **shippable on its own**: stop after any stage and the app is better
than before it. No later stage is required by an earlier one — the dependency facts are in
`evidence.md` §8.

---

## 1. Contract (one sentence per item)

| # | Item | Contract once its stage lands | Stage |
|---|---|---|---|
| 01 | URL update interval | The user sets `url_reconcile_interval_ms` (ms, clamped) and the Python URL reconciler re-checks tabs/rows at exactly that cadence — applied from the next pass, no restart, and it is a *floor*: any wake event triggers an immediate pass. | **S6** (setting + control) · read-only cadence in **S9** |
| 02 | Captcha ⇄ timeout | Watcher **OFF** ⇒ **no captcha activity at all** — no probe, no overlay, no `waiting_captcha` row, no stats/recording/penalty, no `🛡` line, **no pause**; the generation timeout runs exactly as if no dialog existed (round-1 D-1, made measurable by D-23). Watcher **ON** ⇒ the per-page generation timeout is **paused** while that page waits for a captcha to clear — with or without a 2Captcha key (without a key: detect, say so honestly, wait for the manual solve) — and both the wait and the pause are **capped** at the user's `watcher_captcha_timeout_sec`; at the cap the job fails honestly instead of hanging (D-13 + **D-14R**). | **S2** (OFF = zero activity) · **S3** (capped pause) |
| 03 | URL rows | Never-linked user rows are kept (D-4 confirmed); every row that cannot currently receive a job shows a small "not used as job receiver" icon; **all** images reset to pending (single Reset *and* Reset All) re-enter the queue immediately (D-6 **reversed**). | **S4** (reset re-queue) · **S7** (receiver icon) |
| 04 | L-1 | `connect_page_pool` schedules on the real helper, so "Add tab to pool" and the reconciler's tab join work. | **S1** |
| 05 | Live Worker & Queue Debug | One registered window shows every worker (page-pool tab) with its live job status, the pending-image count and the **name of the first image in the queue**, updated in real time from existing signals — and newly added / removed webpages appear and disappear in it without a restart. | **S8** (window contract + L-5 rescue) · **S9** (live content) |

---

## 2. Decisions (D-11…D-24; amendments named explicitly)

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| **D-11** | The interval is a **session config key** `url_reconcile_interval_ms`, default **5000**, clamped **500…60000 ms**, written through the existing `save_settings` slot by a new `apply_url_interval(bridge, data)` helper, read by the reconciler **once per pass**. | Brief item 01 (*user setting in ms*). Reusing `save_settings` keeps the frozen 134-slot surface (D-9/R8). Per-pass read = live effect, mirroring `watcher_interval_ms` (`config_manager.py:24`, clamped in `watcher_captcha.py:65-73`). | A new `set_url_interval` slot (contract churn); reading it once at loop start (needs a restart to apply — contradicts "dynamic"). |
| **D-12R** *(rev 2 — moved by the staging)* | The interval **control lives in the URL List window's job-cycle bar** (new ids `urlIntervalMs` + `urlIntervalSaveBtn` next to the existing cooldown knobs, wired by a **new** file `js/panels/url-list/interval.js`); the Live Debug window shows the cadence **read-only** ("reconcile every 5.0 s · last pass 2 s ago"). One writer, one display (RULE 10). | Staging forced the move: with the control in the debug window (S9) the setting (S6) would ship a stage with a backend-only knob. The job-cycle bar already owns the same kind of knob (`urlCooldownMin` + `urlCooldownSaveBtn`, `index.html:68-73`, bound in `url-list/listeners.js:31`, logic in `url-list/cooldown.js`) and sits **next to the rows it affects**; `settings.js` (252 lines / 48 funcs) and every `url-list/*.js` file stay untouched because the new control gets its own new file (evidence §6, §8). | (a) Control in the debug window (rev 1 — a stage with no UI). (b) Growing `settings.js` or `url-list/cooldown.js` (ratchet breach). (c) The URL List **title bar** (96 px title-fit invariant, SYSTEM_OF_RECORD row 19). (d) Two writable controls (RULE 10). |
| **D-13** *(amends round-1 D-1)* | Watcher **ON** ⇒ the generation wait charges every second spent inside the captcha settle to a **`PauseClock`**, and `_check_timeout` subtracts it: `elapsed = now − start − paused`. Watcher **OFF** ⇒ the clock stays at 0 because the `security_settler` is never installed (round-1 D-1) ⇒ the timeout runs exactly as today. The clock carries a **cap**: `note()` charges at most `cap − total`, so one generation wait can never absorb more than the cap (D-14R). | Brief item 02 bullets 1-2, and evidence §2: today an unbounded RULE-20 wait (`wait_captcha_cleared` "never gives up") always ends in `Timeout after …ms` even after the dialog cleared. One subtraction in one function fixes it for every caller of the wait loop. | (a) Restarting the wait after a settle (re-baselines `old_srcs`, risks losing the output that appeared during the solve — RULE 15). (b) Raising `watcher_generation_timeout_sec` globally (punishes the no-captcha case). (c) A per-page deadline in the pool (two owners of one timeout). |
| **D-14R** *(owner correction — reverses the first draft of D-14)* | The pause **is capped, and so is the wait** — one knob, the existing `watcher_captcha_timeout_sec` (default 300 s, clamped 10…3600, already editable in the Watcher window), bounds **both** (a) how long one captcha wait may last and (b) how much generation timeout one wait may absorb (`PauseClock(cap=…)`, cumulative **per generation wait**). At the cap the wait ends, the job fails retryable with an honest reason (`wait_timeout`), the tab keeps its normal cooldown, and the pause stops accruing ⇒ the worst case per image is bounded: `generation_timeout + captcha_cap`. Stop/abort still wins earlier, and the pause stays observable (throttled line, `waiting_captcha` row, debug-window worker line with absorbed/remaining budget). | Owner: *"D-14 — should be capped"* + *"no activity at all if off"* (with the Watcher OFF there is nothing to cap — D-23). Reusing one existing setting keeps RULE 10 (one control per decision) and adds no config surface; the wait overlay already counts that same number down (`service.py:257-258`), so the cap is visible while it runs. | (a) **Unbounded-but-observable** pause (the first draft of D-14 — rejected by the owner: a job could hang forever). (b) A second setting `captcha_pause_cap_sec` (two knobs for one decision; kept as the follow-up in §12 item 6). (c) Capping inside `wait_captcha_cleared` — its signature is already at the file's `max_params` **4** and its "never gives up" behaviour is pinned by `tests/test_cooldown_service.py:604-618`, so the cap is composed into the `stop` predicate the caller already passes, leaving that module and that test untouched. |
| **D-15** *(refines round-1 D-3)* | The captcha **wait reason** comes from one pure helper `policy.wait_reason(bridge)` with three outcomes: Watcher ON + key ⇒ *"Captcha Watcher is solving it (2Captcha SDK)"*; Watcher ON + **no key** ⇒ *"Watcher ON, no 2Captcha key — solve it in Chrome; this job's timeout is paused"*; (Watcher OFF never reaches the wait — round-1 D-1 `out_of_scope`). | Brief item 02 bullet 3. Today the no-key case tells the user to *"turn the Watcher ON"* while it is ON (`service.py:235-237`) — a lie in the UI. `_manual_wait` has **zero** LOC headroom (span 27 = file max 27), so the wording must be produced by the caller (`_resolve_captcha`, span 8). | Editing the string inside `_manual_wait` (ratchet breach); branching in JS (the pipeline owns the words). |
| **D-16** *(reverses round-1 D-6)* | **Every** reset re-queues: `reset_image_state(img)` drops its `selected` parameter and always sets `status="pending"`, `selected=True`. `reset_all` and `reset_image` both end in round-1's `commit_queue(bridge)` ⇒ the live loop picks the images up on the next wake (≤ ~50 ms idle). One log line states the count: `♻️ Reset All: N images → pending + re-queued (live run picks them up)`. | Brief item 03: *"All images that are reset to pending status are automatically re-added to the processing queue."* Round 1 parked `reset_all` (destructive-surprise argument); the owner has now explicitly overruled that. Undo still exists (`push_queue_undo`) and `retry_image` already behaved this way (`run_control.py:197-208`), so the vocabulary is consistent. | Keeping `reset_all` parked (round-1 D-6 — reversed by the brief); a confirm dialog (adds a JS edit to a frozen file and still contradicts "automatically"). |
| **D-17** *(confirms round-1 D-4)* | Never-linked user-typed rows are **kept**; the reconciler keeps trying to link them. No change. | Brief item 03 confirms it; I-20 (user-authorized URLs only) — a typed row is authorisation. | Grace-period deletion (destroys user intent on a slow Chrome start). |
| **D-18** | A row is a **job receiver** iff `enabled` **and** `tab_id` **and** that tab is in the pool **and** `is_connected`. Python computes it (`live/url_policy.mark_receivers(rows, live_tab_ids)`), stores it on the row (`UrlRow.receiver`, default `False`), publishes it (`urls_to_js` +1 key), and JS only **reflects** it: an inline `<span class="url-not-receiver" title="Not used as job receiver">⊘</span>` in the existing one-line row template + a CSS rule. | Brief item 03 (icon for links "not used as job receiver"). The rule is the conjunction the run gate already applies (`enabled_tab_ids`, `auto_connect.py:203-209`) plus pool liveness (`page_pool.status_snapshot`) — duplicating it in JS would create a second owner (RULE 10) and jscpd pressure. Zero JS line growth: `rowHtml` is a single template line (`render.js:6-8`). | Computing eligibility in JS from the pool payload (two owners of one rule); a new column (the table is already 8 columns wide and the title-bar/width invariants bite); reusing the `○ checking…` connection cell (that cell is written by `cdp.js`-owned code, frozen). |
| **D-19** | Receiver flags are recomputed by the **single writer** of URL rows: every reconcile pass and every `commit_urls` (user toggle / add / remove) ⇒ the icon flips immediately on a checkbox change and within one interval on a tab connect/disconnect. A wake (`pool`, `urls`) triggers an immediate pass, so the interval is a floor, not a latency. | Round-1 I-42 (Python owns rows) + I-37 (every mutation ends in `commit_urls`). | Recomputing on a separate timer (second cadence, second writer); letting JS poll a slot (new slot — forbidden by D-9). |
| **D-20** *(amends round-1 D-9)* | Item 05 adds **one window**, and D-9's substance is kept: **no new slot, no new signal, no growth of any baselined `.js` file**. The frozen surface stays 134 slots; the window-set contract grows 15 → **16** deliberately (like the slot contract, every pinned test is updated in the same commit). New behaviour lives in **new** JS files; the three registry edits are net-zero-line (evidence §6.1). | Brief item 05 mandates a window; round-1 D-9 forbade *contract churn for information the UI already receives* — the information is still received through existing signals, only the surface that shows it is new. | (a) Refusing the window and enriching the Progress panel (frozen JS, and the brief is explicit). (b) A floating non-grid overlay (outside the sash-grid contract: no persistence, no Windows menu, no presets — a second window system). |
| **D-21** | The new window **rescues the destroyed Page Pool panel** (L-5): window id `live_debug`, title **"Live Worker & Queue Debug"**, element `winLiveDebug`, containing (a) the *existing* pool markup moved verbatim (all element ids preserved ⇒ `PagePoolPanel` and its 4 frozen JS files are untouched), (b) a new **queue-head strip** (pending count, first image name, run state, reconcile age), (c) the **URL interval control** (D-12), (d) a new **per-worker job line** list. The orphan `data-window="page_pool"` div is deleted. | One worker table, one owner (RULE 10); zero duplication (jscpd 1.240 %); the pool UI becomes visible for the first time; `PagePoolPanel` keeps its cooldown controls (its own decision) while `LiveDebugPanel` owns the live job/queue view (a different decision). | (a) Registering `page_pool` as a 16th window *and* adding `live_debug` as a 17th (two overlapping worker tables). (b) Rewriting the pool table inside the new panel (4 frozen files re-implemented ⇒ jscpd + ratchet risk). (c) Leaving the orphan markup in place (dead DOM, and `replaceChildren` keeps destroying it). |
| **D-24** *(rev 2 — the staging rule itself)* | Work is delivered as **10 separable stages, most important first** (§9), each independently gate-green and shippable; importance is architectural (defect ⇒ predicate/funnel ⇒ behaviour ⇒ observability). Two hard staging rules follow: **(a)** a stage's *new* `.js` files must be **complete inside that stage** — a later stage adds new files, it never grows an earlier stage's, because an integrator's `--record-baseline` freezes whatever exists at that moment (`verify_quality.py:762-812`, `refresh=False` records new files); **(b)** each stage updates its own `docs/current/` rows in the same commit, so no stage ever leaves the docs describing a system that does not exist. | Owner instruction (*"split it to steps… separatable features… implementing one by one and integrating in chain"*) + the JS ratchet being **global** (with `--changed`, `check_js` measures *every* baselined `.js` file, `verify_quality.py:252-270,1032-1034`). | One wave (rev 1 — the owner reversed it); staging by file/layer instead of by feature (each step would be unshippable on its own). |
| **D-23** *(owner correction — "no activity at all if off")* | Watcher **OFF** means **zero captcha side effects**, asserted as a measured contract rather than as an absence of code: no per-poll `is_security_dialog_visible` (the settler is never installed), no detect probe, no overlay, no pool `waiting_captcha` mark, no stats, no recording, no penalty, no `CAPTCHA_SOLVE`/`CAPTCHA_JOB` line, no `🛡` log line, **no pause** (`clock.total == 0`, no cap installed), and no captcha/pause wording in the debug window's worker line. One predicate decides it (`policy.captcha_in_scope`, round-1 D-3) and one counting test proves the zero on a spy bridge/controller. | Owner wording; round-1 D-1/I-40 intended this, D-23 makes it measurable **including the two surfaces this round adds** (the pause clock and the debug window). | A per-site suppression list (a second decision owner); muting the log only (probe, overlay, stats and penalty would still run). |
| **D-22** | The debug window's data rides **existing signals only**: `page_pool_updated` (workers), `progress_updated` (counts, run state, and a new `live` object), `arena_state_updated` (jobs for the per-worker join). The new panel **self-connects** in `init()` via `Boot.onBridgeReady` (precedent: `arena-presets.js:39-48`), so `listeners.js` (frozen, 168 lines / 51 funcs) is untouched. Sub-second liveness comes from a **1 s JS ticker** that re-renders from cached payloads (elapsed/age counters) — no bridge traffic, no CDP traffic. Python publishes the *derived* facts (`queued`, `next_image`, `receivers`, `url_interval_ms`, `last_pass_at`) in `prog["live"]` from one pure helper `live_view(bridge)`, so no ordering/eligibility rule is re-implemented in JS. | Evidence §5.3: everything needed is already emitted except the queue head, which is one dict key. The ticker pattern is the same one `url-list/cooldown.js` already uses for countdowns. | A new `live_debug_updated` signal + slot pair (contract churn, D-20); polling a slot every second from JS (bridge traffic + a new slot); computing `next_image` in JS (second owner of the eligibility rule, I-41). |

---

## 3. Architecture deltas on top of round 1

### 3.1 Modules

| Path | Stage | Status | Owns | ~LOC |
|---|---|---|---|---:|
| `app/core/window_catalog.py` | S8 | **new** | `WINDOWS` (16 id/title pairs), `WINDOW_IDS`, `WINDOW_TITLES`, `LEGACY_WINDOW_IDS`, `GRID_VERSION = 6`, `MIN_GRID_SIZE` — moved out of `layout_service.py` (which re-exports all five names, so `from app.core.layout_service import WINDOW_IDS` keeps working for tests/panels) | 45 |
| `app/services/live/debug_view.py` | S9 (interval helpers in S6) | **new** | `live_view(bridge) -> dict` (queued, next_image, next_image_id, receivers, receiver_rows, workers_busy, url_interval_ms, last_pass_at, run_state) + `interval_ms(bridge)` + `next_queued(images)`; pure reads, no writes, no Qt | 90 |
| `app/browser/output_wait.py` | S3 | existing (211 → ~250) | gains `PauseClock(cap)` (mutable `total`; `note(seconds)` charges at most `cap − total`; `expired()`; `describe()`), `paused_elapsed(start, clock)` — the pause term lives with the timeout it modifies, and `cdp_arena/output.py:13` already imports `WaitSpec` from here | +34 |
| `app/services/live/reconcile.py` | S6 | round-1 file | gains: read `interval_ms(bridge)` per pass, wake-triggered immediate pass, `mark_receivers` call, `last_pass_at` stamp | +25 |
| `app/services/live/url_policy.py` | S6 (+ receivers in S7) | round-1 file | gains `mark_receivers(rows, live_tab_ids) -> int` (pure) and `receiver_reason(row, live_tab_ids) -> str` (tooltip wording) | +25 |
| `app/services/captcha/policy.py` | S2 (+ cap/reason in S3) | round-1 file | gains `wait_reason(bridge) -> str` (three-way, D-15), `has_key(bridge) -> bool`, `pause_cap_seconds(bridge) -> float` (the one knob, D-14R) and `WaitDeadline` (composes user-stop + cap-expiry into the `stop` predicate `wait_captcha_cleared` already accepts) | +40 |
| `app/ui/web/js/panels/live-debug.js` | S9 | **new** | facade `LiveDebugPanel` (`init`, `onPool`, `onProgress`, `onState`, `restore`), ends with `window.LiveDebugPanel = LiveDebugPanel` (I-35) | 90 |
| `app/ui/web/js/panels/live-debug/store.js` | S9 | **new** | `LiveDebugStore`: cached payloads, 1 s ticker start/stop, selectors, `esc`/`fmt` reuse via `UIHelpers` | 80 |
| `app/ui/web/js/panels/live-debug/render.js` | S9 | **new** | `LiveDebugRender`: queue-head strip, per-worker job lines, interval control value, receiver counters | 130 |
| `app/ui/web/js/panels/live-debug/actions.js` | S9 | **new** | `LiveDebugActions`: Refresh (`get_page_pool_status`), pause/interval readouts, row filters | 60 |
| `app/ui/web/js/panels/url-list/interval.js` | S6 | **new** | `UrlInterval`: binds `urlIntervalMs` + `urlIntervalSaveBtn` (own ids), clamps 500…60000, writes via `Boot.needBridge('save_settings')`, loads from `progress_updated.live`; ends `window.UrlInterval = UrlInterval` (I-35) | 60 |
| `app/ui/web/css/live-debug.css` | S8/S9 | **new** | the window's strips (queue head, worker job lines, cadence) — CSS is outside both ratchet lanes | 60 |
| `app/ui/web/css/arena.css` | S7 | existing (ungated) | gains the `.url-not-receiver` rule only — S7 runs *before* the window exists (S8), so the icon does not live in a file named after it | +6 |

Module counts after S10 (RULE 18.3, 5-15 files, measured at `6bbaf8b`): `app/core` 13 → **14** ✓;
`app/services/live` 0 → **7** (round-1 six + `debug_view.py`) ✓; `app/services/captcha` 6 → **7** ✓;
`app/services` 12 top-level files, unchanged ✓. Two modules are **already over the ideal** and this
wave deliberately does not worsen them: `app/browser` **23** top-level `.py` files (so `PauseClock`
goes *into* `output_wait.py` instead of adding a 24th) and `app/ui/panels` **16** (no new panel file —
the L-1 fix and the `live` publish line are edits). `app/ui/web/js/panels` gains one folder (4 files),
each ≤ 150 lines ✓ (JS folders are not a RULE 18 module).

### 3.2 Import direction (unchanged rule, new edges)

`ui → services → core/browser`; `services` never imports `ui` (round-1 D-10). New edges:
`ui/panels/layout_state → services/live/debug_view` (emit path) ·
`services/live/reconcile → services/live/url_policy` (receivers) ·
`services/live/debug_view → services/live/feed` (eligibility, one rule — I-41) ·
`browser/cdp_arena/output → browser/output_wait` (already exists for `WaitSpec`,
`cdp_arena/output.py:13` — now also imports `PauseClock`, so **no new module edge**).

### 3.3 Runtime picture (delta on round-1 §3.2)

```
Qt thread (frozen slots)                        bg loop thread
────────────────────────                        ──────────────
save_settings{url_reconcile_interval_ms} ──► config.set_state  (clamp 500…60000)
                                                RECONCILER  live/reconcile.py
                                                  every interval_ms(bridge)  ← read per pass (D-11)
                                                  OR immediately on wake("urls"|"pool")
                                                  … → url_policy.mark_receivers(rows, live_tabs)
                                                  → commit_urls → arena_state_updated
                                                  → last_pass_at = now  (for the debug window)
                                                JOB WAIT  cdp_arena/output.py::_run_wait
                                                  clock = PauseClock()
                                                  per poll: _security_gate(cdp, ctrl, clock)
                                                             └─ settler() blocked T seconds
                                                                ⇒ clock.note(T)   (D-13)
                                                  output_wait._check_timeout:
                                                    elapsed = now − start − clock.total
SUPERVISOR (round 1) ── emit_arena_state ──► progress_updated{…, live:{queued,next_image,…}}
                                          ──► page_pool_updated{pages[…current_image,current_job_id]}
                                          ──► arena_state_updated{urls[…receiver], images, jobs}
                                                              │
Web UI (self-connected, no listeners.js edit)                 ▼
  LiveDebugPanel: onProgress → queue head + interval ; onPool → workers ; onState → job join
                  1 s ticker → elapsed / reconcile age (no bridge traffic)
  UrlListRender.rowHtml → ⊘ icon when u.receiver === false (Python-computed, D-18)
```

---

## 4. Item 01 — URL update interval (ms)

**Config.** `DEFAULT_SESSION` gains `"url_reconcile_interval_ms": 5000`
(`config_manager.py:9-31`, next to `watcher_interval_ms`). Old `session.json` files load with the
default (`SessionStore._load_json(path, DEFAULT_SESSION)`) — no migration (RULE 13).

**Write.** `save_settings` (`app_settings.py:258-273`, span 16 / file max 18 ⇒ +1 line) calls a new
module-level `apply_url_interval(bridge, data)`:

```python
# app/ui/panels/app_settings.py (new symbol, ~7 LOC, CC 2)
def apply_url_interval(bridge, data: dict) -> None:
    """Persist the URL reconcile cadence (ms) when the payload carries it."""
    if "url_reconcile_interval_ms" not in data:
        return
    ms = clamp_interval_ms(data.get("url_reconcile_interval_ms"))
    bridge.config.set_state(url_reconcile_interval_ms=ms)
```

`clamp_interval_ms` lives in `live/debug_view.py` (one owner for the range, used by the JS-facing
publish path too). Undo: `save_settings` already ends in `push_settings_undo(self)` ⇒ the interval is
undoable with the rest of the settings (no new kind).

**Read (Python).** `live/reconcile.py` asks `debug_view.interval_ms(bridge)` **at the top of every
pass** and sleeps that long; a wake short-circuits the sleep (round-1 `LiveBus.wait`). Changing the
value therefore applies from the next pass without restarting the loop, and lowering it never
starves the wake path.

**Read + control (UI, D-12R).** The **control** ships in the same stage as the setting (S6): a new
`urlIntervalMs` number input + `urlIntervalSaveBtn` inside the URL List job-cycle bar
(`index.html:68-73`, ungated markup), wired by the new `js/panels/url-list/interval.js` and registered
by appending `'UrlInterval'` to `_PANEL_INITS` (net-zero line edit). It saves through
`Boot.needBridge('save_settings')` with `{url_reconcile_interval_ms: N}` — the same slot the Settings
panel uses — and loads its current value from `progress_updated.live.url_interval_ms`, published by one
added line in `emit_arena_state` (`layout_state.py:38-47`, span 10 / file max 19 ⇒ no new slot, no new
signal). The Live Debug window (S9) shows the same number **read-only** with the last-pass age.

**Clamp + feedback.** 500…60000 ms (below 500 ms the CDP `/json` fetch would become a hot loop;
above 60 s "dynamic" stops being true). JS clamps for instant feedback, Python clamps again on write
(never trust the wire — same shape as `parse_watcher_config`).

**Docs.** SYSTEM_OF_RECORD row 8 (Settings list) + row 11 (CDP connection: replace "scan on start +
every 15 s" with "Python reconciler at `url_reconcile_interval_ms`, default 5 s, plus immediate
passes on wake") — both amended **with** the code (RULE 17).

---

## 5. Item 02 — captcha ⇄ generation timeout

### 5.1 The pause clock (D-13)

```python
# app/browser/output_wait.py (added next to WaitSpec, ~40 LOC)
@dataclass
class PauseClock:
    cap: float = 0.0                             # seconds this wait may absorb (0 = nothing may be absorbed)
    total: float = 0.0
    def note(self, seconds: float) -> None:      # charge min(seconds, cap − total); ignore ≤ 0; never raises
    def expired(self) -> bool:                   # cap > 0 and total >= cap
    def describe(self) -> str:                   # "+37s captcha wait (cap 300s)" or ""

def paused_elapsed(start: float, clock) -> float  # now − start − (clock.total if clock else 0)
```

**Cap plumbing (D-14R, no signature changes).** `wait_for_output` installs the cap **next to the
settler** — `ctx.ctrl.pause_cap_s = policy.pause_cap_seconds(ctx.bridge)` at
`single_job_runner.py:249`, removed in the same `finally:` (`:257-261`) — and `_run_wait` builds
`PauseClock(cap=getattr(spec.ctrl, "pause_cap_s", 0.0))`. Neither
`CDPArenaController.wait_for_new_output` (`cdp_arena/mixins.py:139-146`) nor `cdp_arena.WaitSpec`
(`:29-35`) gains a parameter. With the Watcher OFF **neither** the settler nor the cap is installed,
so the clock cannot charge at all (D-23) — the OFF case is guaranteed by construction, not by a
branch inside the loop.

**`output_wait.py`** (211 → ~245 lines, `max_func_loc 23`, coverage floor 94.95 %):

* `WaitSpec` gains `pause: object | None = None` (+1 line in a 4-line dataclass — no function span).
* `_check_timeout` (span 11): the first line becomes `elapsed = paused_elapsed(state.start, spec.pause)`
  ⇒ **net-zero lines**, no CC change (the branch structure is untouched).
* `_handle_timeout_fallback` / `_process_fallback` keep using wall-clock elapsed for their own
  spinner-loss windows — deliberate: a captcha pause must not extend *revival* heuristics, only the
  hard timeout. Recorded here because it is the one place where two elapsed notions coexist.

**`cdp_arena/output.py`** (182 lines, `max_func_loc 16`):

* `_run_wait` (span 14 → 15): `clock = PauseClock()` (+1), `PollSpec(..., pause=clock)` (same line),
  `_security_gate(cdp, spec.ctrl, clock)` (same line).
* `_security_gate` (span 10 → 12): measure around the settle only —
  `t0 = time.monotonic()` before `await settler()`, `clock.note(time.monotonic() - t0)` after,
  guarded by `if clock is not None`. No charge when the dialog is not visible (the settle never ran)
  and no charge when `settler` is absent (Watcher OFF, round-1 D-1) ⇒ **item 02 bullet 1 falls out of
  the construction, not out of a branch**.
* `_map_wait_result` (span 10 → 11): the failure text becomes
  `f"Timeout after {timeout_ms}ms{clock.describe()}"` and the payload gains `"paused_s": int(clock.total)`
  ⇒ an honest post-mortem (RULE 2, RULE 4: the reason names the gate that broke *and* the wait it
  absorbed). Its signature changes from `(cdp, result, baseline, timeout_ms)` — **4 params, the file
  maximum** — to `(cdp, result, spec)`, reading `spec.baseline` / `spec.timeout_ms` / `spec.pause`
  inside (params 4 → **3**, no growth; same param-object style as `WaitSpec`/`JobCtx`/`BatchCtx`).
  The single call site is `_run_wait:171`, so the edit is net-zero lines.

### 5.2 The cases after S3 (including the cap)

| Case | Detection | Wait | Generation timeout | Cap reached (`watcher_captcha_timeout_sec`) | User-visible wording |
|---|---|---|---|---|---|
| Watcher **OFF** | **none** (round-1 D-1 + D-23: `check_security` returns False, `handle_captcha` → `out_of_scope`, no settler, no cap, no overlay, no stats, no recording, no penalty, no `🛡` line) | none | **runs** (clock 0) | n/a — nothing waits | the gate that actually broke (`WAIT_OUTPUT` timeout / page-error text) |
| Watcher **ON** + key | detect probe + stats + recording + `waiting_captcha` row | `_manual_wait` until the solver or the user clears it | **paused** for the wait, up to the cap | wait ends ⇒ `wait_timeout` ⇒ job FAILED (retryable), cooldown as usual | overlay reason: *"Captcha Watcher is solving it (2Captcha SDK)"*; throttled `⏸ Generation timeout paused for captcha wait (Ns / cap Ms)` |
| Watcher **ON**, no key | identical (detection does not depend on the key) | identical — waits for the **manual** solve | **paused**, up to the cap | identical | overlay reason (D-15): *"Watcher ON, no 2Captcha key — solve it in Chrome; this job's timeout is paused (cap Ms)"*; the existing `solver_start` warn line stays (`watcher_solver.py:130-134`) |
| Watcher **ON**, second captcha in the same generation | detected again (new encounter) | a fresh wait, bounded by the same knob | the clock is **already near/over its cumulative cap** ⇒ further settles charge nothing ⇒ the timeout counts down in real time | — | `⏸ Pause budget exhausted (cap Ms) — generation timeout running again` |

`policy.wait_reason(bridge)` is the single owner of that wording; `_resolve_captcha`
(`service.py:232-239`, span 8 → 9) calls it and passes the result to `_manual_wait` — the wording is
produced by the *caller* because `_manual_wait` has zero LOC headroom (span **27** = file `max_func_loc`
27, evidence §6.1); its own body only shrinks (§5.3: the outcome `if/else` is extracted, the cap rides
the `stop` argument it already passes).

### 5.3 Interaction with the rest of the pipeline

* **The wait is bounded by the caller, not by `cooldown_service`** (D-14R): `_manual_wait` passes
  `WaitDeadline(timeout).stop_or_expired(_stop_pred(ctx))` as the `stop` argument
  `wait_captcha_cleared` already accepts (`cooldown_service.py:446`), so that module, its
  `max_params 4` signature and its pinned "keeps waiting" test all stay untouched.
  `solved=False` **and** `deadline.expired()` ⇒
  `SolveOutcome(status="wait_timeout", reason=f"Captcha not cleared in {timeout}s — job failed (retryable)")`;
  `status` is a free-form string (`captcha/signals.py:94-99`), so no enum changes (round-1 already adds
  `out_of_scope`).
* `_handle_captcha_outcome` (`single_job_runner.py:75-85`) maps `wait_timeout` to
  `raise RuntimeError(outcome.reason)` — the exact shape its `page_error` branch already uses ⇒ the job
  fails retryable and the failure names the cap and the knob.
* `_manual_wait` **shrinks** 27 → ~21 LOC: the 7-line solved/stopped `if/else` (`:269-275`) becomes one
  call to a new `_wait_outcome(ctx, solved, expired, signal)` (~14 LOC). Required anyway — the file's
  `max_func_loc` is 27 and `_manual_wait` is at it.
* Cooldown penalty recording (`_record_penalty`, once per cleared edge) is unchanged — the pause does
  not create a second captcha event, and a cap-reached failure records no penalty (nothing was cleared).
* Post-settle **revival** (`captcha/recovery.py`, `arm_resume`/`note_settle` at
  `single_job_runner.py:265-271,279-292`) is unchanged: it is triggered by the settle, not by the
  timeout, and its own bounded resubmit is not extended by the clock (§5.1).
* The dispatcher's parallel lane gets the same behaviour for free: it calls the same
  `wait_for_new_output` path per job.
* `wait_for_free_page` / `cooldown_aware_timeout` (`page_pool.py:178-189`,
  `cooldown_service.py:549-556`) are **not** touched: the pause is scoped to one page's generation
  wait, exactly as the brief words it ("for that page").

---

## 6. Item 03 — URL rows: receiver icon + reset re-queue

### 6.1 Receiver flag (D-18/D-19)

```python
# app/services/live/url_policy.py (pure, +25 LOC)
def receiver_reason(row, live_tab_ids) -> str:   # "" | "unchecked" | "no tab" | "tab offline"
def mark_receivers(rows, live_tab_ids) -> int:   # sets row.receiver, returns changed count
```

`live_tab_ids` = `{p.tab_id for p in snapshot["pages"] if p["is_connected"]}` (from
`page_pool.status_snapshot()`), intersected with `enabled_tab_ids(rows)` semantics by construction
(`enabled` + `tab_id` are checked per row). One writer: called from `reconcile_once` (after
`sync_pool_presence`, before `commit_urls`) and from `commit_urls` itself so a checkbox flip is
instant. `UrlRow.receiver: bool = False` (`models.py:13-21`) round-trips through
`asdict`/`UrlRow(**u)` with no migration; both undo builders gain the key
(`undo_entries.py:21-41`) so undo/redo does not blank the icons.

### 6.2 Icon (zero JS growth)

* `urls_to_js` (`arena_serialize.py:12-25`, span 14 / file max 23) publishes `"receiver": bool(u.get("receiver", False))`.
* `rowHtml` (`url-list/render.js:6-8`) — inside the existing single template line, next to the URL
  text: `${u.receiver === false ? '<span class="url-not-receiver" title="Not used as job receiver">⊘</span>' : ''}`.
  The `title` carries the reason; `render()` rebuilds rows on every `arena_state_updated`, so the icon
  follows the flag with no extra JS.
* `.url-not-receiver` styling in the existing `css/arena.css` (muted colour, 11 px, `cursor:help`) —
  ungated, and S7 must not depend on a file the S8 window introduces.
* Rows that are receivers show nothing (absence = healthy), so the icon is a *warning* marker and the
  table does not grow a column (title-bar/width invariants, SYSTEM_OF_RECORD row 19).

### 6.3 Reset re-queue (D-16)

```python
# app/ui/panels/run_control.py — net-zero lines
def reset_image_state(img) -> None:      # parameter deleted (no caller passed False; no test used it)
    img.status = "pending"; img.selected = True; img.error = None
    img.output_path = None; img.assigned_url_id = None; img.attempt_count = 0

def reset_all(self):      # slot body: reset_image_state(img) … then commit_queue(self) (round 1)
                          # + one log line with the count
def reset_image(self, img_id):   # same call, same funnel
```

Both slots end in round-1's `commit_queue(bridge)` (recalculate + save + emit + undo + `wake("queue")`)
⇒ a live run picks the images up on the next pass (round-1 §7.2: ≤ ~50 ms when idle). `reset_all`
keeps clearing `state.jobs` and keeps `push_queue_undo` (Undo restores the previous statuses —
the destructive-surprise protection round 1 wanted now lives in Undo + the log line instead of in a
parked queue).

### 6.4 D-9 confirmation

Round-1 D-9 ("the passive re-check + live queue works") is confirmed by the brief and unchanged, with
one amendment of scope: it now also covers the new window (D-20) — the *slot* surface stays frozen,
the *window* surface grows by one, deliberately.

---

## 7. Item 04 — L-1 (stage **S1**, first)

`app/ui/panels/page_pool.py:147`: `self._schedule_coro(...)` → `schedule_coro(self, ...)` with
`from app.services.run_state import schedule_coro` added to the module imports (the pattern used by
`browser_tabs.py:25`, `cdp_tools.py:14`, `run_control.py:16`). Same LOC in the slot body
(span 13 / file max 16), +1 import line (Python lines are not ratcheted).

Regression test `tests/test_page_pool_join.py` (round-1 budget §6.1) asserts the slot schedules on a
host that does **not** define `_schedule_coro` — i.e. the test fails on the old code by construction,
which is also the guard against the fake-bridge masking that hid the defect
(`tests/test_panel_browser_tabs.py:82,156,168,180,211` inject `_schedule_coro=`).

---

## 8. Item 05 — the Live Worker & Queue Debug window

### 8.1 Registration (16 windows, one deliberate contract change)

| Layer | Edit | Line-cost |
|---|---|---|
| `app/core/window_catalog.py` (new) | 16 `{id,title}` pairs incl. `{"id": "live_debug", "title": "Live Worker & Queue Debug"}`; `GRID_VERSION = 6`; `LEGACY_WINDOW_IDS` unchanged (`page_pool` was never valid, so no stored tree can contain it) | new file |
| `app/core/layout_service.py` | import + re-export the five names; `default_grid_tree` gains `leaf("live_debug")` **on the existing right-column line** with rebalanced sizes `[24, 20, 16, 20, 20]` (span stays 21 = file max) | −28 lines (table moved out) |
| `sash-core/constants.js` | window entry appended to the `arena_presets` line; `VERSION: 6` on the return line | **0** (25 lines / 3 funcs) |
| `sash-grid-windows/store.js` | `live_debug: 'winLiveDebug'` appended to the last map line in `_collectPanels` | **0** (122 / 19, `_collectPanels` span 14) |
| `arena-app.js` | `'LiveDebugPanel'` appended to the last `_PANEL_INITS` line | **0** (176 / 28) |
| `index.html` | the orphan `winPagePool` div (29 lines) becomes `<div class="panel" id="winLiveDebug" data-window="live_debug">` with a new title row, the moved pool body, the queue-head strip, the interval control and the worker-job list; `<link … live-debug.css>`; 4 `<script>` tags before `arena-app.js` | HTML (ungated) |
| Migration | none to write: `migrate_grid_tree` (`layout_service.py:283-297`) appends the missing leaf to every stored v≤6 layout, and JS `sashDeserialize*` (`validate.js:100-142`) does the same; `GRID_VERSION` 6 keeps old payloads acceptable (`1 <= v <= GRID_VERSION`) | 0 |
| Windows menu / presets / dock | automatic — all iterate `SashCore.WINDOW_IDS` / `WINDOW_TITLES` (`sash-grid-windows/menus.js:100`, `store.js:34,96-97`, `windows.js:52-102`); `window_preset_service` counts leaves dynamically (`:106,124`) | 0 |

### 8.2 Window content (four blocks, one owner each)

| Block | Element ids | Owner | Source |
|---|---|---|---|
| **Queue head** | `ldQueued`, `ldNextImage`, `ldRunState`, `ldReceivers` | `LiveDebugRender.queueHead()` | `progress_updated.live` (`queued`, `next_image`, `run_state`, `receivers`) |
| **Reconcile cadence** (read-only — the writable control lives in the URL List bar, D-12R/S6) | `ldInterval`, `ldLastPass` | `LiveDebugRender.cadence()` | `live.url_interval_ms`, `live.last_pass_at` |
| **Worker job lines** | `ldWorkerJobs` | `LiveDebugRender.workers()` | `page_pool_updated.pages[]` (`status`, `current_image`, `current_job_id`, `busy_since`, `jobs_completed`, `captcha_count`, `cooldown_remaining`) joined to `arena_state_updated.jobs[]` for image path/attempt/error |
| **Pool table + controls** (rescued) | `poolStatusBadge`, `poolTotal…poolFree`, `poolTableBody`, `poolRefreshBtn`, `poolConnectBtn`, `poolClearBtn` | `PagePoolPanel` (**unchanged**) | `page_pool_updated` via `listeners.js:115-118` (unchanged) |

Worker job line format (one line per pool page, job-centric — deliberately *not* a copy of the
tab-centric pool table):

```
🟦 3F2A…  arena.ai/image/direct   ▶ photo_014.jpg   generating 42s   job 20260920-141502-AB12 · attempt 1
🛑 9C11…  arena.ai/image/direct   ⏸ captcha wait 1m12s — generation timeout paused   🛡x2
🟩 7B02…  arena.ai/image/direct   idle · 12 jobs done · cooldown 3m41s
⚪ —      (no pages in pool)      waiting for a webpage: add a tab or let the reconciler join one
```

Phase is derived from the pool `status` (`busy` / `waiting_generation` / `waiting_captcha` /
`cooldown` / `steady` / `error` / `disconnected` — `page_status.py:17-25`) plus `busy_since` for the
elapsed time; the paused-timeout wording appears when `status == waiting_captcha` **and** the Watcher
is ON (from `live_view`, so JS does not re-derive policy).

### 8.3 Real-time model (D-22)

* **Push:** three existing signals; the panel self-connects in `init()` under `Boot.onBridgeReady`
  (bridge exists before panels init — `arena-app.js:167-173`), each `connect` guarded by `try` and by
  `if (bridge.X)` (the `test_boot_all_panels.mjs` fake bridge makes every member connectable).
* **Tick:** one 1 s `setInterval` in `LiveDebugStore` re-renders elapsed/age fields from the cached
  payloads — no bridge call, no CDP call (the same trick `url-list/cooldown.js` uses for countdowns).
  The ticker starts only when the window is visible (`SashGrid.isClosed/isMinimized` are readable via
  `window.SashGrid`) and stops when it is hidden ⇒ no background churn.
* **First paint:** `restore(data)` is called from `_restoreArenaPanels` **only** for the six panels
  listed there (`arena-app.js:120-126`, frozen) ⇒ the debug panel instead pulls its first payload on
  `init()` through existing slots: `Boot.needBridge('watcher_status')` is *not* used (no new
  dependency); the first `progress_updated` / `page_pool_updated` arrives within one emit cycle
  because `initWithBridge()` immediately calls `_loadArenaState()` and the pool emits on connect.
  Belt-and-braces: `LiveDebugActions.refresh()` (the Refresh button already in the rescued markup)
  calls the frozen `get_page_pool_status` slot (`app/ui/panels/page_pool.py:105-118`, which emits the snapshot itself) and waits for the next push otherwise.
* **New/removed webpages:** add ⇒ reconciler joins the tab (needs L-1, §7) ⇒ `add_page` ⇒
  `_emit_pool_status` (`app/ui/bridge.py:100-108`) ⇒ the worker list grows; remove ⇒ `sync_pool_presence` / `disconnect_page_pool`
  (`page_pool.py:153-165`) ⇒ `_emit_pool_status` ⇒ the row disappears. Both also flip URL-row
  receiver flags (§6.1) in the same pass.

### 8.4 Tests for the window (see `quality-budget.md` §6 for the full matrix)

`tests/test_window_catalog.py` (Python/JS tables identical — extends the existing desync guard),
`tests/test_live_debug_view.py` (`live_view` pure-read contract, `interval_ms` clamp, `next_queued`
order), `tests/js/test_live_debug_panel.mjs` (loads the real `index.html` scripts, asserts
`window.LiveDebugPanel` publishes itself, renders a queue head + a paused worker from fake payloads,
and that `winLiveDebug` is mounted by the grid instead of destroyed), plus the four `15 → 16` count
assertions in `tests/test_grid_layout.py:245-253` and the harness lists in `tests/js/sash_harness.mjs`.

---

## 9. Staged delivery — S1…S10, most important first (D-24)

**S0 (prerequisite, not a stage):** bootstrap `.venv` + `npm ci`, then capture the equivalence
baseline — gate output, coverage, jscpd, goldens (`quality-budget.md` §1-§2). Every stage below starts
from a green tree and ends green.

| Stage | Separable feature | Why it sits here | Depends on | What the user gets if the chain stops here |
|---|---|---|---|---|
| **S1** | **L-1 — the pool join works** (`page_pool.py:147` `_schedule_coro` → `schedule_coro` + import) | One word, and today *no* tab can join the pool through the slot: every later worker-facing stage would be built on a broken seam (evidence §4) | — | "Add Selected Tab to Pool" works; parallel mode can actually get pages |
| **S2** | **Captcha scope — Watcher OFF = zero activity** (new `captcha/policy.py`, 5 gate edits, `out_of_scope`, D-23 counting test) | The loudest complaint, and the *predicate* every later captcha decision reads (scope, cap, wording, debug-window silence) | — | No detection, overlay, penalty, stats, recording or `🛡` line while the Watcher is OFF |
| **S3** | **Captcha ⇄ generation timeout — capped pause** (`PauseClock` in `output_wait.py`, `_security_gate` charging, `wait_timeout`, `wait_reason`) | The job-killing bug: a captcha that *was* cleared still ends in `Timeout after …ms` (evidence §2). Needs S2's `policy.py` | S2 | A solved captcha no longer fails the job; bounded worst case `generation_timeout + captcha_cap`; honest no-key wording |
| **S4** | **Live queue core + reset re-queue** (`live/bus.py`, `live/feed.py`, `commit_queue` in 8 slots, `schedule_batch`, `_state_lock`, one eligibility rule, **D-6R**) | The funnel + wake event every "dynamic" stage writes into; also deletes the duplicated eligibility rule (L-4) and makes D-6R live | — | Reset / Reset All / Retry / Scan re-enter the queue immediately (≤ ~50 ms idle) |
| **S5** | **Always-live run** (`live/supervisor.py`, single run-state writer D-8, orchestrator/dispatcher tail surgery, scan-guard change) | The consumer of S4's wake; makes "runs until stopped" true and `run_state` honest (fixes L-2) | S4 | The run survives no-work / no-tab / all-cooling / CDP-down; only Stop ends it |
| **S6** | **Dynamic URLs + the interval setting** (`live/url_policy.py`, `live/reconcile.py` with `LiveDeps.join_tab`, `browser_tabs.py` move-out, JS 15 s interval **deleted**, `url_reconcile_interval_ms` + `apply_url_interval` + new `url-list/interval.js` control) | Rows must follow the live tabs; joins through S1's fixed path, commits through S4's funnel; the cadence knob belongs with the loop it drives and ships **with** its UI (D-12R) | S1, S4 (full value with S5) | Webpages opened/closed in Chrome add/remove URL rows on the fly, in any run state, at a user-set cadence |
| **S7** | **Receiver flag + ⊘ icon** (`UrlRow.receiver`, `mark_receivers`, `urls_to_js`, `rowHtml`, both undo builders, `.url-not-receiver` CSS) | A read model on top of S6's single row writer; the debug stage displays its count | S6, S4 | Every row that cannot receive a job is visibly marked, and the mark follows a checkbox flip instantly |
| **S8** | **Window contract 15 → 16 + L-5 rescue** (new `core/window_catalog.py`, `layout_service` re-export + leaf, JS registry ×3, `index.html` markup move, pinned tests) | The riskiest *contract* change, deliberately placed after the behaviour is stable — and the prerequisite for S9. Fixes the destroyed Page Pool window (evidence §5.2) | — | The workers table (tabs, status, job, cooldowns, controls) is visible for the first time |
| **S9** | **Live Worker & Queue Debug content** (`live/debug_view.py::live_view`, `prog["live"]`, 4 new `live-debug/*.js`, CSS, read-only cadence) | Pure observability: reads S1…S8, adds no pipeline behaviour ⇒ architecturally last (D-24.4) | S4, S5, S6, S7, S8 | One window: every worker + job phase + elapsed, pending count, **first image name**, receiver count, reconcile cadence/age — live |
| **S10** | **Consolidation**: `QUALITY_RECHECK.md` refresh, RULE 18 recheck of every touched/new file, full gate, baseline decision | The recheck the brief asks for; it must see the whole chain | S1…S9 | A gate-clean, doc-consistent release |

### 9.1 What every stage must satisfy (the stage contract)

1. **Tests first** for its own new symbols (RULE 16.6 step 3); the test that fails before the fix is
   named in §9.3.
2. **Fast lane green** after the stage: `verify_quality --changed --allow-legacy --coverage-ratchet`
   (+ `npm run test:js` when it touched JS). Remember the JS lane is **global**: touching one `.js`
   file gates every baselined `.js` file (`verify_quality.py:252-270,1032-1034`).
3. **No slot, no signal, ever** (D-20): `tests/test_bridge_slots.py` and `test_bridge_metaobject.py`
   stay unedited through all ten stages.
4. **New `.js` files are complete inside their stage** (D-24a): a later stage adds files, never lines
   to an earlier stage's file — an integrator's `--record-baseline` freezes whatever exists then.
5. **Its own doc rows land in the same commit** (RULE 17, D-24b) — §9.3 names them per stage.
6. **Goldens unchanged**, unless the stage says otherwise (only S5 may need a reviewed regeneration —
   the harness arms `_stop_after`, round-1 R7).
7. **The app runs** at the end of the stage (no half-registered window, no orphan markup, no dead
   panel): a stage that changes a contract changes *every* side of it in the same commit.

### 9.2 The integration chain

```
S1 pool join ─────────────────────────────┐
S2 captcha scope ──► S3 capped pause      │  (behaviour, most important)
S4 queue funnel ───► S5 always-live run   │
        └──────────► S6 dynamic URLs ◄────┘   (S6 joins tabs via S1, commits via S4)
                        └────────► S7 receiver flag
S8 window contract (15→16) + L-5 rescue ──► S9 debug window content
                                              ▲ reads S4 queued/next · S5 run_state ·
                                              │ S6 cadence/last pass · S7 receivers · S1/S8 workers
S10 consolidation (docs + gates + RULE 18 recheck)
```

Two independent tracks run in parallel and only meet at S9: the **behaviour track** (S1→S7) and the
**surface track** (S8). S2/S3 are independent of S4-S7, so the captcha fixes can ship first even
though the live-loop work is larger.

### 9.3 Per-stage detail (files · the test that proves it · doc rows)

| Stage | Files touched / added | Proving test(s) | `docs/current/` rows in the same commit |
|---|---|---|---|
| **S1** | `app/ui/panels/page_pool.py` (1 word + 1 import) | `tests/test_page_pool_join.py` — schedules on a host **without** `_schedule_coro` (fails at `6bbaf8b`) | row 19 note (pool join repaired); evidence of L-1 closed |
| **S2** | new `app/services/captcha/policy.py`; `app/services/captcha/service.py`; `app/services/single_job_runner.py`; `app/services/captcha/signals.py` (`out_of_scope`) | `tests/test_captcha_scope.py`, `tests/test_watcher_off_zero_activity.py` (counts 0 probes / 0 overlays / 0 stats / 0 recordings / 0 penalties / 0 `🛡` lines) | **RULE 20** amendment (OFF = out of scope), **I-19/I-34/I-40**, row 12 |
| **S3** | `app/browser/output_wait.py` (`PauseClock`, `paused_elapsed`, `_check_timeout` line), `app/browser/cdp_arena/output.py` (`_security_gate`, `_run_wait`, `_map_wait_result` params 4→3), `app/services/captcha/service.py` (`_manual_wait` shrinks, `_wait_outcome` extracted), `app/services/captcha/policy.py` (`pause_cap_seconds`, `WaitDeadline`, `wait_reason`), `app/services/single_job_runner.py` (`ctrl.pause_cap_s`, `_handle_captcha_outcome` +`wait_timeout`) | `tests/test_pause_clock.py` (cumulative cap), `tests/test_output_wait_timeout_pause.py` (pause works **and** cap-reached times out), `tests/test_captcha_wait_cap.py`, `tests/test_captcha_wait_reason.py`; `tests/test_cooldown_service.py:604-618` stays **unedited** | **RULE 20** (bounded wait + capped pause), **I-44**, row 12, row 8 (the knob doubles as the cap) |
| **S4** | new `app/services/live/{__init__,bus,feed}.py`; `app/ui/panels/run_control.py` (`reset_image_state` param deleted, `commit_queue` tails), `app/ui/panels/queue_scan.py` (delegation + tails), `app/services/run_state.py` (`schedule_batch`, `_track_batch_future` deleted), `app/services/batch_orchestrator.py` (`_selected_images` deleted) | `tests/test_live_bus.py`, `tests/test_live_feed.py`, `tests/test_reset_requeues.py` (both resets ⇒ `pending` + `selected` + wake + count log line) | **I-41**, **I-46**, rows 6/11 (queue funnel), row 8 (Reset semantics) |
| **S5** | new `app/services/live/supervisor.py`; `app/services/batch_orchestrator.py`, `app/services/multi_page_dispatcher.py`, `app/ui/panels/run_control.py`, `app/ui/panels/queue_scan.py` (scan guard), `app/ui/panels/layout_state.py` (nothing — `run_state` becomes honest by D-8) | `tests/test_live_supervisor.py` (no-work/no-tab/cooling/CDP-down ⇒ wait, never end; Stop ⇒ idle), goldens reviewed | **I-39**, row 6 (run lifecycle), row 11, `QUALITY_RECHECK` note |
| **S6** | new `app/services/live/{reconcile,url_policy}.py`; `app/ui/panels/browser_tabs.py` (move-out + delegations), `app/ui/panels/url_queue.py` (helper delegations), `app/persistence/config_manager.py` (key), `app/ui/panels/app_settings.py` (`apply_url_interval`), `app/services/live/debug_view.py` (`interval_ms`, `clamp_interval_ms` only), `app/ui/panels/layout_state.py` (`prog["live"]` line), new `app/ui/web/js/panels/url-list/interval.js`, `index.html` (bar markup), `arena-app.js` (`'UrlInterval'`), `app/ui/web/js/panels/cdp.js` (**−1 line**, 15 s interval deleted), `package.json` (+1 `.mjs`, ungated explicit list) | `tests/test_live_reconcile.py` (interval re-read per pass; empty fetch never removes; live-job deferral), `tests/test_url_policy.py`, `tests/test_url_interval_setting.py`, `tests/js/test_url_interval_control.mjs`; `tests/js/test_cdp_store*.mjs` for the deletion | **I-42** (cadence is the user setting), row 11 (JS 15 s timer gone), row 8 (new setting), row 21 |
| **S7** | `app/core/models.py` (`UrlRow.receiver`), `app/services/live/url_policy.py` (`mark_receivers`, `receiver_reason`), `app/services/live/reconcile.py` (call), `app/ui/services/arena_serialize.py`, `app/ui/services/undo_entries.py` (×2 builders), `app/ui/web/js/panels/url-list/render.js` (**0 lines**), `css/arena.css` (+6, ungated), `package.json` (+1 `.mjs`) | `tests/test_url_receivers.py`, `tests/js/test_url_list_receiver_icon.mjs` (icon present/absent **and** `render.js` line count unchanged) | **I-45**, row 21 (receiver = row view of the run gate), row 19 (icon) |
| **S8** | new `app/core/window_catalog.py`; `app/core/layout_service.py` (re-export + leaf on an existing line, `GRID_VERSION` 6); `js/sash-core/constants.js` (**0**), `js/sash-grid-windows/store.js` (**0**), `js/arena-app.js` (**0**); `index.html` (orphan `winPagePool` → `winLiveDebug`); new `css/live-debug.css`; tests: `test_grid_layout.py` (15→16 ×4), `tests/js/sash_harness.mjs` (ids + title secondaries), `package.json` (+1 `.mjs`) | `tests/test_window_catalog.py` (Python ≡ JS ≡ element map), `tests/js/test_live_debug_panel.mjs` part 1 (grid **mounts** `winLiveDebug`; the pool table renders into a mounted element), `test_title_fit.mjs`, `test_boot_all_panels.mjs` | row 19 (**16 windows**, stale `captcha_records` name fixed, L-5 recorded), **I-43**, `data_model`/storage notes if the preset doc shape is quoted |
| **S9** | `app/services/live/debug_view.py` (`live_view`, `next_queued`), `app/ui/panels/layout_state.py` (`prog["live"]` — from S6, extended), new `js/panels/live-debug{,/store,/render,/actions}.js`, `index.html` (queue-head strip + worker job lines + cadence readout), `arena-app.js` (`'LiveDebugPanel'`, **0 lines**), `css/live-debug.css` (grown, ungated) | `tests/test_live_debug_view.py` (read-only, `next_queued` = first eligible), `tests/js/test_live_debug_panel.mjs` part 2 (queue head, paused worker line, cadence, 1 s ticker with **no** bridge call) | row 19 (what the window shows), **I-43/I-44/I-45** enforcement pointers, `QUALITY_RECHECK` |
| **S10** | `docs/current/QUALITY_RECHECK.md`, `docs/README.md` ("UI 15 windows" → 16), this folder's checklists | full gate: `bash tools/pre_push_check.sh`, all-py test run, `npm run test:js` (**28** files — 3 new `.mjs` appended in S6/S7/S8), radon, cognitive, jscpd | everything above verified consistent; baseline re-record **only** with a stated reason |

### 9.4 Deliberately un-splittable (must land inside one stage's single commit)

* **S3**: the cap, the `wait_timeout` outcome and its `_handle_captcha_outcome` mapping — a cap
  without the honest failure would silently hang, a failure without the cap would kill solved jobs.
* **S4**: `reset_image_state`'s parameter deletion + both slot call sites + `commit_queue` (D-6R is one
  decision, not three edits).
* **S6**: the setting, its clamp, the per-pass read **and** its control (D-12R) — a backend-only knob
  is not a user setting.
* **S8**: the window table, the default tree, the three JS registries, the markup move and the four
  pinned test counts — a half-registered window is exactly L-5.
* **S9**: `live_view` and the four JS files — the panel must not publish itself before its data exists
  (I-35/B6 class of dead-UI bug).

### 9.5 Value prefixes (why this order and not another)

* After **S3**: the two defects that made the app unusable for long runs are gone (a captcha no longer
  kills a solved job; the Watcher switch actually means something).
* After **S5**: the run is live and the queue reacts — round 1's whole promise, delivered.
* After **S7**: URLs follow Chrome and every row tells the truth about job eligibility.
* After **S9**: the operator can *see* all of it. Observability last is a choice, not an afterthought:
  every earlier stage is verifiable by tests and logs without the window, and the window is the only
  stage that would have to be rebuilt if the behaviour stages changed shape.

---

## 10. Invariants (append to SYSTEM_OF_RECORD §5 with the code; never renumber)

| ID | Invariant | Enforcement |
|---|---|---|
| **I-43** *(S8)* | The Python/JS window registries are one contract: identical ids, order and titles, and every registered window has a DOM element that the grid mounts — a panel whose `data-window` is not registered is **destroyed** by `render()` (L-5) | `core/window_catalog.py` + `tests/test_window_catalog.py`, `tests/test_grid_layout.py:117-121`, `tests/js/test_live_debug_panel.mjs` |
| **I-44** *(S3)* | A page's generation timeout is paused for exactly the time that page spends waiting for a captcha to clear, and only then; the pause is **capped** at `watcher_captcha_timeout_sec` per generation wait, the wait itself ends at the same cap with an honest `wait_timeout` failure, and both the absorbed pause and the cap are reported (failure text + debug window), never silent. Watcher OFF ⇒ no pause and no captcha activity of any kind (D-23) | `browser/output_wait.py` (`PauseClock`) + `captcha/policy.WaitDeadline` + `tests/test_pause_clock.py`, `test_output_wait_timeout_pause.py`, `test_captcha_wait_cap.py`, `test_watcher_off_zero_activity.py` |
| **I-45** *(S7)* | URL-row receiver eligibility has one owner (Python `url_policy.mark_receivers`); the web UI reflects the flag and never recomputes it | `services/live/url_policy.py` + `tests/test_url_receivers.py`, `tests/js/test_url_list_receiver_icon.mjs` |
| **I-46** *(S4)* | Every reset (`reset_image`, `reset_all`) returns images to `pending` **and** `selected`, ends in `commit_queue`, and is undoable; no reset parks work | `ui/panels/run_control.py` + `tests/test_reset_requeues.py` |

Amended in the same change, **each in the stage that makes it true** (D-24b):
**I-19 / I-34 / RULE 20 / I-40** *(S2 for the OFF half, S3 for the capped-pause half)* — Watcher OFF =
captcha out of scope, *counted* zero side effects (D-23), Watcher ON = detect + wait + penalty + logs +
**paused generation timeout**, solving only with a stored key; **I-42** *(S6)* — round-1's fixed 5 s
reconcile pass becomes the user-set `url_reconcile_interval_ms`; **I-33 / I-37** *(S7)* — rows stay
Python-owned and the row view carries the receiver flag, written by the reconciler/`commit_urls`;
**I-35** *(S6 for `UrlInterval`, S9 for `LiveDebugPanel`)* — every new panel module publishes itself.

---

## 11. Risks

| # | Risk | Mitigation |
|---|---|---|
| R11 | ~~An unbounded pause hangs a job forever~~ **closed by D-14R**: the worst case per image is now `generation_timeout + watcher_captcha_timeout_sec` | cap cumulative per generation wait; wait ends at the cap with `wait_timeout`; Stop/abort still wins earlier; per-tab Stop already exists (I-31) |
| R21 | The cap is too small for a slow manual solve ⇒ a job fails that a longer wait would have saved | One user knob (default 300 s, clamp 10…3600, editable in the Watcher window, read per wait ⇒ no restart); the failure text names it (`Captcha not cleared in Ns`); the debug window shows absorbed/remaining pause budget next to the paused worker |
| R22 | Two captchas in one generation each absorb a full cap ⇒ the pause becomes unbounded again through the back door | `PauseClock.total` is cumulative **per generation wait**, so the second settle charges nothing once the budget is gone (§5.2 last row) — asserted by `test_pause_clock.py` |
| R23 | **Staging trap**: an integrator runs `--record-baseline` after a stage, freezing that stage's *new* `.js` files, and a later stage can no longer grow them | D-24a: a stage's new JS files are complete inside the stage; later stages add **new** files (`url-list/interval.js` in S6, the four `live-debug/*.js` in S9 — no overlap). The fast lane after every stage catches a breach immediately (`verify_quality.py:762-812`) |
| R24 | **Docs drift** across ten stages: `docs/current/` ends up describing a half-built system | D-24b + §9.3: every stage names the rows it updates in the same commit; S10 only *verifies* consistency and refreshes `QUALITY_RECHECK.md` |
| R25 | The chain is interrupted (owner stops it mid-way) and a contract is left half-changed | Each stage is shippable (§9.5 value prefixes) and §9.4 lists the edits that must never be split across commits; the only contract changes (S8 window set, S4 slot tails) are atomic inside their stage |
| R26 | Two stages touch the same frozen JS file from different directions (S6 deletes the `cdp.js` interval; S7 edits `url-list/render.js`; S8/S9 edit three registries) | Every one of those edits is net-zero-or-negative in lines/funcs (§3.2 ledger) and the JS lane is global (it measures *all* baselined files on any JS change), so a conflict shows up as a gate failure in the stage that causes it, not later |
| R12 | Pause clock charged for non-captcha slowness | Charged **only** around `settler()`, which only runs when the dialog is visible *and* the settler is installed (Watcher ON) — `clock.total` stays 0 otherwise; unit test asserts 0 charge on a slow-but-clean poll |
| R13 | Reset All re-queues 500 images by accident (the reason round 1 parked it) | The owner overruled it explicitly (D-16); Undo restores prior statuses (`push_queue_undo`), one log line names the count, and the live loop still respects per-tab cooldowns, so the batch cannot storm one tab |
| R14 | The 16-window contract desyncs Python vs JS again | `test_grid_layout.py:117-121` already compares the parsed JS table with Python; `tests/test_window_catalog.py` adds the element-id map (`_collectPanels`) to the same guard |
| R15 | Rescuing the pool markup breaks `PagePoolPanel` (ids, listeners) | Markup moved **verbatim** (ids preserved), the four pool JS files untouched, `tests/js/test_live_debug_panel.mjs` boots the real `index.html` script list and asserts the pool table renders into a *mounted* element |
| R16 | A frozen JS file grows by one line and the whole gate fails | Every JS edit in this wave is net-zero (evidence §6.1 ledger); `verify_quality --changed` after each step; new behaviour only in new files |
| R17 | The new panel duplicates the pool table (jscpd 1.240 %) | The job-line list is job-centric (image, phase, elapsed, job id) while the pool table stays tab-centric with cooldown controls; no shared template strings; duplication measured at **S10** |
| R18 | `next_image` misleads when the parallel lane dispatches out of order | The label reads *"next in queue"* and the worker lines show what is actually running; `live_view` documents that the dispatcher picks tabs, not images (`multi_page_dispatcher._acquire_free_in`), image order stays `eligible[0]` |
| R19 | Interval set to 500 ms hammers CDP `/json` | Clamp floor 500 ms + the pass itself is the cost (one fetch); wake-triggered passes are deduped by the round-1 `LiveBus`; the debug window shows the last-pass age so a too-small value is visible |
| R20 | Coverage floors drop in touched legacy files | Per-file floors listed in `quality-budget.md` §3; new logic lives in new fully-tested files; `--coverage-ratchet` mode for the mid-wave runs |

---

## 12. Out of scope (explicit follow-ups)

1. Registering `page_pool` as its **own** window in addition to `live_debug` (D-21 rejects it: two
   worker tables). If the owner wants the pool controls in a separate window, that is a one-line
   catalog change plus markup, in a later round.
2. Persisting `url_policy` memory and receiver history across restarts (round-1 follow-up 3).
3. A per-worker **sparkline**/history (jobs over time) in the debug window — the data
   (`jobs_completed`, `captcha_count`, `rate_limit_count`) is already in the snapshot; a chart is a
   new JS surface with its own budget.
4. Making the passive `WatcherService` retire (round-1 follow-up 1) — still a RULE 10 tension, still
   its own round.
5. Moving the JS 500 ms `ensurePrimary` tick into Python (round-1 follow-up 2).
6. **Decoupling** the two caps — a separate `captcha_pause_cap_sec` so the pause budget and the wait
   length can differ. D-14R deliberately uses one knob (`watcher_captcha_timeout_sec`); the flip is one
   config key + one clamp + one `PauseClock(cap=…)` argument.
7. Any new bridge slot or signal (D-20/D-22 forbid both; if a future feature needs one, it is a
   contract review like the 134-slot freeze).
8. Re-merging the stages into one wave (rev 1's shape) — the owner asked for the chain; if a future
   round needs a single drop, S1…S9 are already ordered so that squashing them is a merge, not a
   redesign.
9. Splitting S9 further (queue head / worker lines / cadence as three stages): the four JS files must
   land together because the panel publishes itself once (I-35) and its data contract is one payload.

## 13. End-of-plan recheck (RULE 16 / 17 / 18 / 19 / 20) — required by the brief

Run once against the whole plan, and again per stage from the stage's own rows.

| Rule | Where this plan satisfies it | Status |
|---|---|---|
| **RULE 16.6 process** (understand → design doc → tests first → measure → docs same change) | Understand: `evidence.md` §1-§8 (every claim carries `file:line`). Design doc: this folder, archived per RULE 17. Tests first: §9.3 names the proving test of every stage; §9.1.1 makes it a stage gate. Measure: `quality-budget.md` §1 fast lane after every stage, §3 per-file maxima, §4 symbol budgets. Docs same change: §9.1.5 + D-24b + `quality-budget.md` §7 | ✓ |
| **RULE 16.0-16.5 gates** | Hard limits respected by construction: no new symbol > 30 LOC / > 4 params / CC > 10 / nesting > 4 (§4 budgets); legacy offenders (`single_job_runner` 902, `cooldown_service` 787, `Bridge`, `CDPArenaController`) are **not grown** — `cooldown_service.py` is not edited at all (the cap composes into the caller's `stop`); `_manual_wait` (span 27 = file max) **shrinks** to ~21 via `_wait_outcome` (§5.3). `live/__init__.py` re-export carries the §16.0 waiver comment | ✓ |
| **RULE 16.7 acceptance checklist** | Mirrored line-for-line in `quality-budget.md` §8.0 (per stage) + §8.1 (S10), including "no new function > 30 LOC", "coverage ≥ baseline (86.09/82.01)", "every new function has a test that fails if deleted", "no new vulture/duplication findings", "no gaming" | ✓ |
| **RULE 17 one current doc, dated archive** | Plan lives in `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/`, indexed by the `docs/README.md` bullet + footer; `docs/current/SYSTEM_OF_RECORD.md` and `AGENT_RULES.md` stay **untouched until code lands** — and then each stage updates only its own rows (§9.3, D-24b), so no stage ever leaves `current/` describing a system that does not exist | ✓ |
| **RULE 18 ideal sizes** | `quality-budget.md` §5: function 4-20 (2 documented deviations, both loops), file 150-300 (`layout_service` 300 → ~272 improved; the two over-ideal modules `browser` 23 / `ui/panels` 16 are **not worsened**), module 5-15 (`core` 14, `services/live` 7, `captcha` 7), context 60-200, sub-150 files each justified as one decision | ✓ |
| **RULE 19 fix complexity before size** | Data before branches in every stage: `receiver` flag (S7), `live` payload dict (S4/S6/S9), `wait_reason` + scope tables (S2/S3), `PauseClock` value (S3), `window_catalog` table (S8) — no new if/elif chains; and the chain *removes* complexity: S4 deletes the duplicated eligibility rule, S6 deletes the JS 15 s timer, S3 shrinks `_manual_wait`, S8 deletes the dead `winPagePool` markup | ✓ |
| **RULE 20 CAPTCHA policy** | Amended by D-14R + D-23 (applied in S2/S3; the one-knob choice and its follow-up are §12 item 6): default manual, opt-in owner-authorized 2Captcha; Watcher OFF ⇒ **no captcha activity of any kind**; ON ⇒ the wait is **bounded** by `watcher_captcha_timeout_sec`, which also caps the per-page timeout pause; at the cap the job fails honestly as `wait_timeout` (retryable, no penalty) | ✓ |
| **Plan-only constraint** | `git status` for this revision shows **docs only** (`design.md`, `evidence.md`, `quality-budget.md`, `docs/README.md`); no file under `app/`, `tools/`, `tests/` was touched. Revision 1 remains in git at `a5f69ee` | ✓ |
| **RULE 8 tests execute the real thing** | Every JS test boots the real `index.html` script list (`test_boot_all_panels.mjs` pattern) and the real registry tables; the Python tests drive real objects (real `PauseClock` in a real `output_wait` loop, real `commit_queue` through real slots) — no mock of the thing under test | ✓ |

**Residual risks carried into implementation** (all recorded, none blocking): R23/R24/R25/R26 (the four
staging risks, §11) and the single open owner question in §12 item 6 (whether the pause cap deserves its own
`captcha_pause_cap_sec` key instead of sharing `watcher_captcha_timeout_sec`). The plan defaults to
sharing it, because D-14R was stated in terms of the existing knob.
